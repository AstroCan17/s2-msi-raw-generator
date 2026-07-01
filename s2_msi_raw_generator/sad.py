# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Satellite Ancillary Data (SAD) — real AOCS attitude + orbit ephemeris + thermal for the L0 ISP.

The real S2A ``S2A_OPER_AUX_SADATA_*`` / HKTM binary inner layout is proprietary (S2 PDGS ISP ICD, not
public), so a bit-exact decode is infeasible. This module degrades gracefully in three tiers:

1. **Outer framing decode** (real, optional): :func:`scan_ccsds_packets` / :func:`decode_sadata_framing`
   parse the CCSDS Space-Packet boundaries (APID, length, CUC time) of a real SADATA/HKTM stream.
2. **Inner AOCS/orbit synthesis** (physically real values): :func:`synth_orbit_attitude` propagates a
   Sentinel-2 sun-synchronous circular orbit (ECEF position/velocity), a nadir/velocity-aligned attitude
   quaternion, and a slow thermal cycle — numpy-only, no external ephemeris.
3. **Re-pack as real CCSDS ISP** (:func:`pack_sad_isp`): a documented big-endian float64 payload
   [q0..q3, x, y, z, vx, vy, vz, T] replacing the previous all-zero SAD payload.

``msi-processor`` does not consume the SAD for L1B (it is optional passthrough); this exists for product
fidelity, EOQC ``Datation_Sync``/``Time_Correlation`` and future rigorous geometry.
"""

from __future__ import annotations

import struct
import tarfile
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from . import isp
from .datation import TAI_UTC_OFFSET_S, _iso_z

# Physical constants + the Sentinel-2 reference orbit (sun-synchronous, ~786 km, i≈98.62°).
MU_EARTH = 3.986004418e14      # m³/s²
OMEGA_EARTH = 7.2921159e-5     # rad/s
R_S2 = 7.157e6                 # orbital radius (m): mean Earth radius + ~786 km altitude
INCLINATION_DEG = 98.62
DETECTOR_T0_K = 195.0          # SWIR MCT detector operating point (<195 K)
DETECTOR_DT_K = 2.0            # thermal cycle amplitude over the orbit

# Real CCSDS SAD payload: 11 big-endian float64 = quaternion(4) + position(3) + velocity(3) + thermal(1).
SAD_PAYLOAD_FMT = ">11d"
SAD_PAYLOAD_LEN = struct.calcsize(SAD_PAYLOAD_FMT)   # 88 octets


@dataclass(frozen=True)
class AocsSeries:
    """Per-sample AOCS/orbit series (ECEF), one row per SAD packet or image line."""

    times_s: np.ndarray      # (N,)   GPS seconds
    position: np.ndarray     # (N,3)  ECEF position (m)
    velocity: np.ndarray     # (N,3)  ECEF velocity (m/s)
    quaternion: np.ndarray   # (N,4)  unit attitude quaternion (w, x, y, z)
    thermal: np.ndarray      # (N,)   detector temperature (K)


def _rot_x(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _matrix_to_quaternion(rot: np.ndarray) -> np.ndarray:
    """Rotation matrix → unit quaternion ``(w, x, y, z)`` (trace method)."""
    tr = np.trace(rot)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w, x = 0.25 * s, (rot[2, 1] - rot[1, 2]) / s
        y, z = (rot[0, 2] - rot[2, 0]) / s, (rot[1, 0] - rot[0, 1]) / s
    elif rot[0, 0] > rot[1, 1] and rot[0, 0] > rot[2, 2]:
        s = np.sqrt(1.0 + rot[0, 0] - rot[1, 1] - rot[2, 2]) * 2
        w, x = (rot[2, 1] - rot[1, 2]) / s, 0.25 * s
        y, z = (rot[0, 1] + rot[1, 0]) / s, (rot[0, 2] + rot[2, 0]) / s
    elif rot[1, 1] > rot[2, 2]:
        s = np.sqrt(1.0 + rot[1, 1] - rot[0, 0] - rot[2, 2]) * 2
        w, x = (rot[0, 2] - rot[2, 0]) / s, (rot[0, 1] + rot[1, 0]) / s
        y, z = 0.25 * s, (rot[1, 2] + rot[2, 1]) / s
    else:
        s = np.sqrt(1.0 + rot[2, 2] - rot[0, 0] - rot[1, 1]) * 2
        w, x = (rot[1, 0] - rot[0, 1]) / s, (rot[0, 2] + rot[2, 0]) / s
        y, z = (rot[1, 2] + rot[2, 1]) / s, 0.25 * s
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def _nadir_quaternion(pos: np.ndarray, vel: np.ndarray) -> np.ndarray:
    """Attitude of a nadir-pointing, velocity-aligned spacecraft body frame (ECEF → body)."""
    z_body = -pos / np.linalg.norm(pos)              # +Z_body toward Earth (nadir)
    y_body = np.cross(z_body, vel / np.linalg.norm(vel))
    y_body /= np.linalg.norm(y_body)
    x_body = np.cross(y_body, z_body)
    rot = np.stack([x_body, y_body, z_body], axis=1)  # columns = body axes expressed in ECEF
    return _matrix_to_quaternion(rot)


def synth_orbit_attitude(
    times_s,
    *,
    a: float = R_S2,
    inclination_deg: float = INCLINATION_DEG,
    raan_deg: float = 0.0,
    u0_deg: float = 0.0,
) -> AocsSeries:
    """Physically-plausible S2 circular-orbit ECEF position/velocity + nadir attitude at ``times_s``."""
    t = np.atleast_1d(np.asarray(times_s, dtype=float))
    tref = t - t[0]
    n = np.sqrt(MU_EARTH / a ** 3)                    # mean motion (rad/s)
    u = np.radians(u0_deg) + n * tref                 # argument of latitude
    r_pf = a * np.stack([np.cos(u), np.sin(u), np.zeros_like(u)], axis=-1)
    v_pf = a * n * np.stack([-np.sin(u), np.cos(u), np.zeros_like(u)], axis=-1)
    q_pf2eci = _rot_z(np.radians(raan_deg)) @ _rot_x(np.radians(inclination_deg))
    r_eci = r_pf @ q_pf2eci.T
    v_eci = v_pf @ q_pf2eci.T
    theta = OMEGA_EARTH * tref                        # Earth rotation since the first sample
    omega_vec = np.array([0.0, 0.0, OMEGA_EARTH])
    pos = np.empty_like(r_eci)
    vel = np.empty_like(v_eci)
    quat = np.empty((t.size, 4))
    for i in range(t.size):
        rz = _rot_z(-theta[i])
        pos[i] = rz @ r_eci[i]
        vel[i] = rz @ (v_eci[i] - np.cross(omega_vec, r_eci[i]))  # transport theorem
        quat[i] = _nadir_quaternion(pos[i], vel[i])
    thermal = DETECTOR_T0_K + DETECTOR_DT_K * np.sin(u)
    return AocsSeries(times_s=t, position=pos, velocity=vel, quaternion=quat, thermal=thermal)


def pack_sad_isp(aocs: AocsSeries, apid: int) -> tuple[np.ndarray, np.ndarray]:
    """Pack an :class:`AocsSeries` into real CCSDS SAD ISP packets (primary header + CUC + payload)."""
    n = aocs.times_s.size
    data_field_len = isp.CUC_TIME_LEN + SAD_PAYLOAD_LEN
    out = np.empty((n, isp.PRIMARY_HEADER_LEN + data_field_len), dtype=np.uint8)
    lengths = np.full(n, data_field_len, dtype=np.uint16)
    for i in range(n):
        payload = struct.pack(SAD_PAYLOAD_FMT, *aocs.quaternion[i], *aocs.position[i],
                              *aocs.velocity[i], float(aocs.thermal[i]))
        rec = (isp.build_primary_header(apid, i, data_field_len - 1)
               + isp.cuc_time(float(aocs.times_s[i])) + payload)
        out[i] = np.frombuffer(rec, dtype=np.uint8)
    return out, lengths


def unpack_sad_payload(rec: bytes) -> dict:
    """Decode one SAD ISP record → ``{time, quaternion, position, velocity, thermal}``."""
    t = isp.parse_cuc_time(rec[isp.PRIMARY_HEADER_LEN:isp.ISP_HEADER_LEN])
    vals = struct.unpack(SAD_PAYLOAD_FMT, rec[isp.ISP_HEADER_LEN:isp.ISP_HEADER_LEN + SAD_PAYLOAD_LEN])
    return {"time": t, "quaternion": vals[0:4], "position": vals[4:7],
            "velocity": vals[7:10], "thermal": vals[10]}


def scan_ccsds_packets(buf: bytes) -> list[dict]:
    """Scan a byte buffer for consecutive CCSDS Space Packets (real outer-framing decode, tier 1)."""
    packets, off, n = [], 0, len(buf)
    while off + isp.PRIMARY_HEADER_LEN <= n:
        hdr = isp.parse_primary_header(buf[off:off + isp.PRIMARY_HEADER_LEN])
        data_len = hdr["data_len"] + 1                # CCSDS: field is (octets − 1)
        total = isp.PRIMARY_HEADER_LEN + data_len
        if off + total > n:
            break
        hdr["offset"] = off
        packets.append(hdr)
        off += total
    return packets


def decode_sadata_framing(tar_path) -> list[dict]:
    """Tier-1 real decode: CCSDS packet framing of a real ``S2A_OPER_AUX_SADATA_*`` / HKTM ``.tar``.

    Returns the aggregated packet headers (APID, sequence, length, CUC not decoded here — inner layout
    is proprietary). Enrichment only; the synthesis path (:func:`synth_orbit_attitude`) is the default.
    """
    packets: list[dict] = []
    with tarfile.open(tar_path, "r:*") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            for p in scan_ccsds_packets(f.read()):
                p["member"] = member.name
                packets.append(p)
    return packets


def aocs_to_conditions(aocs: AocsSeries) -> dict:
    """Per-line ``conditions/*`` arrays for the open-container L0 handoff (used by the E2E MR)."""
    return {
        "time/line_time": aocs.times_s.astype(np.float64),
        "orbit/position": aocs.position.astype(np.float64),
        "orbit/velocity": aocs.velocity.astype(np.float64),
        "attitude/quaternion": aocs.quaternion.astype(np.float64),
    }


def orbit_ephemeris(datation, n_lines: int) -> tuple[dict, dict]:
    """``(start, stop)`` orbit-ephemeris blocks (TAI/UTC/UT1 + ECEF position/velocity) for the metadata."""
    last = max(n_lines - 1, 0)
    aocs = synth_orbit_attitude(np.array([datation.gps_epoch_s, datation.line_time_gps(last)]))

    def point(i: int, line: int) -> dict:
        utc = datation.line_time_utc(line)
        return {
            "TAI": _iso_z(utc + timedelta(seconds=TAI_UTC_OFFSET_S)),
            "UTC": _iso_z(utc),
            "UT1": _iso_z(utc),  # |UT1−UTC| < 1 s; synthetic ⇒ equal
            "position": [round(float(x), 3) for x in aocs.position[i]],
            "velocity": [round(float(x), 3) for x in aocs.velocity[i]],
        }

    return point(0, 0), point(1, last)

"""Tests for the SAD module (REQ-FUNC-036/037): orbit/attitude synthesis + CCSDS SAD ISP."""

from __future__ import annotations

import io
import tarfile

import numpy as np
import pytest

from s2_msi_raw_generator import datation, isp, sad


def test_synth_orbit_attitude_is_physical():
    aocs = sad.synth_orbit_attitude(1.39e9 + np.arange(0, 600, 60.0))
    rmag = np.linalg.norm(aocs.position, axis=1)
    assert np.allclose(rmag, sad.R_S2, rtol=1e-6)                 # circular orbit → constant radius
    vmag = np.linalg.norm(aocs.velocity, axis=1)
    assert np.all((6.5e3 < vmag) & (vmag < 8.0e3))               # ~7.5 km/s incl. Earth rotation
    assert np.allclose(np.linalg.norm(aocs.quaternion, axis=1), 1.0, atol=1e-6)  # unit quaternion


def test_sad_isp_packs_and_round_trips():
    aocs = sad.synth_orbit_attitude(np.array([1.39e9, 1.39e9 + 10.0]))
    arr, lengths = sad.pack_sad_isp(aocs, apid=1305)
    assert arr.dtype == np.uint8 and arr.shape[0] == 2
    assert np.all(lengths == isp.CUC_TIME_LEN + sad.SAD_PAYLOAD_LEN)
    rec = bytes(arr[0])
    assert isp.parse_primary_header(rec[:6])["apid"] == 1305
    dec = sad.unpack_sad_payload(rec)
    assert np.allclose(dec["quaternion"], aocs.quaternion[0], atol=1e-9)
    assert np.allclose(dec["position"], aocs.position[0], rtol=1e-9)
    assert dec["thermal"] == pytest.approx(float(aocs.thermal[0]))
    assert dec["time"] == pytest.approx(1.39e9, abs=1.0 / 65536)


def test_scan_ccsds_packets_finds_boundaries():
    stream = b"".join(isp.build_primary_header(1305, i, 9) + b"\x00" * 10 for i in range(3))
    pkts = sad.scan_ccsds_packets(stream)
    assert [p["apid"] for p in pkts] == [1305, 1305, 1305]
    assert [p["seq_count"] for p in pkts] == [0, 1, 2]


def test_decode_sadata_framing_from_tar(tmp_path):
    stream = b"".join(isp.build_primary_header(1305, i, 9) + b"\x00" * 10 for i in range(2))
    tarp = tmp_path / "SADATA.tar"
    with tarfile.open(tarp, "w") as t:
        info = tarfile.TarInfo("SADATA_0001")
        info.size = len(stream)
        t.addfile(info, io.BytesIO(stream))
    pkts = sad.decode_sadata_framing(tarp)
    assert len(pkts) == 2 and all(p["apid"] == 1305 and p["member"] == "SADATA_0001" for p in pkts)


def test_orbit_ephemeris_metadata_blocks():
    d = datation.Datation(epoch_utc="2024-04-03T10:24:15Z")
    start, stop = sad.orbit_ephemeris(d, n_lines=2000)
    for e in (start, stop):
        assert set(e) == {"TAI", "UTC", "UT1", "position", "velocity"}
        assert e["UTC"].endswith("Z") and e["TAI"].endswith("Z")
        assert 7.0e6 < np.linalg.norm(e["position"]) < 7.3e6
    assert start["UTC"] <= stop["UTC"] and start["TAI"] > start["UTC"]


def test_l0_sad_packets_carry_real_aocs(tmp_path):
    zarr = pytest.importorskip("zarr")
    from s2_msi_raw_generator import l0product
    frames = {(4, "B03"): np.full((16, 8), 100.0)}
    l0 = l0product.reverse_to_l0_frames(frames, seed=1)
    out = str(tmp_path / "L0sad.zarr")
    l0product.write_l0_product(out, l0, with_isp=True)

    g = zarr.open_group(out, mode="r")
    apid = dict(g["measurements/d04/b03"].attrs)["apid"]
    rec = bytes(np.asarray(g[f"conditions/anc_data/s{apid}/isp"])[0])
    dec = sad.unpack_sad_payload(rec)
    assert np.linalg.norm(dec["quaternion"]) == pytest.approx(1.0, abs=1e-6)   # non-zero attitude, not placeholder zeros
    assert 7.0e6 < np.linalg.norm(dec["position"]) < 7.3e6
    oe = dict(g.attrs)["other_metadata"]["orbit_ephemeris_start"]
    assert "TAI" in oe and len(oe["position"]) == 3

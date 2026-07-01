"""S15 — CCSDS Instrument Source Packet (ISP) generation + SAD telemetry.

Implements the ATBD §5.S15 step: package the synthetic L0 detector/band frames into CCSDS Space
Packets (CCSDS 133.0-B primary header + a CUC secondary time header), and generate Satellite
Ancillary Data (SAD) packets per APID. Timestamps derive from ``sensor.LINE_PERIOD_MS``.

Layout (ATBD Annex A.9):
* ``measurements/d{DD}/b{BB}/isp_header`` — per-line packet headers (image data stays in band{BB}).
* ``conditions/anc_data/s{APID}/isp`` + ``packet_data_length`` — SAD/housekeeping telemetry.
"""

from __future__ import annotations

import numpy as np

PRIMARY_HEADER_LEN = 6   # CCSDS Space Packet primary header (octets)
CUC_TIME_LEN = 6         # secondary header: 4-octet coarse + 2-octet fine (CUC)
ISP_HEADER_LEN = PRIMARY_HEADER_LEN + CUC_TIME_LEN  # 12

SEQ_STANDALONE = 0b11    # unsegmented (standalone) packet
SEQ_COUNT_MOD = 1 << 14  # 14-bit sequence counter


def build_primary_header(
    apid: int,
    seq_count: int,
    data_len: int,
    *,
    packet_type: int = 0,      # 0 = telemetry / science
    sec_hdr_flag: int = 1,
    seq_flags: int = SEQ_STANDALONE,
    version: int = 0,
) -> bytes:
    """CCSDS 133.0-B 6-octet primary header (big-endian).

    ``data_len`` is the CCSDS *Packet Data Length* field = (octets in the packet data field) − 1.
    """
    if not 0 <= apid < (1 << 11):
        raise ValueError("APID must fit in 11 bits")
    w0 = (version << 13) | (packet_type << 12) | (sec_hdr_flag << 11) | (apid & 0x7FF)
    w1 = ((seq_flags & 0x3) << 14) | (seq_count % SEQ_COUNT_MOD)
    w2 = data_len & 0xFFFF
    return bytes([w0 >> 8, w0 & 0xFF, w1 >> 8, w1 & 0xFF, w2 >> 8, w2 & 0xFF])


def parse_primary_header(b: bytes) -> dict:
    """Inverse of :func:`build_primary_header` (for tests / decode)."""
    w0 = (b[0] << 8) | b[1]
    w1 = (b[2] << 8) | b[3]
    w2 = (b[4] << 8) | b[5]
    return {
        "version": w0 >> 13,
        "packet_type": (w0 >> 12) & 1,
        "sec_hdr_flag": (w0 >> 11) & 1,
        "apid": w0 & 0x7FF,
        "seq_flags": (w1 >> 14) & 0x3,
        "seq_count": w1 & 0x3FFF,
        "data_len": w2,
    }


def cuc_time(t_seconds: float) -> bytes:
    """6-octet CCSDS Unsegmented time Code: 4 octets coarse (s) + 2 octets fine (1/65536 s)."""
    coarse = int(t_seconds) & 0xFFFFFFFF
    fine = int(round((t_seconds - int(t_seconds)) * 65536)) & 0xFFFF
    return bytes([
        (coarse >> 24) & 0xFF, (coarse >> 16) & 0xFF, (coarse >> 8) & 0xFF, coarse & 0xFF,
        (fine >> 8) & 0xFF, fine & 0xFF,
    ])


def apid_for(detector: int, band_index: int, base: int = 1024) -> int:
    """Deterministic 11-bit APID for a (detector, band) science stream."""
    return (base + detector * 16 + band_index) & 0x7FF


def frame_isp_headers(
    frame: np.ndarray,
    apid: int,
    *,
    t0_seconds: float = 0.0,
    line_period_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-line ISP headers for a detector/band frame (image data itself stays in ``band{BB}``).

    Returns ``(headers, packet_data_length)``:

    * ``headers``  — uint8 ``(n_lines, ISP_HEADER_LEN)`` primary + CUC-time header per line.
    * ``packet_data_length`` — uint16 ``(n_lines,)`` octet count of each packet's data field
      (= CUC secondary header + one image line of uint16 samples).
    """
    n_lines, cols = frame.shape
    data_field_len = CUC_TIME_LEN + cols * 2  # secondary header + line samples (2 octets each)
    headers = np.empty((n_lines, ISP_HEADER_LEN), dtype=np.uint8)
    lengths = np.full(n_lines, data_field_len, dtype=np.uint16)
    for i in range(n_lines):
        t = t0_seconds + i * line_period_s
        ph = build_primary_header(apid, i, data_field_len - 1)
        headers[i] = np.frombuffer(ph + cuc_time(t), dtype=np.uint8)
    return headers, lengths


def build_sad_packets(
    apid: int,
    n_packets: int,
    *,
    t0_seconds: float = 0.0,
    period_s: float,
    payload: bytes = b"\x00" * 16,
) -> tuple[np.ndarray, np.ndarray]:
    """Satellite Ancillary Data (housekeeping) packets for one APID.

    Returns ``(isp, packet_data_length)``: ``isp`` is uint8 ``(n_packets, header+payload)``,
    ``packet_data_length`` is uint16 ``(n_packets,)``.
    """
    data_field_len = CUC_TIME_LEN + len(payload)
    rec_len = PRIMARY_HEADER_LEN + data_field_len
    isp = np.empty((n_packets, rec_len), dtype=np.uint8)
    lengths = np.full(n_packets, data_field_len, dtype=np.uint16)
    for i in range(n_packets):
        t = t0_seconds + i * period_s
        rec = build_primary_header(apid, i, data_field_len - 1) + cuc_time(t) + payload
        isp[i] = np.frombuffer(rec, dtype=np.uint8)
    return isp, lengths

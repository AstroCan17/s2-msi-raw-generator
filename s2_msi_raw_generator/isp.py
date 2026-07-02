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
SEQ_FIRST = 0b01         # first packet of a segmented group
SEQ_CONT = 0b00          # continuation packet
SEQ_LAST = 0b10          # last packet of a segmented group
SEQ_COUNT_MOD = 1 << 14  # 14-bit sequence counter

#: Default maximum packet-data-field payload (octets, excl. the CUC secondary header).
DEFAULT_MAX_PAYLOAD = 8192


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


def parse_cuc_time(b: bytes) -> float:
    """Inverse of :func:`cuc_time` — 6 octets → seconds (4-octet coarse + 2-octet fine / 65536)."""
    coarse = (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]
    fine = (b[4] << 8) | b[5]
    return coarse + fine / 65536.0


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


def packetize_stream(
    payload: bytes,
    apid: int,
    *,
    segment_bounds: list[int],
    segment_times_gps: np.ndarray,
    max_payload: int = DEFAULT_MAX_PAYLOAD,
    seq_start: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Carry a byte stream in CCSDS space packets, honouring segment grouping.

    ``segment_bounds`` are the byte offsets of segment starts within ``payload`` (ascending,
    ``segment_bounds[0] == 0``); each segment is sliced into packets of at most ``max_payload``
    data octets and flagged ``SEQ_FIRST``/``SEQ_CONT``/``SEQ_LAST`` (``SEQ_STANDALONE`` when a
    segment fits in one packet).  Every packet carries a CUC secondary header stamped with its
    segment's GPS time (``segment_times_gps``, seconds, one per segment).  The 14-bit sequence
    counter starts at ``seq_start`` and is continuous across the whole stream.

    Returns ``(isp, offsets, lengths)``: the concatenated packet stream (uint8 1-D), the byte
    offset of each packet within it (uint64), and each packet's CCSDS *Packet Data Length*
    field value + 1 = data-field octet count (uint32).
    """
    if not segment_bounds or segment_bounds[0] != 0:
        raise ValueError("segment_bounds must start at 0")
    if len(segment_times_gps) != len(segment_bounds):
        raise ValueError("one GPS time per segment required")
    if max_payload < 1 or max_payload + CUC_TIME_LEN > 0x10000:
        raise ValueError("max_payload out of range for the 16-bit Packet Data Length field")
    bounds = list(segment_bounds) + [len(payload)]
    chunks: list[bytes] = []
    offsets: list[int] = []
    lengths: list[int] = []
    pos = 0
    seq = seq_start
    for si in range(len(segment_bounds)):
        s0, s1 = bounds[si], bounds[si + 1]
        if s1 < s0:
            raise ValueError("segment_bounds must be ascending")
        cuc = cuc_time(float(segment_times_gps[si]))
        n_pkts = max(1, -(-(s1 - s0) // max_payload))
        for pi in range(n_pkts):
            p0 = s0 + pi * max_payload
            body = payload[p0:min(p0 + max_payload, s1)]
            if n_pkts == 1:
                flags = SEQ_STANDALONE
            elif pi == 0:
                flags = SEQ_FIRST
            elif pi == n_pkts - 1:
                flags = SEQ_LAST
            else:
                flags = SEQ_CONT
            data_field = cuc + body
            rec = build_primary_header(apid, seq, len(data_field) - 1, seq_flags=flags) + data_field
            offsets.append(pos)
            lengths.append(len(data_field))
            chunks.append(rec)
            pos += len(rec)
            seq += 1
    stream = np.frombuffer(b"".join(chunks), dtype=np.uint8).copy()
    return stream, np.asarray(offsets, dtype=np.uint64), np.asarray(lengths, dtype=np.uint32)


def iter_packets(buf: bytes | np.ndarray):
    """Iterate CCSDS packets in a concatenated stream → ``(header dict, cuc_seconds, body bytes)``.

    Shared by our reassembly and by structural scans of real ISP files: the primary header's
    *Packet Data Length* field walks the stream; a stream is well-formed iff packets tile it
    exactly.  ``body`` excludes the CUC secondary header.
    """
    data = bytes(bytearray(np.asarray(buf, dtype=np.uint8))) if not isinstance(buf, (bytes, memoryview)) else bytes(buf)
    pos = 0
    while pos < len(data):
        if pos + PRIMARY_HEADER_LEN > len(data):
            raise ValueError(f"truncated primary header at offset {pos}")
        hdr = parse_primary_header(data[pos:pos + PRIMARY_HEADER_LEN])
        dlen = hdr["data_len"] + 1
        end = pos + PRIMARY_HEADER_LEN + dlen
        if end > len(data):
            raise ValueError(f"packet at offset {pos} overruns the stream")
        field = data[pos + PRIMARY_HEADER_LEN:end]
        cuc = parse_cuc_time(field[:CUC_TIME_LEN]) if hdr["sec_hdr_flag"] and dlen >= CUC_TIME_LEN else None
        body = field[CUC_TIME_LEN:] if hdr["sec_hdr_flag"] and dlen >= CUC_TIME_LEN else field
        yield hdr, cuc, body
        pos = end


def reassemble_segments(buf: bytes | np.ndarray) -> list[bytes]:
    """Inverse of :func:`packetize_stream`: packets → per-segment byte streams.

    Enforces seq_flags grammar (FIRST → CONT* → LAST, or STANDALONE) and 14-bit sequence-counter
    continuity; raises ``ValueError`` on gaps or malformed flag sequences.
    """
    segments: list[bytes] = []
    current: list[bytes] | None = None
    prev_seq: int | None = None
    for hdr, _cuc, body in iter_packets(buf):
        if prev_seq is not None and hdr["seq_count"] != (prev_seq + 1) % SEQ_COUNT_MOD:
            raise ValueError(f"sequence gap: {prev_seq} → {hdr['seq_count']}")
        prev_seq = hdr["seq_count"]
        flags = hdr["seq_flags"]
        if flags == SEQ_STANDALONE:
            if current is not None:
                raise ValueError("STANDALONE inside an open segmented group")
            segments.append(body)
        elif flags == SEQ_FIRST:
            if current is not None:
                raise ValueError("FIRST inside an open segmented group")
            current = [body]
        elif flags == SEQ_CONT:
            if current is None:
                raise ValueError("CONTINUATION without FIRST")
            current.append(body)
        elif flags == SEQ_LAST:
            if current is None:
                raise ValueError("LAST without FIRST")
            current.append(body)
            segments.append(b"".join(current))
            current = None
    if current is not None:
        raise ValueError("stream ended inside a segmented group")
    return segments

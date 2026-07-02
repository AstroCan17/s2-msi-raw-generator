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

"""CCSDS 122.0-B image-data compression — **lossless subset** (integer DWT + bit-plane coder).

Sentinel-2 compresses MSI video data onboard with the proprietary **MRCPB** wavelet scheme
(bit-plane coding, "similar to JPEG 2000"); a CCSDS-compression ASIC is the documented
*alternative* option (eoPortal, S2 CoReCi).  This module implements that alternative —
CCSDS 122.0-B — in its **lossless profile**, pure numpy, so the generator's L0 ISP payloads
carry genuinely wavelet-compressed image data and the ground segment (L1A side) can restore
the exact DN.

Implemented per the Blue Book structure
---------------------------------------

- **Integer DWT 9/7-M** (CCSDS 122.0-B §3.3): three 2-D decomposition levels, lifting form
  with the specified ``floor(·+1/2)`` rounding and whole-sample symmetric extension;
  exactly invertible on integers.
- **Block/family structure** (§4.1): one 8×8 pixel area → 1 DC + 63 AC coefficients in
  three families (parent, 2×2 children, 4×4 grandchildren per family), raster scan;
  **gaggles** of 16 blocks; **segments** of ``segment_blocks`` blocks.
- **Segment headers** (§4.2): the Part-1A/3/4 semantic content (start/end flags, segment
  count, ``BitDepthDC``/``BitDepthAC``, segment size, DWT type, pixel bit depth, image
  dimensions) is carried in an explicit little-endian layout (see ``parse_segment_headers``);
  the stream is fully self-describing.
- **DC coefficient coding** (§4.3): per-segment DPCM against a raw reference sample,
  zigzag signed→nonnegative mapping, per-gaggle Rice coding with brute-force parameter
  selection and an uncoded escape option.
- **Per-block BitDepthAC** (§4.4): same DPCM + per-gaggle Rice machinery.

Documented divergences (kept deliberately small, listed in the ICD/ATBD)
------------------------------------------------------------------------

1. **§4.5.3 word mapping / variable-length codes are not implemented.**  AC bit-plane
   coding keeps the stage semantics and scan order (significance → sign → refinement,
   plane-sequential from ``BitDepthAC−1`` down to 0, block-major within a segment) but the
   per-stage bits are packed **raw** (``numpy.packbits``) instead of entropy-coded words.
   Consequence: bit-exact lossless with the full segment/gaggle/block/plane structure, but
   the stream is *not interoperable* with reference CCSDS-122 decoders (the matching
   decoder lives in this module) and ratios run below a full BPE.
2. **Header field packing** uses explicit byte-aligned little-endian fields (with section
   byte-lengths) rather than the Blue Book bit layout; the *content* mirrors Parts 1A/3/4.
3. Sections are byte-aligned; the Blue Book packs them contiguously.

The API is frame-oriented: :func:`compress_frame` → ``(payload bytes, CompressionStats)``
and :func:`decompress_frame` → the exact ``uint16`` DN frame.  Segments default to one
block row (8 image lines) so packetization downstream maps segments to CCSDS space-packet
groups with line-accurate datation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

#: Frame-stream magic (8 bytes) + container version.
MAGIC = b"C122LSv1"
_VERSION = 1

#: Blocks per gaggle (CCSDS 122.0-B §4.1).
GAGGLE_BLOCKS = 16

#: Rice escape parameter value marking an uncoded (raw) gaggle.
_RICE_ESCAPE = 31

_FRAME_HDR = struct.Struct("<8sBBIIBBII")   # magic, ver, levels, height, width, bitdepth, pad_flags, seg_blocks, n_segments
_SEG_HDR = struct.Struct("<BIBBIII")        # flags, n_blocks, bitdepth_dc, bitdepth_ac, len_dc, len_bda, len_ac


@dataclass
class CompressionStats:
    """Byte accounting of one compressed frame."""

    raw_bytes: int
    compressed_bytes: int
    n_segments: int
    n_blocks: int
    pixel_bit_depth: int
    dc_bytes: int
    bitdepth_ac_bytes: int
    ac_bytes: int
    header_bytes: int

    @property
    def ratio(self) -> float:
        """Raw ÷ compressed size (packed-sample raw, ``pixel_bit_depth`` bits/px)."""
        return self.raw_bytes / self.compressed_bytes if self.compressed_bytes else float("nan")

    @property
    def bits_per_pixel(self) -> float:
        """Compressed bits per pixel."""
        raw_px = self.raw_bytes * 8 / self.pixel_bit_depth
        return self.compressed_bytes * 8 / raw_px if raw_px else float("nan")


# ---------------------------------------------------------------------------
# Integer DWT 9/7-M (§3.3) — lifting, whole-sample symmetric extension
# ---------------------------------------------------------------------------

def _dwt1d_forward(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One 9/7-M lifting level along the last axis (even length ≥ 4). Returns (low, high)."""
    xe = x[..., 0::2].astype(np.int64)
    xo = x[..., 1::2].astype(np.int64)
    xep = np.pad(xe, [(0, 0)] * (xe.ndim - 1) + [(1, 2)], mode="reflect")
    # D_j = X_{2j+1} - floor((9(X_{2j}+X_{2j+2}) - (X_{2j-2}+X_{2j+4}) + 8) / 16)
    d = xo - ((9 * (xep[..., 1:-2] + xep[..., 2:-1]) - (xep[..., :-3] + xep[..., 3:]) + 8) >> 4)
    # S_j = X_{2j} - floor((-(D_{j-1}+D_j) + 2) / 4),  D_{-1} = D_0
    dm1 = np.concatenate([d[..., :1], d[..., :-1]], axis=-1)
    s = xe - ((-(dm1 + d) + 2) >> 2)
    return s, d


def _dwt1d_inverse(s: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Exact inverse of :func:`_dwt1d_forward` along the last axis."""
    s = s.astype(np.int64)
    d = d.astype(np.int64)
    dm1 = np.concatenate([d[..., :1], d[..., :-1]], axis=-1)
    xe = s + ((-(dm1 + d) + 2) >> 2)
    xep = np.pad(xe, [(0, 0)] * (xe.ndim - 1) + [(1, 2)], mode="reflect")
    xo = d + ((9 * (xep[..., 1:-2] + xep[..., 2:-1]) - (xep[..., :-3] + xep[..., 3:]) + 8) >> 4)
    out = np.empty(s.shape[:-1] + (s.shape[-1] * 2,), dtype=np.int64)
    out[..., 0::2] = xe
    out[..., 1::2] = xo
    return out


def dwt97m_forward(frame: np.ndarray, levels: int = 3) -> dict[str, np.ndarray]:
    """3-level (default) 2-D integer 9/7-M DWT → subband dict ``LL<n>, HL<l>, LH<l>, HH<l>``.

    Rows are transformed first, then columns; the recursion descends into ``LL``.
    Input dimensions must be divisible by ``2**levels``.
    """
    a = frame.astype(np.int64)
    if any(s % (1 << levels) for s in a.shape):
        raise ValueError(f"frame shape {a.shape} not divisible by {1 << levels}")
    bands: dict[str, np.ndarray] = {}
    ll = a
    for lev in range(1, levels + 1):
        lo, hi = _dwt1d_forward(ll)                      # along width
        llc, lhc = _dwt1d_forward(lo.swapaxes(-1, -2))   # along height of low part
        hlc, hhc = _dwt1d_forward(hi.swapaxes(-1, -2))
        ll = llc.swapaxes(-1, -2)
        bands[f"HL{lev}"] = hlc.swapaxes(-1, -2)
        bands[f"LH{lev}"] = lhc.swapaxes(-1, -2)
        bands[f"HH{lev}"] = hhc.swapaxes(-1, -2)
    bands[f"LL{levels}"] = ll
    return bands


def dwt97m_inverse(bands: dict[str, np.ndarray], levels: int = 3) -> np.ndarray:
    """Exact inverse of :func:`dwt97m_forward`."""
    ll = bands[f"LL{levels}"].astype(np.int64)
    for lev in range(levels, 0, -1):
        hl = bands[f"HL{lev}"]
        lh = bands[f"LH{lev}"]
        hh = bands[f"HH{lev}"]
        lo = _dwt1d_inverse(ll.swapaxes(-1, -2), lh.swapaxes(-1, -2)).swapaxes(-1, -2)
        hi = _dwt1d_inverse(hl.swapaxes(-1, -2), hh.swapaxes(-1, -2)).swapaxes(-1, -2)
        ll = _dwt1d_inverse(lo, hi)
    return ll


# ---------------------------------------------------------------------------
# Block/family gather & scatter (§4.1)
# ---------------------------------------------------------------------------

def _gather_blocks(bands: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Subbands → per-block coefficients: ``(dc (nb,), ac (nb, 63))`` in raster block order."""
    ll = bands["LL3"]
    h8, w8 = ll.shape
    dc = ll.reshape(-1)
    fams = []
    for fam in ("HL", "LH", "HH"):
        parent = bands[f"{fam}3"].reshape(h8, w8, 1)
        ch = bands[f"{fam}2"].reshape(h8, 2, w8, 2).transpose(0, 2, 1, 3).reshape(h8, w8, 4)
        gc = bands[f"{fam}1"].reshape(h8, 4, w8, 4).transpose(0, 2, 1, 3).reshape(h8, w8, 16)
        fams.append(np.concatenate([parent, ch, gc], axis=2))
    ac = np.concatenate(fams, axis=2).reshape(-1, 63)
    return dc, ac


def _scatter_blocks(dc: np.ndarray, ac: np.ndarray, h8: int, w8: int) -> dict[str, np.ndarray]:
    """Exact inverse of :func:`_gather_blocks`."""
    bands = {"LL3": dc.reshape(h8, w8)}
    ac3 = ac.reshape(h8, w8, 63)
    for i, fam in enumerate(("HL", "LH", "HH")):
        seg = ac3[:, :, i * 21:(i + 1) * 21]
        bands[f"{fam}3"] = seg[:, :, 0]
        bands[f"{fam}2"] = seg[:, :, 1:5].reshape(h8, w8, 2, 2).transpose(0, 2, 1, 3).reshape(h8 * 2, w8 * 2)
        bands[f"{fam}1"] = seg[:, :, 5:21].reshape(h8, w8, 4, 4).transpose(0, 2, 1, 3).reshape(h8 * 4, w8 * 4)
    return bands


# ---------------------------------------------------------------------------
# Bit I/O
# ---------------------------------------------------------------------------

class _BitWriter:
    """Accumulates 0/1 bit arrays; packs to bytes at the end."""

    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []

    def bits(self, arr: np.ndarray) -> None:
        self._chunks.append(np.asarray(arr, dtype=np.uint8))

    def uints(self, vals: np.ndarray, nbits: int) -> None:
        """Fixed-width big-endian-within-field unsigned integers."""
        if nbits == 0:
            return
        v = np.asarray(vals, dtype=np.uint64).reshape(-1, 1)
        shifts = np.arange(nbits - 1, -1, -1, dtype=np.uint64)
        self._chunks.append(((v >> shifts) & 1).astype(np.uint8).reshape(-1))

    def getvalue(self) -> bytes:
        if not self._chunks:
            return b""
        allbits = np.concatenate(self._chunks)
        return np.packbits(allbits).tobytes()


class _BitReader:
    """Sequential reader over a packed bit section."""

    def __init__(self, data: bytes) -> None:
        self._bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        self._pos = 0

    def bits(self, n: int) -> np.ndarray:
        out = self._bits[self._pos:self._pos + n]
        if out.size != n:
            raise ValueError("bitstream underrun")
        self._pos += n
        return out

    def uints(self, count: int, nbits: int) -> np.ndarray:
        if nbits == 0:
            return np.zeros(count, dtype=np.int64)
        raw = self.bits(count * nbits).reshape(count, nbits).astype(np.uint64)
        shifts = np.arange(nbits - 1, -1, -1, dtype=np.uint64)
        return (raw << shifts).sum(axis=1).astype(np.int64)

    def unary(self, count: int) -> np.ndarray:
        """Read ``count`` unary-coded values (q ones terminated by a zero each)."""
        zeros = np.flatnonzero(self._bits[self._pos:] == 0)
        if zeros.size < count:
            raise ValueError("bitstream underrun (unary)")
        ends = zeros[:count]
        starts = np.concatenate([[0], ends[:-1] + 1])
        q = ends - starts
        self._pos += int(ends[-1]) + 1
        return q.astype(np.int64)


# ---------------------------------------------------------------------------
# Rice/DPCM coding of DC coefficients and per-block BitDepthAC (§4.3 / §4.4)
# ---------------------------------------------------------------------------

def _zigzag(d: np.ndarray) -> np.ndarray:
    return np.where(d >= 0, d << 1, (-d << 1) - 1).astype(np.int64)


def _unzigzag(m: np.ndarray) -> np.ndarray:
    return np.where(m & 1, -((m + 1) >> 1), m >> 1).astype(np.int64)


def _rice_encode(w: _BitWriter, vals: np.ndarray, raw_bits: int) -> None:
    """Per-gaggle Rice coding of nonnegative ``vals`` with brute-force k + raw escape.

    Each gaggle of :data:`GAGGLE_BLOCKS` values carries a 5-bit parameter: ``k`` (0–30)
    for Rice, or 31 for an uncoded gaggle at ``raw_bits`` bits/value.
    """
    vals = np.asarray(vals, dtype=np.int64)
    for g0 in range(0, vals.size, GAGGLE_BLOCKS):
        g = vals[g0:g0 + GAGGLE_BLOCKS]
        best_k, best_cost = _RICE_ESCAPE, raw_bits * g.size
        for k in range(min(raw_bits + 1, _RICE_ESCAPE)):
            cost = int((g >> k).sum()) + g.size * (1 + k)
            if cost < best_cost:
                best_k, best_cost = k, cost
        w.uints(np.array([best_k]), 5)
        if best_k == _RICE_ESCAPE:
            w.uints(g, raw_bits)
        else:
            q = (g >> best_k).astype(np.int64)
            total = int(q.sum()) + q.size
            bits = np.ones(total, dtype=np.uint8)
            bits[np.cumsum(q + 1) - 1] = 0
            w.bits(bits)
            w.uints(g & ((1 << best_k) - 1), best_k)


def _rice_decode(r: _BitReader, count: int, raw_bits: int) -> np.ndarray:
    out = np.empty(count, dtype=np.int64)
    for g0 in range(0, count, GAGGLE_BLOCKS):
        n = min(GAGGLE_BLOCKS, count - g0)
        k = int(r.uints(1, 5)[0])
        if k == _RICE_ESCAPE:
            out[g0:g0 + n] = r.uints(n, raw_bits)
        else:
            q = r.unary(n)
            rem = r.uints(n, k)
            out[g0:g0 + n] = (q << k) | rem
    return out


def _encode_dpcm(vals: np.ndarray, ref_bits: int) -> bytes:
    """Reference sample (two's complement, ``ref_bits``) + zigzag DPCM Rice stream."""
    w = _BitWriter()
    ref = int(vals[0])
    w.uints(np.array([ref & ((1 << ref_bits) - 1)]), ref_bits)
    if vals.size > 1:
        _rice_encode(w, _zigzag(np.diff(vals)), raw_bits=ref_bits + 1)
    return w.getvalue()


def _decode_dpcm(data: bytes, count: int, ref_bits: int) -> np.ndarray:
    r = _BitReader(data)
    ref = int(r.uints(1, ref_bits)[0])
    if ref >= 1 << (ref_bits - 1):           # sign-extend two's complement
        ref -= 1 << ref_bits
    if count == 1:
        return np.array([ref], dtype=np.int64)
    diffs = _unzigzag(_rice_decode(r, count - 1, raw_bits=ref_bits + 1))
    out = np.empty(count, dtype=np.int64)
    out[0] = ref
    np.cumsum(diffs, out=out[1:])
    out[1:] += ref
    return out


# ---------------------------------------------------------------------------
# AC bit-plane coder (§4.5 stage semantics; raw-packed planes — documented divergence)
# ---------------------------------------------------------------------------

def _encode_ac_planes(ac: np.ndarray, bda_blocks: np.ndarray, bitdepth_ac: int) -> bytes:
    """Significance / sign / refinement passes, plane-sequential, block-major scan."""
    mag = np.abs(ac)
    neg = ac < 0
    sig = np.zeros(ac.shape, dtype=bool)
    w = _BitWriter()
    for b in range(bitdepth_ac - 1, -1, -1):
        elig = bda_blocks > b                            # (nb,) blocks with content at this plane
        if not elig.any():
            continue
        plane = ((mag >> b) & 1).astype(np.uint8)
        insig = (~sig) & elig[:, None]
        w.bits(plane[insig])                             # significance pass
        newly = insig & (plane == 1)
        w.bits(neg[newly].astype(np.uint8))              # sign pass
        w.bits(plane[sig & elig[:, None]])               # refinement pass
        sig |= newly
    return w.getvalue()


def _decode_ac_planes(data: bytes, bda_blocks: np.ndarray, bitdepth_ac: int, n_blocks: int) -> np.ndarray:
    mag = np.zeros((n_blocks, 63), dtype=np.int64)
    neg = np.zeros((n_blocks, 63), dtype=bool)
    sig = np.zeros((n_blocks, 63), dtype=bool)
    r = _BitReader(data)
    for b in range(bitdepth_ac - 1, -1, -1):
        elig = bda_blocks > b
        if not elig.any():
            continue
        insig = (~sig) & elig[:, None]
        n_ins = int(insig.sum())
        sbits = r.bits(n_ins).astype(bool)
        newly = np.zeros_like(sig)
        newly[insig] = sbits
        n_new = int(newly.sum())
        neg[newly] = r.bits(n_new).astype(bool)
        mag[newly] |= 1 << b
        ref_mask = sig & elig[:, None]
        n_ref = int(ref_mask.sum())
        rbits = r.bits(n_ref).astype(np.int64)
        mag[ref_mask] |= rbits << b
        sig |= newly
    return np.where(neg, -mag, mag)


# ---------------------------------------------------------------------------
# Segment & frame containers
# ---------------------------------------------------------------------------

def _need_bits_signed(vals: np.ndarray) -> int:
    """Two's-complement width covering min/max (≥ 2)."""
    lo = int(vals.min())
    hi = int(vals.max())
    need = max(hi.bit_length() + 1, (-lo - 1).bit_length() + 1 if lo < 0 else 2, 2)
    return need


def _encode_segment(dc: np.ndarray, ac: np.ndarray, first: bool, last: bool) -> bytes:
    bitdepth_dc = _need_bits_signed(dc)
    bda = np.zeros(ac.shape[0], dtype=np.int64)
    if ac.size:
        m = np.abs(ac).max(axis=1)
        # exact integer bit length, vectorized: bit_length(v) == 64 - clz(v)
        nz = m > 0
        bda[nz] = np.floor(np.log2(m[nz].astype(np.float64))).astype(np.int64) + 1
        # guard float rounding at exact powers of two
        too_big = (np.int64(1) << bda[nz]) <= m[nz]
        if too_big.any():
            idx = np.flatnonzero(nz)[too_big]
            bda[idx] += 1
    bitdepth_ac = int(bda.max()) if bda.size else 0
    dc_field = _encode_dpcm(dc, bitdepth_dc)
    bda_field = _encode_dpcm(bda, ref_bits=6)
    ac_field = _encode_ac_planes(ac, bda, bitdepth_ac) if bitdepth_ac else b""
    flags = (1 if first else 0) | (2 if last else 0)
    hdr = _SEG_HDR.pack(flags, dc.size, bitdepth_dc, bitdepth_ac,
                        len(dc_field), len(bda_field), len(ac_field))
    return hdr + dc_field + bda_field + ac_field


def _decode_segment(buf: memoryview, off: int) -> tuple[np.ndarray, np.ndarray, int]:
    flags, n_blocks, bitdepth_dc, bitdepth_ac, len_dc, len_bda, len_ac = _SEG_HDR.unpack_from(buf, off)
    off += _SEG_HDR.size
    dc = _decode_dpcm(bytes(buf[off:off + len_dc]), n_blocks, bitdepth_dc)
    off += len_dc
    bda = _decode_dpcm(bytes(buf[off:off + len_bda]), n_blocks, ref_bits=6)
    off += len_bda
    if bitdepth_ac:
        ac = _decode_ac_planes(bytes(buf[off:off + len_ac]), bda, bitdepth_ac, n_blocks)
    else:
        ac = np.zeros((n_blocks, 63), dtype=np.int64)
    off += len_ac
    return dc, ac, off


def compress_frame(dn: np.ndarray, *, pixel_bit_depth: int = 12,
                   segment_blocks: int | None = None) -> tuple[bytes, CompressionStats]:
    """Losslessly compress a 2-D DN frame → ``(payload, stats)``.

    ``segment_blocks`` defaults to one block row (``width // 8``), aligning each segment
    with 8 image lines.  The payload is fully self-describing (see module docstring).
    """
    a = np.asarray(dn)
    if a.ndim != 2:
        raise ValueError("frame must be 2-D")
    if a.size == 0:
        raise ValueError("frame is empty")
    h, w = a.shape
    pad_h = (-h) % 8
    pad_w = (-w) % 8
    if pad_h or pad_w:
        a = np.pad(a, ((0, pad_h), (0, pad_w)), mode="reflect")
    bands = dwt97m_forward(a, levels=3)
    dc, ac = _gather_blocks(bands)
    h8, w8 = a.shape[0] // 8, a.shape[1] // 8
    if segment_blocks is None:
        segment_blocks = w8
    segment_blocks = max(1, int(segment_blocks))
    n_blocks = dc.size
    seg_bounds = list(range(0, n_blocks, segment_blocks))
    parts = [_FRAME_HDR.pack(MAGIC, _VERSION, 3, a.shape[0], a.shape[1], pixel_bit_depth,
                             (pad_h << 4) | pad_w, segment_blocks, len(seg_bounds))]
    hdr_bytes = len(parts[0]) + _SEG_HDR.size * len(seg_bounds)
    dc_b = bda_b = ac_b = 0
    for i, s0 in enumerate(seg_bounds):
        s1 = min(s0 + segment_blocks, n_blocks)
        seg = _encode_segment(dc[s0:s1], ac[s0:s1], first=(i == 0), last=(s1 == n_blocks))
        _, _, _, _, ldc, lbda, lac = _SEG_HDR.unpack_from(seg, 0)
        dc_b += ldc
        bda_b += lbda
        ac_b += lac
        parts.append(seg)
    payload = b"".join(parts)
    stats = CompressionStats(
        raw_bytes=(h * w * pixel_bit_depth + 7) // 8,
        compressed_bytes=len(payload),
        n_segments=len(seg_bounds),
        n_blocks=n_blocks,
        pixel_bit_depth=pixel_bit_depth,
        dc_bytes=dc_b,
        bitdepth_ac_bytes=bda_b,
        ac_bytes=ac_b,
        header_bytes=hdr_bytes,
    )
    return payload, stats


def decompress_frame(payload: bytes | memoryview) -> np.ndarray:
    """Exact inverse of :func:`compress_frame` → ``uint16`` frame."""
    buf = memoryview(payload)
    magic, ver, levels, hh, ww, _bd, pad_flags, seg_blocks, n_segments = _FRAME_HDR.unpack_from(buf, 0)
    if magic != MAGIC or ver != _VERSION:
        raise ValueError("not a C122LS stream")
    off = _FRAME_HDR.size
    dcs, acs = [], []
    for _ in range(n_segments):
        dc, ac, off = _decode_segment(buf, off)
        dcs.append(dc)
        acs.append(ac)
    dc = np.concatenate(dcs)
    ac = np.concatenate(acs, axis=0)
    h8, w8 = hh // 8, ww // 8
    bands = _scatter_blocks(dc, ac, h8, w8)
    frame = dwt97m_inverse(bands, levels=levels)
    pad_h, pad_w = pad_flags >> 4, pad_flags & 0xF
    if pad_h or pad_w:
        frame = frame[:hh - pad_h, :ww - pad_w]
    return frame.astype(np.uint16)


def parse_segment_headers(payload: bytes | memoryview) -> dict:
    """Header inventory of a compressed stream (frame fields + per-segment Part-1A content)."""
    buf = memoryview(payload)
    magic, ver, levels, hh, ww, bd, pad_flags, seg_blocks, n_segments = _FRAME_HDR.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ValueError("not a C122LS stream")
    out = {
        "version": ver, "dwt_levels": levels, "height": hh, "width": ww,
        "pixel_bit_depth": bd, "pad_h": pad_flags >> 4, "pad_w": pad_flags & 0xF,
        "segment_blocks": seg_blocks, "n_segments": n_segments, "segments": [],
    }
    off = _FRAME_HDR.size
    for _ in range(n_segments):
        flags, n_blocks, bdc, bac, ldc, lbda, lac = _SEG_HDR.unpack_from(buf, off)
        out["segments"].append({
            "start_img": bool(flags & 1), "end_img": bool(flags & 2), "n_blocks": n_blocks,
            "bitdepth_dc": bdc, "bitdepth_ac": bac,
            "dc_bytes": ldc, "bitdepth_ac_bytes": lbda, "ac_bytes": lac,
        })
        off += _SEG_HDR.size + ldc + lbda + lac
    return out

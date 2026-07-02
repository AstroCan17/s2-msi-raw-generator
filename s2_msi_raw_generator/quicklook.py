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

"""Dependency-free quicklook PNG writer for the L0 / L1B products (numpy + stdlib only).

Renders a small RGB preview of a ``{band: 2-D array}`` product with a per-channel percentile contrast
stretch — for the repo README / documentation front page. No ``matplotlib`` / ``PIL`` dependency (a minimal PNG
encoder using ``zlib`` + ``struct``), so it runs anywhere the generator does, including the SDE.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np


def _png_bytes(rgb_u8: np.ndarray) -> bytes:
    """Encode an ``(H, W, 3)`` uint8 array to PNG bytes (colour type 2, 8-bit; pure stdlib)."""
    h, w, _ = rgb_u8.shape
    raw = b"".join(b"\x00" + rgb_u8[y].tobytes() for y in range(h))  # filter byte 0 per scanline

    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def _stretch(a, lo_pct: float = 2.0, hi_pct: float = 98.0) -> np.ndarray:
    """Percentile contrast-stretch a 2-D array to ``uint8`` ``[0, 255]``."""
    a = np.asarray(a, dtype=np.float64)
    finite = a[np.isfinite(a)]
    lo, hi = (np.percentile(finite, [lo_pct, hi_pct]) if finite.size else (0.0, 1.0))
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((np.nan_to_num(a, nan=lo) - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def save_rgb(bands: dict, out_png, *, rgb=("B04", "B03", "B02"), upscale: int = 1) -> str:
    """Write an RGB quicklook PNG from a ``{band: 2-D array}`` product. Returns the path.

    ``rgb`` selects the three bands for the R/G/B channels (each independently percentile-stretched).
    ``upscale`` nearest-neighbour enlarges small demo frames for visibility.
    """
    img = np.stack([_stretch(bands[b]) for b in rgb], axis=-1)  # (H, W, 3)
    if upscale > 1:
        img = np.repeat(np.repeat(img, upscale, axis=0), upscale, axis=1)
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(_png_bytes(img))
    return str(out)

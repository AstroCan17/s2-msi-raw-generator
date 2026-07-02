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

"""Quicklook PNG writer tests — both product flavours it renders (uint16 DN L0, float reflectance L1B)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from s2_msi_raw_generator import quicklook

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _rgb_bands(dtype, rng, lo=0, hi=4095, shape=(8, 6)):
    return {b: rng.uniform(lo, hi, shape).astype(dtype) for b in ("B02", "B03", "B04")}


def test_save_rgb_uint16_dn(tmp_path):
    """L0 flavour: raw uint16 DN frames → valid PNG."""
    bands = _rgb_bands(np.uint16, np.random.default_rng(0))
    p = quicklook.save_rgb(bands, tmp_path / "l0.png")
    data = Path(p).read_bytes()
    assert data[:8] == PNG_MAGIC and len(data) > 100


def test_save_rgb_float_reflectance_and_upscale(tmp_path):
    """L1B flavour: float reflectance in [0, 1] (with NaN) → valid PNG; upscale grows the image."""
    bands = _rgb_bands(np.float64, np.random.default_rng(1), lo=0.0, hi=0.3)
    bands["B04"][0, 0] = np.nan                       # percentile stretch must survive NaNs
    small = Path(quicklook.save_rgb(bands, tmp_path / "s.png")).stat().st_size
    big = Path(quicklook.save_rgb(bands, tmp_path / "b.png", upscale=4)).stat().st_size
    assert Path(tmp_path / "s.png").read_bytes()[:8] == PNG_MAGIC
    assert big > small


def test_save_rgb_constant_band(tmp_path):
    """A flat (zero-range) band must not divide by zero."""
    bands = {b: np.zeros((4, 4)) for b in ("B02", "B03", "B04")}
    p = quicklook.save_rgb(bands, tmp_path / "flat.png")
    assert Path(p).read_bytes()[:8] == PNG_MAGIC

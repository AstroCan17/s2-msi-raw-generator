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

"""The jobs>1 process-pool fan-out must be bit-identical to the serial path."""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import l0product, sensor

BANDS = ["B03", "B04", "B8A"]


def _frames() -> dict[tuple[int, str], np.ndarray]:
    rng = np.random.default_rng(7)
    return {(1, bn): rng.integers(0, 4095, (64, 48), dtype=np.uint16) for bn in BANDS}


def test_parallel_write_bit_identical_to_serial(tmp_path):
    frames = _frames()
    serial = l0product.write_l0_product(
        str(tmp_path / "serial.zarr"), frames, with_isp=True, jobs=1
    )
    parallel = l0product.write_l0_product(
        str(tmp_path / "parallel.zarr"), frames, with_isp=True, jobs=3
    )
    gs = zarr.open_group(serial, mode="r")
    gp = zarr.open_group(parallel, mode="r")
    for bn in BANDS:
        k = f"measurements/d01/{sensor.zarr_band_key(bn)}"
        assert np.array_equal(np.asarray(gs[f"{k}/isp"]), np.asarray(gp[f"{k}/isp"]))
        assert dict(gs[k].attrs)["compression"] == dict(gp[k].attrs)["compression"]
        qk = f"quality/d01/{sensor.zarr_band_key(bn)}/mask"
        assert np.array_equal(np.asarray(gs[qk]), np.asarray(gp[qk]))
        # and the parallel product ground-decodes bit-exactly
        assert np.array_equal(l0product.read_l0_isp_dn(parallel, 1, bn), frames[(1, bn)])

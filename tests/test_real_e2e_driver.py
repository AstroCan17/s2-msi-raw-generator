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

"""Real-L1A E2E driver tests on a tiny synthetic PDI-style fixture (REQ-FUNC-093)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import _zarrio, naming

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_e2e_real_l1a.py"
_spec = importlib.util.spec_from_file_location("run_e2e_real_l1a", _SCRIPT)
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

BANDS = ["B02", "B03", "B04"]


@pytest.fixture()
def pdi_l1a(tmp_path):
    """A 64×64 PDI-style L1A zarr: measurements/DD01/Bxx/l1a_raw_image + STAC attrs."""
    rng = np.random.default_rng(5)
    path = tmp_path / "PDI_MSI_S2_L1A.zarr"
    g = _zarrio.open_group_w(path)
    g.attrs["stac_discovery"] = {"properties": {
        "datetime": "2022-08-03T11:36:42Z", "sat:relative_orbit": 123,
        "platform": "sentinel-2a"}}
    m = g.create_group("measurements").create_group("DD01")
    for b in BANDS:
        dn = rng.integers(0, 4096, (64, 64), dtype=np.uint16)
        dn[-2:] = 0                                   # a 2-line zero tail (line-loss case)
        _zarrio.put_array(m.create_group(b), "l1a_raw_image", dn, dtype="uint16")
    return str(path)


def _run(store, pdi_l1a, phases, extra=()):
    argv = [str(store), "--phases", phases, "--l1a", pdi_l1a, "--bands", ",".join(BANDS), *extra]
    assert drv.main(argv) == 0


def test_preflight_package_ground_decode(tmp_path, pdi_l1a):
    store = tmp_path / "store"
    _run(store, pdi_l1a, "preflight,package,ground-decode")
    pre = json.loads((store / "report/preflight.json").read_text())
    assert pre["bit_depth"] == 12 and pre["n_lines"] == 64
    assert pre["per_band"]["B02"]["trailing_zero_lines"] == 2
    # PSFD names parse and are traceable to the fixture's STAC metadata (no fallbacks)
    parsed = naming.parse_psfd_name(pre["product_names"]["l0"])
    assert parsed["relative_orbit"] == 123 and parsed["unit"] == "A"
    assert pre["naming_fallbacks"] == []
    gd = json.loads((store / "report/ground_decode.json").read_text())
    assert all(v["bit_exact"] for v in gd.values())
    # both product forms exist under PSFD names
    assert (store / "l0" / pre["product_names"]["l0"]).is_dir()
    assert (store / "l0" / pre["product_names"]["l0_oc"]).is_dir()
    # the OC detector frames equal the fixture DN (packaging is transparent)
    g = zarr.open_group(str(store / "l0" / pre["product_names"]["l0_oc"]), mode="r")
    src = zarr.open_group(pdi_l1a, mode="r")
    for b in BANDS:
        assert np.array_equal(np.asarray(g[f"measurements/detector/{b}"]),
                              np.asarray(src[f"measurements/DD01/{b}/l1a_raw_image"]))


def test_line_windowing(tmp_path, pdi_l1a):
    store = tmp_path / "store"
    _run(store, pdi_l1a, "preflight,package,ground-decode", extra=("--lines", "32"))
    pre = json.loads((store / "report/preflight.json").read_text())
    assert pre["n_lines"] == 32


def test_l0_decode_validate_sde(tmp_path, pdi_l1a):
    """Full chain incl. msi-processor — runs where eopf + msi_processor are installed."""
    pytest.importorskip("eopf")
    pytest.importorskip("msi_processor")
    store = tmp_path / "store"
    _run(store, pdi_l1a, "preflight,package,ground-decode,l0-decode,validate")
    va = json.loads((store / "report/validate.json").read_text())
    assert set(va) == set(BANDS)
    for b, v in va.items():
        assert v["bit_identical_kept"], b
        assert v["lines_lost"] == 2 == v["preflight_zero_tail"], b

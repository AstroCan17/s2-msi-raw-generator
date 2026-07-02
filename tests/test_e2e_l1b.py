"""E2E L0→L1B tests (REQ-FUNC-042).

Generator CI asserts the open-container **schema** msi-processor's ``l0_decode`` requires (zarr only);
the real ``radiometric``→``toa`` run is skipped unless ``eopf`` + ``msi_processor`` are installed (SDE).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import sensor

# Import the pipeline driver script (scripts/ is not a package).
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _SCRIPT)
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)


def test_opencontainer_l0_matches_processor_schema(tmp_path):
    l0_path, _caldb, _ = e2e.build_inputs(tmp_path, n_det=32, n_lines=24, bands=["B03", "B04"])
    g = zarr.open_group(l0_path, mode="r")
    for bn in ("B03", "B04"):
        a = g[f"measurements/detector/{bn}"]              # l0_decode reads measurements/detector/<band>
        assert a.dtype == np.uint16 and a.shape == (24, 32)
        assert 0 <= int(np.asarray(a).min()) and int(np.asarray(a).max()) <= sensor.DN_MAX
        assert g[f"quality/l0_flags/{bn}"].dtype == np.uint16   # QAFlag seed the processor OR-accumulates
    assert g["conditions/time/line_time"].shape == (24,)
    assert g["conditions/orbit/position"].shape == (24, 3)
    assert g["conditions/orbit/velocity"].shape == (24, 3)
    assert g["conditions/attitude/quaternion"].shape == (24, 4)
    # root metadata carried on the open container too
    assert dict(g.attrs)["stac_discovery"]["properties"]["eopf:type"] == "S2MSIL0_"


def test_nuc_gain_width_matches_detector_axis(tmp_path):
    """The hard handoff invariant: nuc.gain[band] length == measurements/detector/<band> width."""
    n_det = 32
    l0_path, caldb, _ = e2e.build_inputs(tmp_path, n_det=n_det, n_lines=16, bands=["B03"])
    g = zarr.open_group(l0_path, mode="r")
    nuc = zarr.open_group(f"{caldb}/nuc.zarr", mode="r")
    assert np.asarray(nuc["gain/B03"]).shape[0] == g["measurements/detector/B03"].shape[1] == n_det
    # spectral ESUN present + correct for the toa reflectance step
    spec = zarr.open_group(f"{caldb}/spectral.zarr", mode="r")
    assert float(np.asarray(spec["esun/B03"])) == pytest.approx(sensor.ESUN["S2A"]["B03"], rel=1e-6)


def test_l0_to_l1b_real_chain_sde(tmp_path):
    """Real L0→L1B run + native persist — skipped unless eopf + msi_processor are installed (the SDE)."""
    pytest.importorskip("eopf")
    pytest.importorskip("msi_processor")
    l0_path, caldb, _ = e2e.build_inputs(tmp_path, n_det=64, n_lines=48)
    l1b = e2e.run_processor(l0_path, caldb)
    assert l1b is not None
    l1b_path = e2e.write_l1b(l1b, tmp_path / "l1b")           # EOZarrStore → <dir>/<PSFD L1B>.zarr
    g = zarr.open_group(l1b_path, mode="r")
    assert "measurements" in g                                # persisted product tree round-trips

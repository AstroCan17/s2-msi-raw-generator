"""Open-container L0 handoff schema (REQ-FUNC-042) + cal-DB width invariant.

The OC form is what the nominal chain's ``ground-decode`` phase emits for the consumer's
``l0_decode``; the schema contract is asserted here from directly-constructed frames.
"""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import caldb, l0product, sensor


def _frames(bands, n_lines=24, n_det=32, seed=0):
    rng = np.random.default_rng(seed)
    return {
        b: rng.integers(0, sensor.DN_MAX + 1, size=(n_lines, n_det)).astype(np.uint16)
        for b in bands
    }


def test_opencontainer_l0_matches_processor_schema(tmp_path):
    band_frames = _frames(("B03", "B04"))
    l0_path = l0product.write_l0_opencontainer(str(tmp_path / "oc.zarr"), band_frames)
    g = zarr.open_group(l0_path, mode="r")
    for bn in ("B03", "B04"):
        a = g[
            f"measurements/detector/{bn}"
        ]  # l0_decode reads measurements/detector/<band>
        assert a.dtype == np.uint16 and a.shape == (24, 32)
        assert (
            0 <= int(np.asarray(a).min()) and int(np.asarray(a).max()) <= sensor.DN_MAX
        )
        assert (
            g[f"quality/l0_flags/{bn}"].dtype == np.uint16
        )  # QAFlag seed the processor OR-accumulates
    assert g["conditions/time/line_time"].shape == (24,)
    assert g["conditions/orbit/position"].shape == (24, 3)
    assert g["conditions/orbit/velocity"].shape == (24, 3)
    assert g["conditions/attitude/quaternion"].shape == (24, 4)
    # root metadata carried on the open container too (nominal defaults)
    props = dict(g.attrs)["stac_discovery"]["properties"]
    assert props["eopf:type"] == "S2MSIL0_"
    assert props["msi:datatake_type"] == "INS-NOBS"


def test_nuc_gain_width_matches_detector_axis(tmp_path):
    """The hard handoff invariant: nuc.gain[band] length == measurements/detector/<band> width."""
    n_det = 32
    l0_path = l0product.write_l0_opencontainer(
        str(tmp_path / "oc.zarr"), _frames(("B03",), n_det=n_det)
    )
    caldb.build(tmp_path / "caldb", n_det=n_det, seed=1)
    g = zarr.open_group(l0_path, mode="r")
    nuc = zarr.open_group(str(tmp_path / "caldb" / "nuc.zarr"), mode="r")
    assert (
        np.asarray(nuc["gain/B03"]).shape[0]
        == g["measurements/detector/B03"].shape[1]
        == n_det
    )
    spec = zarr.open_group(str(tmp_path / "caldb" / "spectral.zarr"), mode="r")
    assert float(np.asarray(spec["esun/B03"])) == pytest.approx(
        sensor.ESUN["S2A"]["B03"], rel=1e-6
    )

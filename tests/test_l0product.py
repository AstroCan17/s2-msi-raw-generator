"""Increment-2 tests: L0 RAW EOProduct assembly (REQ-FUNC-030–036)."""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_e2es import l0product, sensor


def _synthetic_l1b(detectors, bands, shape=(16, 8), seed=0):
    rng = np.random.default_rng(seed)
    frames = {}
    for d in detectors:
        for bn in bands:
            lref = sensor.band(bn).lref
            frames[(d, bn)] = np.clip(rng.normal(lref, lref * 0.3, size=shape), 0, None)
    return frames


def test_reverse_to_l0_frames_are_uint16_in_range():
    frames = _synthetic_l1b([4, 5], ["B03", "B04"])
    l0 = l0product.reverse_to_l0_frames(frames, seed=1)
    assert set(l0) == set(frames)
    for dn in l0.values():
        assert dn.dtype == np.uint16
        assert dn.min() >= 0 and dn.max() <= sensor.DN_MAX


def test_write_and_reopen_l0_structure(tmp_path):
    detectors, bands = [4, 7], ["B02", "B03", "B8A"]
    frames = l0product.reverse_to_l0_frames(_synthetic_l1b(detectors, bands), seed=2)
    out = str(tmp_path / "L0.zarr")
    l0product.write_l0_product(out, frames, platform="Sentinel-2A")

    g = zarr.open_group(out, mode="r")
    # measurements/d{DD}/b{BB}/band{BB} uint16
    arr = g["measurements/d04/b03/band03"]
    assert arr.dtype == np.uint16 and arr.shape == (16, 8)
    # quality mask uint8
    assert g["quality/d07/b8a/mask"].dtype == np.uint8
    # band key for B8A is b8a / band8A
    assert g["measurements/d07/b8a/band8A"].shape == (16, 8)

    # root STAC + sensor config (REQ-FUNC-033/034)
    attrs = dict(g.attrs)
    assert attrs["stac_discovery"]["properties"]["eopf:type"] == "S2MSIL0_"
    ac = attrs["other_metadata"]["sensor_configuration"]["acquisition_configuration"]
    assert ac["tdi_configuration_list"] == {"03": "APPLIED", "04": "APPLIED",
                                            "11": "APPLIED", "12": "APPLIED"}
    assert ac["spectral_band_info"]["03"]["physical_gains"] == pytest.approx(4.17678)
    assert attrs["other_metadata"]["sensor_configuration"]["time_stamp"]["line_period"] \
        == pytest.approx(1.5658736)
    assert "SentiWiki" in attrs["processing_history"]["adf_provenance"]["psf"]


def test_full_156_array_contract(tmp_path):
    # 12 detectors × 13 bands = 156 measurement arrays + 156 masks (REQ-FUNC-031/032).
    detectors = list(range(1, 13))
    bands = list(sensor.BANDS)
    frames = {(d, bn): np.zeros((2, 2), dtype=np.float64) for d in detectors for bn in bands}
    l0 = l0product.reverse_to_l0_frames(frames, seed=3)
    out = str(tmp_path / "L0full.zarr")
    l0product.write_l0_product(out, l0)

    g = zarr.open_group(out, mode="r")
    n_meas = sum(1 for k in g["measurements"].array_keys_recursive()) \
        if hasattr(g["measurements"], "array_keys_recursive") else None
    # count band arrays explicitly
    count = 0
    for d in detectors:
        for bn in bands:
            assert g[f"measurements/d{d:02d}/{sensor.zarr_band_key(bn)}/band{sensor.band_number(bn)}"] is not None
            count += 1
    assert count == 156

"""Increment-2 tests: Synthetic L0 RAW EOProduct assembly (REQ-FUNC-030–036)."""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import l0product, sensor


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
    out = str(tmp_path / "Synthetic L0.zarr")
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


def test_stac_geometry_orbit_and_datation(tmp_path):
    """REQ-FUNC-035/038: GPS/OBT datation span + STAC geometry/bbox/orbit + band time stamps."""
    from s2_msi_raw_generator import datation as dm

    detectors, bands = [4], ["B02", "B03"]
    frames = l0product.reverse_to_l0_frames(_synthetic_l1b(detectors, bands, shape=(64, 8)), seed=5)
    out = str(tmp_path / "L0meta.zarr")
    d = dm.Datation(epoch_utc="2024-04-03T10:24:15Z")
    l0product.write_l0_product(out, frames, datation=d)

    props = dict(zarr.open_group(out, mode="r").attrs)["stac_discovery"]
    # geometry / bbox
    disc = props
    assert len(disc["bbox"]) == 4
    ring = disc["geometry"]["coordinates"][0]
    assert disc["geometry"]["type"] == "Polygon" and ring[0] == ring[-1] and len(ring) >= 4
    # orbit + product identity
    p = disc["properties"]
    assert p["sat:relative_orbit"] == 45 and p["sat:absolute_orbit"] == 0
    assert p["sat:orbit_state"] == "descending"
    assert p["constellation"] == "sentinel-2" and p["product:type"] == "S2MSIL0_"
    assert p["eopf:datastrip_id"].startswith("S2A_OPER_MSI_L0__DS_2024")
    # acquisition datetime span (Zulu, ordered, not the old placeholder)
    assert p["start_datetime"].endswith("Z") and p["start_datetime"] <= p["end_datetime"]
    assert p["start_datetime"].startswith("2024-04-03T10:24:15")

    tstamp = dict(zarr.open_group(out, mode="r").attrs)["other_metadata"]["sensor_configuration"]["time_stamp"]
    assert tstamp["acquisition_epoch_gps_s"] > 1.30e9
    assert set(tstamp["band_time_stamp"]) == {sensor.band_number(b) for b in sensor.BANDS}


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


def test_reverse_frames_seed_is_process_independent():
    """REQ-QUAL-004: crc32-based reseeding (not hash()) — identical DN across processes."""
    frames = {(1, "B03"): np.full((8, 6), 120.0)}
    a = l0product.reverse_to_l0_frames(frames, seed=3)[(1, "B03")]
    b = l0product.reverse_to_l0_frames(frames, seed=3)[(1, "B03")]
    assert np.array_equal(a, b)
    # pin the crc32-derived stream: zlib.crc32(b"B03") % 97 == 33 → rng seed 3 + 100 + 33
    import zlib
    assert zlib.crc32(b"B03") % 97 == 30
    rng = np.random.default_rng(3 + 100 + 30)
    from s2_msi_raw_generator.adf import synthesize
    from s2_msi_raw_generator.reverse import reverse_mvp
    expect = reverse_mvp(np.full((8, 6), 120.0), synthesize(sensor.band("B03"), n_det=6, seed=3), rng)
    assert np.array_equal(a, expect)

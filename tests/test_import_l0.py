from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import _fsutil, _zarrio, import_l0, l0product, naming, sensor
from tests.conftest import patch_pipeline_env

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _SCRIPT)
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

BANDS = ["B02", "B03", "B04"]


@pytest.fixture()
def public_l0_zip(tmp_path):
    src = tmp_path / "public_l0.zarr"
    g = _zarrio.open_group_w(src)
    g.attrs["stac_discovery"] = {"stac_discovery": {"properties": {
        "datetime": "null",
        "start_datetime": "2023-02-16T15:06:21Z",
        "end_datetime": "2023-02-16T15:06:22Z",
        "sat:relative_orbit": "82",
        "sat:absolute_orbit": "/Earth_Explorer_File/.../ORBIT_NUMBER",
        "eopf:data_take_id": "GS2A_20230216T150621_039976_N04.00",
        "platform": "Sentinel-2A",
    }}}
    g.attrs["other_metadata"] = {"sensor_configuration": {"aquisition_configuration": {
        "operation_mode": "NOBS",
        "active_detectors_list": "01,02",
    }}}
    m = g.create_group("measurements")
    for det in (1, 2):
        dg = m.create_group(f"d{det:02d}")
        for idx, band in enumerate(BANDS):
            data = (np.arange(64, dtype=np.uint16).reshape(8, 8) + det * 100 + idx * 10) % 4096
            _zarrio.put_array(dg.create_group(sensor.zarr_band_key(band)), "img", data, dtype="uint16")
    dest = tmp_path / "S02MSIL0__20230216T182840_0001_A123_T000.zarr.zip"
    _fsutil.zip_dir(src, dest)
    return dest


def test_convert_public_l0_to_pdi_l1a(tmp_path, public_l0_zip):
    report = import_l0.convert(public_l0_zip, tmp_path / "inputs", detector=2, bands=BANDS)
    out = Path(report["output"])
    assert out.is_dir()
    parsed = naming.parse_psfd_name(out.name)
    assert parsed["relative_orbit"] == 82
    assert report["identity"]["absolute_orbit"] == 39976
    g = zarr.open_group(str(out), mode="r")
    prov = dict(g.attrs)["other_metadata"]["import_provenance"]
    assert prov["source_detector"] == 2
    assert prov["detector_mapping"] == "d02->DD01"
    public = zarr.open_group(zarr.storage.ZipStore(public_l0_zip, mode="r"), mode="r")
    for band in BANDS:
        assert np.array_equal(
            np.asarray(g[f"measurements/DD01/{band}/l1a_raw_image"]),
            np.asarray(public[f"measurements/d02/{sensor.zarr_band_key(band)}/img"]),
        )


def test_driver_import_l0_pipeline_same_scene(tmp_path, public_l0_zip, monkeypatch):
    store = tmp_path / "store"
    patch_pipeline_env(monkeypatch, store)
    monkeypatch.setenv("S2_L0_INPUT", str(public_l0_zip))
    monkeypatch.setenv("S2_IMPORT_DETECTOR", "1")
    monkeypatch.setenv("S2_BANDS", ",".join(BANDS))
    monkeypatch.setenv("S2_PHASES", "import-l0,preflight,package,ground-decode")
    monkeypatch.setenv("S2_JOBS", "1")
    assert drv.main([], load_env=False) == 0

    pre = json.loads((store / "report/preflight.json").read_text())
    assert pre["naming_fallbacks"] == []
    assert pre["relative_orbit"] == 82
    assert pre["orbit"]["absolute_orbit"] == 39976
    parsed = naming.parse_psfd_name(pre["product_names"]["l0"])
    assert parsed["relative_orbit"] == 82

    public = zarr.open_group(zarr.storage.ZipStore(public_l0_zip, mode="r"), mode="r")
    canon = str(store / "l0" / pre["product_names"]["l0"])
    for band in BANDS:
        assert np.array_equal(
            l0product.read_l0_isp_dn(canon, 1, band),
            np.asarray(public[f"measurements/d01/{sensor.zarr_band_key(band)}/img"], dtype=np.uint16),
        )


def test_import_detector_env_selects_source_detector(tmp_path, public_l0_zip, monkeypatch):
    store = tmp_path / "store"
    patch_pipeline_env(monkeypatch, store)
    monkeypatch.setenv("S2_L0_INPUT", str(public_l0_zip))
    monkeypatch.setenv("S2_IMPORT_DETECTOR", "2")
    monkeypatch.setenv("S2_BANDS", "B02")
    monkeypatch.setenv("S2_PHASES", "import-l0")
    assert drv.main([], load_env=False) == 0
    report = json.loads((store / "report/import_l0.json").read_text())
    assert report["detector"] == 2
    g = zarr.open_group(report["output"], mode="r")
    assert dict(g.attrs)["other_metadata"]["import_provenance"]["source_detector"] == 2


def test_store_paths_use_output_dir_subdirs(tmp_path):
    store = drv._store_paths(tmp_path / "store")
    assert store["l0"] == tmp_path / "store" / "l0"
    assert store["report"] == tmp_path / "store" / "report"

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import _fsutil, _zarrio, inventory
from tests.conftest import patch_pipeline_env

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _SCRIPT)
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)


def _mini_zarr(path: Path, attrs: dict, layout: str = "l0") -> None:
    g = _zarrio.open_group_w(path)
    g.attrs.update(attrs)
    if layout == "l1a":
        _zarrio.put_array(
            g.create_group("measurements").create_group("DD01").create_group("B02"),
            "l1a_raw_image",
            np.ones((2, 3), dtype=np.uint16),
            dtype="uint16",
        )
    else:
        _zarrio.put_array(
            g.create_group("measurements").create_group("d01").create_group("b02"),
            "img",
            np.ones((2, 3), dtype=np.uint16),
            dtype="uint16",
        )


@pytest.fixture()
def mini_store(tmp_path):
    store = tmp_path / "store"
    (store / "inputs/public-data/level-0").mkdir(parents=True)
    (store / "inputs").mkdir(exist_ok=True)
    (store / "l0").mkdir()
    (store / "report").mkdir()

    _mini_zarr(store / "inputs/PDI_MSI_S2_L1A.zarr", {}, layout="l1a")
    _mini_zarr(
        store / "l0/S02MSIL0__20240403T102415_0001_A045_T000.zarr",
        {"stac_discovery": {"properties": {
            "datetime": "2024-04-03T10:24:15Z",
            "sat:relative_orbit": 122,
            "sat:absolute_orbit": 34803,
            "platform": "Sentinel-2A",
        }}},
    )
    public_dir = tmp_path / "public.zarr"
    _mini_zarr(
        public_dir,
        {"stac_discovery": {"stac_discovery": {"properties": {
            "datetime": "null",
            "start_datetime": "2023-02-16T15:06:21Z",
            "sat:relative_orbit": "82",
            "sat:absolute_orbit": "/Earth_Explorer_File/.../ORBIT_NUMBER",
            "eopf:data_take_id": "GS2A_20230216T150621_039976_N04.00",
            "platform": "Sentinel-2A",
        }}}},
    )
    _fsutil.zip_dir(public_dir, store / "inputs/public-data/level-0/S02MSIL0__20230216T182840_0001_A123_T000.zarr.zip")
    (store / "inputs/public-data/level-0/S02MSIL0P_foo.zarr.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (store / "report/preflight.json").write_text(json.dumps({"naming_fallbacks": ["datetime"]}))
    (store / "report/l0_decode.json").write_text(json.dumps({"groups": 4}))
    return store


def test_scan_store_classifies_and_flags(mini_store):
    records = inventory.scan_store(mini_store)
    kinds = {r["kind"] for r in records}
    assert "external-l1a" in kinds
    assert "our-l0-canonical" in kinds
    assert "external-l0-public" in kinds
    public = next(r for r in records if r["kind"] == "external-l0-public")
    assert "double_stac_discovery" in public["flags"]
    assert "absolute_orbit_from_datatake_id" in public["flags"]
    assert public["identity"]["absolute_orbit"] == 39976


def test_findings_and_outputs(mini_store):
    payload = inventory.write_outputs(mini_store)
    ids = {f["id"] for f in payload["findings"]}
    assert "orbit-name-stac-mismatch" in ids
    assert "public-l0-different-datatake" in ids
    assert "l0-decode-empty-group-count" in ids
    assert (mini_store / "INVENTORY.md").exists()
    assert (mini_store / "report/inventory.json").exists()


def test_inventory_phase(monkeypatch, mini_store):
    patch_pipeline_env(monkeypatch, mini_store)
    monkeypatch.setenv("S2_PHASES", "inventory")
    assert drv.main([], load_env=False) == 0
    assert (mini_store / "report/inventory.json").exists()

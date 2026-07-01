"""Tests for the EOQC-style per-product quality report (REQ-FUNC-041)."""

from __future__ import annotations

import json

import pytest

from s2_msi_raw_generator import l0product, quality_report


def _root_metadata():
    return l0product.build_root_metadata(active_detectors=[4], n_lines=64)


def test_qc_report_ok_on_good_product():
    r = quality_report.build_qc_report(_root_metadata(), product_name="S02MSIL0__test",
                                       inspection_time="2026-07-01T00:00:00Z")
    assert r["overall_flag"] == "OK"
    assert all(c["result"] == "pass" for c in r["checks"])
    # minimum EOQC content present
    for key in ("product_name", "product_type", "processing_facility", "sensing_start",
                "sensing_stop", "absolute_orbit", "relative_orbit", "software", "checks"):
        assert key in r


def test_qc_report_ko_when_mandatory_stac_key_removed():
    meta = _root_metadata()
    del meta["stac_discovery"]["properties"]["platform"]
    r = quality_report.build_qc_report(meta, product_name="broken",
                                       inspection_time="2026-07-01T00:00:00Z")
    assert r["overall_flag"] == "KO"
    assert any(c["name"] == "STAC_metadata_content" and c["result"] == "fail" for c in r["checks"])


def test_qc_report_writes_valid_json(tmp_path):
    r = quality_report.build_qc_report(_root_metadata(), product_name="p",
                                       inspection_time="2026-07-01T00:00:00Z")
    p = quality_report.write_qc_report(tmp_path / "QC_report_p.json", r)
    assert json.loads(p.read_text())["overall_flag"] == "OK"


def test_l0_product_embeds_qc_report(tmp_path):
    zarr = pytest.importorskip("zarr")
    import numpy as np
    frames = {(4, "B03"): np.full((16, 8), 100.0)}
    l0 = l0product.reverse_to_l0_frames(frames, seed=1)
    out = str(tmp_path / "L0qc.zarr")
    l0product.write_l0_product(out, l0)
    qc = dict(zarr.open_group(out, mode="r")["quality"].attrs)["qc"]
    assert qc["overall_flag"] == "OK" and qc["product_name"] == "L0qc.zarr"

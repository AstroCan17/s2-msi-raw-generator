"""Calibration mode (REQ-FUNC-048): campaign acquisitions as REAL downlink L0 products.

Runs the driver's calibration phases into a tmp store and asserts the products carry the
PSFD §3 calibration type codes (S02MSIDCA dark / S02MSISCA sun-diffuser), the operation-
mode metadata, bit-exact ISP round-trips, and cal-DB coefficients consistent with the
consumer's two-point derivation over the same (decoded) frames.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import l0product, naming

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _SCRIPT)
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

BANDS = ["B03", "B04"]


@pytest.fixture(scope="module")
def cal_store(tmp_path_factory):
    store = tmp_path_factory.mktemp("calstore")
    drv.main(
        [
            str(store),
            "--mode",
            "calibration",
            "--n-det",
            "32",
            "--cal-lines",
            "16",
            "--bands",
            ",".join(BANDS),
            "--seed",
            "3",
        ]
    )
    return store


def _product(store, prefix):
    hits = sorted((store / "l0").glob(f"{prefix}*.zarr"))
    assert len(hits) == 1
    return hits[0]


def test_products_carry_psfd_cal_type_codes(cal_store):
    for prefix, kind in (("S02MSIDCA", "dark"), ("S02MSISCA", "diffuser")):
        p = _product(cal_store, prefix)
        fields = naming.parse_psfd_name(p.name)
        assert fields["product_type"] == prefix
        assert prefix in naming.TYPE_CODES


def test_operation_mode_metadata(cal_store):
    expect = {
        "S02MSIDCA": ("S2MSIDCA", "DASC", "INS-DASC"),
        "S02MSISCA": ("S2MSISCA", "ABSR", "INS-ABSR"),
    }
    for prefix, (eopf_type, op, dt) in expect.items():
        g = zarr.open_group(str(_product(cal_store, prefix)), mode="r")
        props = dict(g.attrs)["stac_discovery"]["properties"]
        acq = dict(g.attrs)["other_metadata"]["sensor_configuration"][
            "acquisition_configuration"
        ]
        assert props["eopf:type"] == eopf_type and props["product:type"] == eopf_type
        assert props["msi:datatake_type"] == dt
        assert acq["operation_mode"] == op


def test_nominal_defaults_tag_nobs(tmp_path):
    """The nominal writer defaults stamp NOBS / INS-NOBS (unchanged products + 2 new fields)."""
    frames = {(1, "B03"): np.zeros((8, 8), dtype=np.uint16)}
    out = l0product.write_l0_product(str(tmp_path / "nom.zarr"), frames)
    g = zarr.open_group(out, mode="r")
    props = dict(g.attrs)["stac_discovery"]["properties"]
    acq = dict(g.attrs)["other_metadata"]["sensor_configuration"][
        "acquisition_configuration"
    ]
    assert props["eopf:type"] == "S2MSIL0_" and props["msi:datatake_type"] == "INS-NOBS"
    assert acq["operation_mode"] == "NOBS"


def test_isp_round_trip_is_bit_exact(cal_store):
    acquire = json.loads((cal_store / "report" / "cal_acquire.json").read_text())
    assert acquire["n_det"] == 32
    for prefix in ("S02MSIDCA", "S02MSISCA"):
        p = _product(cal_store, prefix)
        for bn in BANDS:
            dn = l0product.read_l0_isp_dn(str(p), 1, bn)
            assert dn.dtype == np.uint16 and dn.shape == (16, 32)
            key = "b" + bn[1:].lower()
            stored = zarr.open_group(str(p), mode="r")[
                f"measurements/d01/{key}/band{bn[1:].lower()}"
            ]
            # decoded stream must equal the stored decoded frame bit-exactly
            assert np.array_equal(dn, np.asarray(stored))


def test_caldb_matches_consumer_two_point_formula(cal_store):
    """Consumer derivation ((muF-muD)/(Fbar-Dbar)) over the DECODED frames == shipped nuc."""
    nuc = zarr.open_group(str(cal_store / "caldb" / "nuc.zarr"), mode="r")
    dark_p = _product(cal_store, "S02MSIDCA")
    flat_p = _product(cal_store, "S02MSISCA")
    for bn in BANDS:
        dark = l0product.read_l0_isp_dn(str(dark_p), 1, bn).astype(np.float64)
        flat = l0product.read_l0_isp_dn(str(flat_p), 1, bn).astype(np.float64)
        mu_f, mu_d = flat.mean(), dark.mean()
        gain = (mu_f - mu_d) / (flat.mean(axis=0) - dark.mean(axis=0))
        shipped = np.asarray(nuc[f"gain/{bn}"], dtype=np.float64)
        assert np.allclose(gain, shipped, rtol=1e-5)

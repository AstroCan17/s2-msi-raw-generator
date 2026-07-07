"""Unit tests for the real-L1B→L0 downlink-domain reverse (``reverse_l1b_to_l0``) and its phase helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from s2_msi_raw_generator import forward_radiometric_atbd as fwd
from s2_msi_raw_generator.gipp import DetectorEq

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
_spec = importlib.util.spec_from_file_location("run_pipeline", _SCRIPT)
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

W = 2552


def _cubic_identity(dark_level: float = 440.0) -> DetectorEq:
    """A near-identity VNIR cubic eq (A=B=0, C=1) with a uniform raw-detector-domain dark."""
    z = np.zeros(W)
    return DetectorEq("CUBIC", np.full(W, dark_level), {"A": z, "B": z.copy(), "C": np.ones(W)})


def _bilinear_identity(dark_level: float = 500.0) -> DetectorEq:
    return DetectorEq(
        "BILINEAR",
        np.full(W, dark_level),
        {"A1": np.ones(W), "A2": np.ones(W), "Zs": np.full(W, 100.0)},
    )


def test_reverse_uses_l0_domain_dark_not_coeff_d():
    """The dark added is ``l0_dark_level`` (≈51), NOT the raw-detector COEFF_D (≈440)."""
    l1b = np.full((64, W), 390.0)
    eq = _cubic_identity(dark_level=440.0)
    raw = fwd.reverse_l1b_to_l0(l1b, eq, radio_offset_l1b=-100.0, l0_dark_level=51.0)
    # identity response + uniform dark → raw = (L1B − 100) + 51 = L1B − 49, exactly (rounding aside)
    assert np.allclose(raw, 390.0 - 49.0, atol=1.0)
    added = float(raw.mean() - (l1b.mean() - 100.0))
    assert abs(added - 51.0) < 1.0  # L0-domain dark, not 440
    assert raw.dtype == np.uint16 and raw.shape == l1b.shape


def test_reverse_bilinear_swir():
    l1b = np.full((32, W), 800.0)
    raw = fwd.reverse_l1b_to_l0(l1b, _bilinear_identity(500.0), radio_offset_l1b=-100.0, l0_dark_level=51.0)
    assert np.allclose(raw, 800.0 - 49.0, atol=1.0)


def test_reverse_unbin_60m_triples_width():
    l1b = np.full((16, 425), 300.0)
    eq = DetectorEq("CUBIC", np.full(425, 440.0), {"A": np.zeros(425), "B": np.zeros(425), "C": np.ones(425)})
    raw = fwd.reverse_l1b_to_l0(l1b, eq, radio_offset_l1b=-100.0, l0_dark_level=51.0, unbin_factor=3)
    assert raw.shape == (16, 425 * 3)  # S5 un-bin ×3 (replication)
    assert np.allclose(raw, 300.0 - 49.0, atol=1.0)


def test_reverse_impresses_dsnu_column_shape():
    """A non-uniform COEFF_D injects a per-column dark (DSNU) shape scaled to the L0 level."""
    dark = np.linspace(430.0, 450.0, W)  # +/- gradient across track
    eq = DetectorEq("CUBIC", dark, {"A": np.zeros(W), "B": np.zeros(W), "C": np.ones(W)})
    raw = fwd.reverse_l1b_to_l0(np.full((8, W), 390.0), eq, radio_offset_l1b=-100.0, l0_dark_level=51.0)
    col = raw.astype(float).mean(axis=0)
    assert col.std() > 0.1  # dark gradient shows as a column pattern
    assert abs(col.mean() - (390.0 - 100.0 + 51.0)) < 1.0


def test_reinsert_blind_places_active_at_keep():
    active = np.full((4, 2552), 7, dtype=np.uint16)
    blind = list(range(20)) + list(range(2572, 2592))  # 40 blind columns → physical 2592
    out = drv._reinsert_blind(active, blind, fill=51)
    assert out.shape == (4, 2592)
    assert (out[:, 20:2572] == 7).all()  # active region preserved
    assert (out[:, :20] == 51).all() and (out[:, 2572:] == 51).all()


def test_reinsert_blind_falls_back_when_inconsistent():
    active = np.full((4, 2552), 7, dtype=np.uint16)
    assert drv._reinsert_blind(active, None, 51) is active  # no BLINDP
    assert drv._reinsert_blind(active, [999999], 51).shape == (4, 2552)  # bad index → unchanged


def test_platform_from_props():
    assert drv._l1b_platform({"platform": "sentinel-2b"}) == "Sentinel-2B"
    assert drv._l1b_platform({"platform": "Sentinel-2A"}) == "Sentinel-2A"
    assert drv._l1b_platform({}) == "Sentinel-2A"


# --- full reverse chain: S8 SWIR / S12 onboard-eq / S10 defective / S9 crosstalk ----------

def test_restage_swir_shift_exactly_invertible():
    """B11/B12 whole-line ±1 roll (method='shift') is exactly undone by restaging with −shifts."""
    rng = np.random.default_rng(0)
    img = rng.normal(500, 30, size=(200, 12))
    shifts = np.array([0, 1, -1, 1, 0, -1, 1, -1, 0, 1, -1, 0])
    staggered = fwd.restage_swir_lines(img, shifts, method="shift")
    assert not np.allclose(staggered, img)                       # it actually moved columns
    back = fwd.restage_swir_lines(staggered, -shifts, method="shift")
    assert np.allclose(back, img)                                # roll is exactly invertible


def test_restage_swir_interp_uses_kernel():
    """B10 sub-pixel method='interp' convolves flagged columns with the 3-tap kernel (± direction)."""
    img = np.zeros((64, 4))
    img[32, :] = 1.0                                             # an impulse per column
    kernel = np.array([0.0, 0.667, 0.333])
    shifts = np.array([0, 1, 0, -1])
    out = fwd.restage_swir_lines(img, shifts, kernel=kernel, method="interp")
    assert np.allclose(out[:, 0], img[:, 0])                     # shift 0 untouched
    assert out[32, 1] == pytest.approx(0.667) and out[33, 1] == pytest.approx(0.333)  # +: down 1/3
    assert out[31, 3] == pytest.approx(0.333) and out[32, 3] == pytest.approx(0.667)  # −: reversed


def test_restage_swir_aligns_wider_shift_map():
    """A physical-detector shift map (wider than the active frame) is centre-cropped to width."""
    img = np.zeros((10, 4))
    shifts = np.array([9, 9, 1, -1, 9, 9])                       # 6-wide map → centre 4 = [9,1,-1,9]
    out = fwd.restage_swir_lines(img + 1.0, shifts, method="shift")
    assert out.shape == img.shape                                # no crash, aligned to width 4


def test_reapply_onboard_eq_identity_and_knee():
    a = np.ones(5)
    z = np.array([[10.0, 50.0, 100.0, 200.0, 400.0]])
    ident = fwd.reapply_onboard_eq(z, {"a1": a, "a2": a, "zs": np.full(5, 100.0)})
    assert np.allclose(ident, z)                                 # a1=a2=1 → identity
    reob2 = {"a1": np.full(5, 1.005), "a2": np.full(5, 0.995), "zs": np.full(5, 100.0)}
    y = fwd.reapply_onboard_eq(z, reob2)
    assert np.allclose(y[0, :2], z[0, :2] * 1.005)              # below knee → a1 gain
    assert y[0, -1] < z[0, -1]                                   # above knee → a2 (<1) gain


def test_reverse_full_chain_swir_and_defective():
    """reverse_l1b_to_l0 applies S8 (roll) and S10 (defective NoData) end-to-end."""
    l1b = np.full((100, 12), 390.0)
    l1b[:, 6] = np.linspace(300, 480, 100)                       # texture so the roll is visible
    eq = DetectorEq("BILINEAR", np.full(12, 500.0),
                    {"A1": np.ones(12), "A2": np.ones(12), "Zs": np.full(12, 100.0)})
    shifts = np.array([0, 1, -1, 0, 1, -1, 1, 0, -1, 1, 0, -1])
    raw = fwd.reverse_l1b_to_l0(
        l1b, eq, radio_offset_l1b=-100.0, l0_dark_level=51.0,
        swir_shift=(shifts, np.array([]), "shift"), defective_cols=np.array([3, 8]), nodata=0.0)
    assert raw.shape == l1b.shape and raw.dtype == np.uint16
    assert (raw[:, 3] == 0).all() and (raw[:, 8] == 0).all()    # S10 defective → NoData
    plain = fwd.reverse_l1b_to_l0(l1b, eq, radio_offset_l1b=-100.0, l0_dark_level=51.0)
    assert not np.array_equal(raw[:, 6], plain[:, 6])           # S8 shifted the textured column


def test_reverse_crosstalk_adds_back_within_resolution_group():
    from s2_msi_raw_generator import sensor

    idx = {b: i for i, b in enumerate(sensor.BANDS)}
    m = np.zeros((13, 13))
    m[idx["B02"], idx["B03"]] = 0.01                            # B03 leaks 1% into B02 (both 10 m)
    sig = {"B02": np.full((4, 8), 100.0), "B03": np.full((4, 8), 200.0),
           "B01": np.full((4, 3), 50.0)}                        # B01 different shape → untouched
    out = drv._reverse_crosstalk(sig, m)
    assert np.allclose(out["B02"], 100.0 + 0.01 * 200.0)       # crosstalk added back
    assert np.allclose(out["B03"], 200.0) and np.allclose(out["B01"], 50.0)
    assert drv._reverse_crosstalk(sig, np.zeros((13, 13)))["B02"].tolist() == sig["B02"].tolist()

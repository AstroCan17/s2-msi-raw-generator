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

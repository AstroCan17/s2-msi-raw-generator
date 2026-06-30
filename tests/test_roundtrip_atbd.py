"""Round-trip V&V for the ATBD radiometric model + real GIPP coefficients.

Two checks (Increment B): (1) the forward correction and the reverse impress are **exact inverses**
on real-DN-scale data; (2) impressing the real per-pixel relative response onto a flat scene and then
correcting it **flattens** the fixed-pattern noise — the equalization genuinely inverts the modelled
PRNU. An optional check runs on the real L1A + GIPP via ``S2_E2ES_L1A`` / ``S2_E2ES_GIPP_DIR``.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from s2_e2es import forward_radiometric_atbd as fwd
from s2_e2es.gipp import DetectorEq


def _cubic_eq(width=64, seed=1):
    rng = np.random.default_rng(seed)
    return DetectorEq(
        model="CUBIC",
        dark=450.0 + rng.normal(0, 2.0, width),
        coeffs={"A": np.full(width, 1e-8), "B": np.full(width, -3e-5),
                "C": 1.0 + rng.normal(0, 0.01, width)},   # ~1 % per-pixel PRNU
    )


def _bilinear_eq(width=64, seed=2):
    rng = np.random.default_rng(seed)
    a1 = 0.95 + rng.normal(0, 0.01, width)
    return DetectorEq(
        model="BILINEAR",
        dark=495.0 + rng.normal(0, 2.0, width),
        coeffs={"A1": a1, "A2": a1 + 0.01, "Zs": np.full(width, 600.0)},
    )


@pytest.mark.parametrize("eq_factory", [_cubic_eq, _bilinear_eq])
def test_forward_inverse_exact(eq_factory):
    eq = eq_factory()
    rng = np.random.default_rng(0)
    x_raw = eq.dark[None, :] + rng.uniform(20, 1500, size=(50, eq.dark.size))
    recovered = fwd.reverse_impress(fwd.forward_correct(x_raw, eq), eq)
    assert np.sqrt(np.mean((recovered - x_raw) ** 2)) < 1e-9


@pytest.mark.parametrize("eq_factory", [_cubic_eq, _bilinear_eq])
def test_relative_response_flattens_fpn(eq_factory):
    eq = eq_factory()
    flat = np.full((200, eq.dark.size), 800.0)        # uniform corrected signal
    raw = fwd.reverse_impress(flat, eq)               # impress real PRNU + dark → striped raw
    corrected = fwd.forward_correct(raw, eq)          # correct → should flatten
    assert fwd.column_fpn(corrected) < 0.3 * fwd.column_fpn(raw) + 1e-9
    assert np.allclose(corrected, flat, atol=1e-6)    # recovers the flat scene


def test_real_l1a_roundtrip_exact():
    l1a = os.environ.get("S2_E2ES_L1A")
    gipp_dir = os.environ.get("S2_E2ES_GIPP_DIR")
    if not (l1a and gipp_dir and os.path.isdir(gipp_dir)):
        pytest.skip("set S2_E2ES_L1A + S2_E2ES_GIPP_DIR to run on the real product")
    zarr = pytest.importorskip("zarr")  # noqa: F841
    from s2_e2es import gipp, io
    gs = gipp.load_gipp_set(gipp_dir)
    for b in ("B03", "B11"):
        eq = gs.band(b).detectors[1]
        x = io.read_l1a_raw(l1a, 1, b, lines=slice(0, 512))
        valid = (x > 0) & (x < 32768)
        xp = fwd.reverse_impress(fwd.forward_correct(x, eq), eq)
        assert np.sqrt(np.mean((xp[valid] - x[valid]) ** 2)) < 1e-6

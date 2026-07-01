"""Increment-1 MVP unit tests for the reverse radiometric chain.

Covers the ATBD §5 step properties + the verification section of the build plan:
algebraic invertibility, PSF radiometry preservation, the noise model (REQ-FUNC-021),
quantization bounds, and the full MVP chain output contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from s2_msi_raw_generator import adf, reverse, sensor


# --- sensor model -------------------------------------------------------------

def test_band_model_has_13_bands_no_pan():
    bands = sensor.all_bands()
    assert len(bands) == 13
    assert "PAN" not in sensor.BANDS
    # Real harvested gains (ATBD Annex A.11).
    assert sensor.band("B04").physical_gain == pytest.approx(4.50915)
    assert sensor.band("B12").physical_gain == pytest.approx(106.15880)


def test_tdi_bands_are_b03_b04_b11_b12():
    assert sensor.TDI_BANDS == frozenset({"B03", "B04", "B11", "B12"})
    assert sensor.band("B03").has_tdi and not sensor.band("B02").has_tdi


# --- S1: radiance <-> DN ------------------------------------------------------

def test_s1_radiance_to_dn_roundtrip_exact():
    b = sensor.band("B04")
    rng = np.random.default_rng(0)
    L = rng.uniform(0, 200, size=(64, 32))
    dn = reverse.s1_radiance_to_dn(L, b.physical_gain)   # DN = A·L
    L_back = dn / b.physical_gain                         # forward: L = DN/A
    np.testing.assert_allclose(L_back, L, rtol=1e-12)


# --- radiometric chain (S1,S7,S11,S12) is exactly invertible ------------------

def test_radiometric_roundtrip_exact():
    b = sensor.band("B05")
    a = adf.synthesize(b, n_det=48, seed=7)
    rng = np.random.default_rng(1)
    L = rng.uniform(0, b.lref * 2, size=(100, 48))
    dn = reverse.reverse_radiometric(L, a)
    L_back = reverse.forward_radiometric(dn, a)
    np.testing.assert_allclose(L_back, L, rtol=1e-9, atol=1e-9)


# --- S6: PSF re-blur preserves radiometry -------------------------------------

def test_psf_is_radiometry_preserving():
    a = adf.synthesize(sensor.band("B08"), n_det=40, seed=3)
    assert a.psf.sum() == pytest.approx(1.0)  # DC gain 1
    rng = np.random.default_rng(2)
    img = rng.uniform(10, 100, size=(80, 40))
    blurred = reverse.s6_psf_reblur(img, a.psf)
    assert blurred.sum() == pytest.approx(img.sum(), rel=1e-9)  # total flux conserved
    assert blurred.std() < img.std()  # actually blurs (reduces local variance)


def test_psf_mtf_at_nyquist_matches_target():
    # Exact discrete Nyquist (f=0.5 cyc/px) MTF of the marginal 1-D PSF = |Σ prof·(-1)^idx|.
    k = adf.gaussian_psf(mtf_nyquist=0.25, radius=4)
    prof = k.sum(axis=0)                     # marginal 1-D PSF (sums to 1)
    idx = np.arange(prof.size) - (prof.size // 2)
    nyq = abs(np.sum(prof * ((-1.0) ** idx)))
    assert nyq == pytest.approx(0.25, abs=0.01)


# --- S13: noise model reproduces sigma = sqrt(a + b*DN) (REQ-FUNC-021) --------

def test_noise_sigma_matches_model_within_5pct():
    b = sensor.band("B03")
    a = adf.synthesize(b, n_det=1, seed=5)
    rng = np.random.default_rng(42)
    dn_level = b.dn_ref
    flat = np.full((200, 200), dn_level)  # 40_000 px >= 10_000 (REQ-FUNC-021)
    noisy = reverse.s13_add_noise(flat, a.noise_a, a.noise_b, rng)
    measured = float(np.std(noisy - flat))
    expected = float(np.sqrt(a.noise_a + a.noise_b * dn_level))
    assert measured == pytest.approx(expected, rel=0.05)


def test_noise_fit_reproduces_snr_at_lref():
    for b in sensor.all_bands():
        na, nb = adf.fit_noise_coeffs(b)
        dn_ref = b.dn_ref
        sigma = np.sqrt(na + nb * dn_ref)
        snr = dn_ref / sigma
        assert snr == pytest.approx(b.snr_at_lref, rel=1e-6)


# --- S14: quantization contract ----------------------------------------------

def test_quantize_bounds_and_dtype():
    rng = np.random.default_rng(9)
    dn = rng.uniform(-50, 5000, size=(50, 50))
    q = reverse.s14_quantize(dn)
    assert q.dtype == np.uint16
    assert q.min() >= 0 and q.max() <= 4095
    # within +/- 0.5 of the (clipped) input
    clipped = np.clip(dn, 0, 4095)
    assert np.all(np.abs(q.astype(float) - clipped) <= 0.5 + 1e-9)


# --- full MVP chain contract --------------------------------------------------

def test_full_mvp_chain_output_contract():
    b = sensor.band("B04")
    a = adf.synthesize(b, n_det=64, seed=11)
    rng = np.random.default_rng(123)
    L = np.clip(rng.normal(b.lref, b.lref * 0.3, size=(128, 64)), 0, None)
    l0 = reverse.reverse_mvp(L, a, rng)
    assert l0.shape == L.shape
    assert l0.dtype == np.uint16
    assert l0.min() >= 0 and l0.max() <= 4095


def test_full_mvp_roundtrip_recovers_radiance_within_noise():
    # End-to-end seeded round-trip excluding PSF (deconv is approximate): the radiometric
    # path + noise + quantize should recover radiance to within the noise/quant budget.
    b = sensor.band("B02")
    a = adf.synthesize(b, n_det=64, seed=4)
    rng = np.random.default_rng(2024)
    L = np.full((150, 64), b.lref)
    dn = reverse.reverse_radiometric(L, a)
    dn = reverse.s13_add_noise(dn, a.noise_a, a.noise_b, rng)
    dn = reverse.s14_quantize(dn).astype(np.float64)
    L_back = reverse.forward_radiometric(dn, a)
    # mean radiance recovered within 1% (noise averages out over 150*64 px)
    assert np.mean(L_back) == pytest.approx(b.lref, rel=0.01)

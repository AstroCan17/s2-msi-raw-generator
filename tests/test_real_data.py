"""Real published-data tests: official ESA PSF matrices + SRF per-unit spectral characterisation.

These assert that the reverse chain uses the real SentiWiki PSF (`data/psf/`) and the real SRF
band centre/bandwidth/equivalent wavelength (`sensor.py`) — not synthetic stand-ins.
"""

from __future__ import annotations

import numpy as np
import pytest

from s2_e2es import adf, sensor


# --- Real PSF matrices --------------------------------------------------------

@pytest.mark.parametrize("unit", sensor.UNITS)
@pytest.mark.parametrize("bn", [b for b in sensor.BANDS if b != "B10"])
def test_real_psf_loads_and_is_normalised(unit, bn):
    osamp = adf.load_oversampled_psf(bn, unit)
    assert osamp is not None
    assert osamp.shape == (33, 33)                    # ESA: 33×33, oversampling 5
    assert osamp.sum() == pytest.approx(1.0, abs=1e-3)

    k = adf.real_psf_kernel(bn, unit)
    assert k.ndim == 2 and k.shape[0] == k.shape[1] and k.shape[0] % 2 == 1
    assert k.sum() == pytest.approx(1.0)               # DC gain 1 (radiometry-preserving)
    centre = k.shape[0] // 2
    assert k[centre, centre] == k.max()                # peak at centre


def test_b10_has_no_psf_uses_identity():
    assert adf.load_oversampled_psf("B10", "S2A") is None
    k = adf.real_psf_kernel("B10", "S2A")
    assert k.shape == (1, 1) and k[0, 0] == 1.0         # identity → no re-blur


def test_psf_differs_between_units():
    # Per-unit PSF really differs (S2A 2024 vs S2B 2023 acquisitions).
    ka = adf.real_psf_kernel("B05", "S2A")
    kb = adf.real_psf_kernel("B05", "S2B")
    assert ka.shape == kb.shape
    assert not np.allclose(ka, kb)


def test_synthesize_uses_real_psf():
    a = adf.synthesize(sensor.band("B04", "S2A"), n_det=32, seed=1)
    assert np.array_equal(a.psf, adf.real_psf_kernel("B04", "S2A"))


# --- Real SRF spectral characterisation --------------------------------------

def test_band_spectral_values_are_real_per_unit():
    b = sensor.band("B05", "S2C")
    assert b.centre_nm == 707.5
    assert b.bandwidth_nm == 15
    assert b.equiv_wavelength_nm == pytest.approx(707.065, abs=1e-3)
    # B05 centre really shifts between units (the ~15 % SRF concern).
    assert sensor.band("B05", "S2A").centre_nm == 705.0


def test_unit_from_platform():
    assert sensor.unit_from_platform("Sentinel-2A") == "S2A"
    assert sensor.unit_from_platform("Sentinel-2B") == "S2B"
    assert sensor.unit_from_platform("S2C") == "S2C"


# --- Real noise model (α, β from the L1A product) ----------------------------

def test_noise_coeffs_are_the_real_product_values():
    b = sensor.band("B05")
    a, beta = adf.noise_coeffs(b)
    # S2-RUT model √(α²+β·DN): a = α², b = β, with α,β straight from the L1A noise_model.
    assert sensor.NOISE_ALPHA["B05"] == 0.578 and sensor.NOISE_BETA["B05"] == 0.03123
    assert a == pytest.approx(0.578 ** 2) and beta == 0.03123


@pytest.mark.parametrize("bn", [b for b in sensor.BANDS])
def test_real_noise_model_reproduces_spec_snr(bn):
    # σ = √(α + β·DN); the DN where DN/σ == SNR must exist and reproduce the spec SNR exactly.
    b = sensor.band(bn)
    a, beta = adf.noise_coeffs(b)
    snr = b.snr_at_lref
    # solve DN² − snr²·β·DN − snr²·α = 0 for the positive root
    dn_ref = (snr**2 * beta + np.sqrt((snr**2 * beta) ** 2 + 4 * snr**2 * a)) / 2
    sigma = np.sqrt(a + beta * dn_ref)
    assert dn_ref / sigma == pytest.approx(snr, rel=1e-6)
    assert dn_ref < 4096                        # within the 12-bit range


def test_spectral_band_info_carries_real_wavelengths():
    info = sensor.spectral_band_info("S2A")
    assert info["02"]["central_wavelength"]["value"] == 492.0
    assert info["02"]["bandwidth"]["value"] == 64
    assert info["8A"]["equivalent_wavelength"]["value"] == pytest.approx(864.711, abs=1e-3)


# --- from_product (real per-detector PRNU/dark) ------------------------------

def test_from_product_marks_real_and_keeps_real_psf():
    b = sensor.band("B03", "S2A")
    n = 16
    a = adf.BandADF.from_product(
        b,
        prnu_gain=np.full(n, 1.01),
        dark_dn=np.full(n, 3.0),
    )
    assert a.prnu_is_real is True
    assert np.array_equal(a.psf, adf.real_psf_kernel("B03", "S2A"))
    assert a.eq_gain.shape == (n,) and np.all(a.eq_gain == 1.0)

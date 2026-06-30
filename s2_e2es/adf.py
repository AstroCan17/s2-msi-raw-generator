"""Synthetic-fallback ADFs — physically-plausible parameters fitted to the datasheet.

Real L1 radiometric ADFs (RABCA/RNOMO/REQOG/REOB2/RDEFI) are credentialed (`s2msi`, blocker
#36) and the DPR-common public bucket does not host them (ATBD §6). For the MVP we synthesize:

* gain      — REAL `physical_gains` from the product metadata (sensor.PHYSICAL_GAIN), not synthetic.
* noise a,b — fitted so ``σ=√(a+b·DN)`` reproduces the band's SNR@Lref (ATBD Annex A.6, REQ-FUNC-021).
* PSF       — Gaussian-from-MTF kernel matching MTF@Nyquist (ATBD Annex A.4).
* PRNU      — 1D per-detector relative-gain signature (PRNU paper: 1D along the pushbroom column).
* dark      — small per-detector dark offset (VNIR <1 DN, SWIR larger; ATBD Annex A.6).

REQ-FUNC-045: callers must log that synthetic ADFs are in use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import sensor


def fit_noise_coeffs(b: sensor.Band, read_fraction: float = 0.1) -> tuple[float, float]:
    """Fit ``(a, b)`` of ``σ² = a + b·DN`` to the band's SNR@Lref.

    Splits the total variance at Lref (``σ_ref² = (DN_ref/SNR)²``) into a read/dark floor
    ``a = read_fraction·σ_ref²`` and a shot term ``b = (1-read_fraction)·σ_ref²/DN_ref``, so that
    ``σ(DN_ref) = σ_ref`` exactly (reproduces SNR@Lref) with ``a, b > 0`` for every band.
    """
    dn_ref = b.dn_ref
    sigma_ref2 = (dn_ref / b.snr_at_lref) ** 2
    a = read_fraction * sigma_ref2
    b_coeff = (sigma_ref2 - a) / dn_ref
    return a, b_coeff


def _discrete_nyquist_mtf(ax: np.ndarray, sigma: float) -> float:
    """1-D Nyquist (f=0.5 cyc/px) MTF of a normalized sampled Gaussian over offsets ``ax``."""
    g = np.exp(-(ax**2) / (2.0 * sigma**2))
    g /= g.sum()
    return float(abs(np.sum(g * ((-1.0) ** ax))))  # |DTFT at f=0.5|


def gaussian_psf(mtf_nyquist: float = 0.25, radius: int = 4) -> np.ndarray:
    """Normalized 2-D separable Gaussian PSF whose **discrete** MTF at Nyquist == ``mtf_nyquist``.

    The continuous formula ``MTF(f)=exp(-2π²σ²f²)`` overestimates attenuation for a sub-pixel,
    truncated, re-normalized kernel, so ``σ`` is calibrated numerically (bisection) to hit the
    discrete target. Kernel sums to 1 (DC gain 1, radiometry-preserving).
    """
    if not 0.0 < mtf_nyquist < 1.0:
        raise ValueError("mtf_nyquist must be in (0, 1)")
    ax = np.arange(-radius, radius + 1, dtype=np.float64)
    lo, hi = 0.1, 5.0  # Nyquist MTF decreases monotonically with σ
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _discrete_nyquist_mtf(ax, mid) > mtf_nyquist:
            lo = mid
        else:
            hi = mid
    sigma = 0.5 * (lo + hi)
    gx = np.exp(-(ax**2) / (2.0 * sigma**2))
    k = np.outer(gx, gx)
    return k / k.sum()


@dataclass(frozen=True)
class BandADF:
    """Synthetic per-band ADF set for the reverse chain (per detector of width ``n_det``)."""

    band: sensor.Band
    noise_a: float
    noise_b: float
    psf: np.ndarray
    prnu_gain: np.ndarray   # (n_det,) relative response, ~1.0
    dark_dn: np.ndarray     # (n_det,) dark offset in DN
    eq_gain: np.ndarray     # (n_det,) onboard equalization gain, ~1.0
    eq_offset: np.ndarray   # (n_det,) onboard equalization offset in DN


def synthesize(
    b: sensor.Band,
    n_det: int,
    *,
    seed: int = 0,
    prnu_std: float = 0.005,
    mtf_nyquist: float = 0.25,
) -> BandADF:
    """Build a seeded synthetic :class:`BandADF` for band ``b`` over ``n_det`` detector columns."""
    rng = np.random.default_rng(seed + hash(b.name) % 10_000)
    a, bb = fit_noise_coeffs(b)
    # 1D per-detector PRNU (relative response), dark larger for SWIR.
    prnu_gain = 1.0 + rng.normal(0.0, prnu_std, size=n_det)
    dark_base = 5.0 if b.name in sensor.SWIR_BANDS else 0.8
    dark_dn = np.abs(rng.normal(dark_base, dark_base * 0.1, size=n_det))
    eq_gain = 1.0 + rng.normal(0.0, prnu_std / 2.0, size=n_det)
    eq_offset = rng.normal(0.0, 0.5, size=n_det)
    return BandADF(
        band=b,
        noise_a=a,
        noise_b=bb,
        psf=gaussian_psf(mtf_nyquist),
        prnu_gain=prnu_gain,
        dark_dn=dark_dn,
        eq_gain=eq_gain,
        eq_offset=eq_offset,
    )

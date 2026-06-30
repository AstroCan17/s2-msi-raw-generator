"""S2 in-flight radiometric calibration sub-set — synthetic CSM sun-diffuser + dark → derived ADF.

A **two-reference** radiometric calibration in Sentinel-2's reflective domain: the high-signal
reference is the on-board **CSM sun-diffuser** (a full-field, full-pupil Lambertian diffuser giving a
near-uniform bright image), and the zero reference is a **dark** acquisition (CSM shutter closed /
nighttime ocean). Per the public L1 ATBD §4.1.1.2.2:

    D(j)  = ⟨X_dark(i, j)⟩_i                                   (dark from a dark acquisition)
    g(j)  = A · ⟨L_diff⟩_i / ⟨X_diff(i, j) − D(j)⟩_i           (relative response from the diffuser)
    with  ⟨g(j)⟩_j = 1   ⇒  fixes the absolute calibration coefficient A.

This module (a) **generates** the synthetic dark + diffuser L0 acquisitions by impressing the *true*
ADF through the reverse chain, then (b) **derives** ``D``, ``g`` and ``A`` back from them — the
*estimated* calibration a downstream processor would actually use, instead of the truth ADF. Closing
this loop (impress truth → estimate → use the estimate) is the E2ES **inverse-crime cure**: residuals
then reflect calibration uncertainty, not a tautology.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .adf import BandADF
from .reverse import reverse_mvp


@dataclass(frozen=True)
class DerivedCalibration:
    """Calibration coefficients *estimated* from the synthetic diffuser + dark acquisitions."""

    band: str
    dark: np.ndarray            # (n_det,) estimated per-detector dark D(j)
    relative_response: np.ndarray  # (n_det,) estimated relative response g(j), ⟨g⟩ = 1
    abs_coeff: float            # estimated absolute calibration coefficient A
    l_diff: float               # diffuser radiance used


def synth_dark_acquisition(adf: BandADF, n_lines: int, rng: np.random.Generator) -> np.ndarray:
    """Synthetic **dark** L0 acquisition (zero scene radiance → dark pedestal + sensor noise)."""
    zero = np.zeros((n_lines, adf.dark_dn.shape[0]), dtype=np.float64)
    return reverse_mvp(zero, adf, rng).astype(np.float64)


def synth_diffuser_acquisition(
    adf: BandADF, l_diff: float, n_lines: int, rng: np.random.Generator
) -> np.ndarray:
    """Synthetic **sun-diffuser** L0 acquisition (uniform full-field radiance ``l_diff`` → raw DN).

    The diffuser is a flat field, so the radiance frame is uniform; the reverse chain impresses the
    true relative response (PRNU), dark and noise — exactly what the on-board CSM diffuser measures.
    """
    uniform = np.full((n_lines, adf.dark_dn.shape[0]), float(l_diff), dtype=np.float64)
    return reverse_mvp(uniform, adf, rng).astype(np.float64)


def derive_dark(dark_acq: np.ndarray) -> np.ndarray:
    """Estimate the per-detector dark ``D(j) = ⟨X_dark⟩_i`` (average over lines reduces noise)."""
    return np.mean(np.asarray(dark_acq, dtype=np.float64), axis=0)


def derive_relative_response(
    diffuser_acq: np.ndarray, dark_est: np.ndarray, l_diff: float
) -> tuple[np.ndarray, float]:
    """Estimate the relative response ``g(j)`` (⟨g⟩ = 1) and the absolute coefficient ``A``.

    ``g(j) = A·L_diff / ⟨X_diff(i,j) − D(j)⟩_i`` then normalised so ``⟨g(j)⟩_j = 1`` (L1 ATBD).
    """
    signal = np.mean(np.asarray(diffuser_acq, dtype=np.float64), axis=0) - np.asarray(dark_est)
    signal = np.where(signal > 0, signal, np.nan)
    g_raw = 1.0 / signal                                  # g ∝ 1 / (X_diff − D)
    g = g_raw / np.nanmean(g_raw)                         # normalise ⟨g⟩_j = 1
    g = np.where(np.isfinite(g), g, 1.0)
    abs_coeff = float(np.nanmean(signal) / l_diff)        # A·L_diff = ⟨X_diff − D⟩ at ⟨g⟩ = 1
    return g, abs_coeff


def calibrate(
    adf: BandADF,
    l_diff: float | None = None,
    *,
    n_dark: int = 256,
    n_diffuser: int = 256,
    seed: int = 0,
) -> DerivedCalibration:
    """Run the full S2 calibration sub-set on the *true* ``adf``: synthesise the dark + diffuser
    acquisitions, then derive the estimated ``D``, ``g``, ``A``.

    ``l_diff`` defaults to a bright diffuser radiance (≈1.5·Lref), staying within the dynamic range.
    """
    if l_diff is None:
        l_diff = 1.5 * adf.band.lref
    rng = np.random.default_rng(seed)
    dark_acq = synth_dark_acquisition(adf, n_dark, rng)
    diff_acq = synth_diffuser_acquisition(adf, l_diff, n_diffuser, rng)
    dark_est = derive_dark(dark_acq)
    g_est, a_est = derive_relative_response(diff_acq, dark_est, l_diff)
    return DerivedCalibration(adf.band.name, dark_est, g_est, a_est, float(l_diff))


def estimated_adf(adf: BandADF, cal: DerivedCalibration) -> BandADF:
    """Build a new :class:`BandADF` using the **estimated** dark + relative response (not the truth).

    PSF and the noise model stay as-is; only the per-detector dark/PRNU are replaced by the
    diffuser/dark-derived estimates — the coefficients a processor would actually apply.
    """
    return BandADF(
        band=adf.band,
        noise_a=adf.noise_a,
        noise_b=adf.noise_b,
        psf=adf.psf,
        prnu_gain=cal.relative_response,
        dark_dn=cal.dark,
        eq_gain=adf.eq_gain,
        eq_offset=adf.eq_offset,
        prnu_is_real=adf.prnu_is_real,
        source="derived (CSM diffuser + dark calibration)",
    )

"""Reverse radiometric chain (L1B radiance → L0 RAW DN), pure NumPy.

Each function is one ATBD §5 step (S1, S6, S7, S11, S12, S13, S14). All operate on a 2-D
per-band, per-detector array ``(lines, detector_columns)``. The MVP chain (Increment 1) is
S1 → S6 → S7 → S11 → S12 → S13 → S14. Steps S3/S4/S5/S8/S9/S10/S15 (framing, offset, binning,
SWIR rearrangement, crosstalk, blind pixels, ISP) are Increment 3+/Full.
"""

from __future__ import annotations

import numpy as np

from .adf import BandADF


# --- individual reverse steps -------------------------------------------------

def s1_radiance_to_dn(radiance: np.ndarray, physical_gain: float) -> np.ndarray:
    """S1 — radiance → calibrated DN: ``DN = L / physical_gain`` (inverse of dn_to_radiance)."""
    return np.asarray(radiance, dtype=np.float64) / physical_gain


def s6_psf_reblur(img: np.ndarray, psf: np.ndarray) -> np.ndarray:
    """S6 — re-introduce optical blur: circular 2-D convolution with a DC-unit PSF kernel.

    Radiometry-preserving (kernel sums to 1 ⇒ array total is preserved exactly).
    """
    img = np.asarray(img, dtype=np.float64)
    h, w = img.shape
    kh, kw = psf.shape
    # Embed the centered kernel on the (h, w) grid, FOLDING modulo the image size so it works
    # even when the kernel is larger than the image (accumulation keeps the kernel sum = 1).
    k = np.zeros((h, w), dtype=np.float64)
    ii = (np.arange(kh) - kh // 2) % h
    jj = (np.arange(kw) - kw // 2) % w
    np.add.at(k, (ii[:, None], jj[None, :]), psf)
    return np.fft.irfft2(np.fft.rfft2(img) * np.fft.rfft2(k), s=(h, w))


def s7_impress_relative_response(dn: np.ndarray, prnu_gain: np.ndarray) -> np.ndarray:
    """S7 — re-introduce per-detector PRNU: ``DN /= gain[detector]`` (undo equalization)."""
    return np.asarray(dn, dtype=np.float64) / prnu_gain[np.newaxis, :]


def s11_reapply_dark(dn: np.ndarray, dark_dn: np.ndarray) -> np.ndarray:
    """S11 — add the per-detector dark signal back: ``DN += dark``."""
    return np.asarray(dn, dtype=np.float64) + dark_dn[np.newaxis, :]


def s12_reapply_onboard_eq(dn: np.ndarray, eq_gain: np.ndarray, eq_offset: np.ndarray) -> np.ndarray:
    """S12 — reverse onboard equalization: ``DN_raw = DN_eq / gain_ob + offset_ob``."""
    return np.asarray(dn, dtype=np.float64) / eq_gain[np.newaxis, :] + eq_offset[np.newaxis, :]


def s13_add_noise(dn: np.ndarray, noise_a: float, noise_b: float, rng: np.random.Generator) -> np.ndarray:
    """S13 — add signal-dependent sensor noise: ``σ = √(a + b·DN)``, ``DN += N(0, σ)``."""
    dn = np.asarray(dn, dtype=np.float64)
    sigma = np.sqrt(np.maximum(noise_a + noise_b * np.maximum(dn, 0.0), 0.0))
    return dn + rng.normal(0.0, 1.0, size=dn.shape) * sigma


def s14_quantize(dn: np.ndarray, dn_max: int = 4095) -> np.ndarray:
    """S14 — quantize to 12-bit and clip: ``clip(round(DN), 0, 4095)`` → uint16."""
    return np.clip(np.rint(np.asarray(dn, dtype=np.float64)), 0, dn_max).astype(np.uint16)


# --- MVP chain ----------------------------------------------------------------

def reverse_mvp(radiance: np.ndarray, adf: BandADF, rng: np.random.Generator) -> np.ndarray:
    """Full MVP reverse chain for one band/detector: radiance → uint16 L0 DN.

    S1 → S6 → S7 → S11 → S12 → S13 → S14.
    """
    dn = s1_radiance_to_dn(radiance, adf.band.physical_gain)
    dn = s6_psf_reblur(dn, adf.psf)
    dn = s7_impress_relative_response(dn, adf.prnu_gain)
    dn = s11_reapply_dark(dn, adf.dark_dn)
    dn = s12_reapply_onboard_eq(dn, adf.eq_gain, adf.eq_offset)
    dn = s13_add_noise(dn, adf.noise_a, adf.noise_b, rng)
    return s14_quantize(dn)


# --- radiometric-only forward (the processor's algebraic inverse; for round-trip V&V) ---

def reverse_radiometric(radiance: np.ndarray, adf: BandADF) -> np.ndarray:
    """Reverse S1→S7→S11→S12 only (no PSF, no noise, no quantize) — exactly invertible."""
    dn = s1_radiance_to_dn(radiance, adf.band.physical_gain)
    dn = s7_impress_relative_response(dn, adf.prnu_gain)
    dn = s11_reapply_dark(dn, adf.dark_dn)
    return s12_reapply_onboard_eq(dn, adf.eq_gain, adf.eq_offset)


def forward_radiometric(dn: np.ndarray, adf: BandADF) -> np.ndarray:
    """Algebraic forward (processor) inverse of :func:`reverse_radiometric`: DN_raw → radiance."""
    dn = np.asarray(dn, dtype=np.float64)
    dn = (dn - adf.eq_offset[np.newaxis, :]) * adf.eq_gain[np.newaxis, :]   # undo S12
    dn = dn - adf.dark_dn[np.newaxis, :]                                    # undo S11
    dn = dn * adf.prnu_gain[np.newaxis, :]                                  # undo S7 (equalize)
    return dn * adf.band.physical_gain                                      # undo S1

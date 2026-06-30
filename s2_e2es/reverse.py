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


# --- Increment 3: remaining chain steps (S3, S4, S5, S8, S9, S10) --------------

def s3_undo_framing(img: np.ndarray) -> np.ndarray:
    """S3 — undo scene framing & round/clamp.

    Framing (cutting the continuous detector strip into scenes) is a product-assembly concern,
    handled in :mod:`s2_e2es.l0product`; on a single full-strip granule array this is identity.
    """
    return np.asarray(img, dtype=np.float64)


def s4_undo_radiometric_offset(dn: np.ndarray, offset: float = 0.0) -> np.ndarray:
    """S4 — remove the PB04.00 product offset: ``DN -= offset``.

    Only relevant when entering from offset-encoded product DN; for the radiance entry path the
    offset is 0 (raw counts carry no product offset). ``sensor.RADIO_ADD_OFFSET_L1B`` is −100.
    """
    return np.asarray(dn, dtype=np.float64) - offset


def s5_unbin(img: np.ndarray, factor: int = 3, axis: int = 1) -> np.ndarray:
    """S5 — un-bin a 60 m band to detector-level by replication along ``axis`` (×``factor``).

    Inverse of forward mean-binning (e.g. 20 m → 60 m, factor 3). Replication preserves each
    cell's value; binning the result back recovers the input.
    """
    if factor < 1:
        raise ValueError("factor must be >= 1")
    return np.repeat(np.asarray(img, dtype=np.float64), factor, axis=axis)


def s8_restage_swir(img: np.ndarray, shifts: np.ndarray) -> np.ndarray:
    """S8 — re-introduce the staggered SWIR readout: roll each detector column along-track.

    ``shifts[c]`` is the integer line shift for column ``c`` (PyRawS-style deterministic shift
    map). Exactly invertible by restaging with ``-shifts``.
    """
    img = np.asarray(img, dtype=np.float64)
    shifts = np.asarray(shifts, dtype=int)
    out = np.empty_like(img)
    for c in range(img.shape[1]):
        out[:, c] = np.roll(img[:, c], int(shifts[c]))
    return out


def s9_apply_crosstalk(bands: dict[str, np.ndarray], coeff: float = 0.002) -> dict[str, np.ndarray]:
    """S9 — inter-band optical/electrical crosstalk within one resolution group.

    Each band gains ``coeff`` × (sum of the other bands). ``bands`` must be a dict of identical-
    shape arrays. <0.5 % channel-to-channel (ATBD Annex A.6). For small ``coeff`` the inverse is
    ≈ subtract ``coeff`` × neighbours.
    """
    names = list(bands)
    if len({bands[n].shape for n in names}) != 1:
        raise ValueError("crosstalk requires same-shape bands (one resolution group)")
    stack = np.stack([np.asarray(bands[n], dtype=np.float64) for n in names])  # (B, H, W)
    total = stack.sum(axis=0)
    return {n: stack[i] + coeff * (total - stack[i]) for i, n in enumerate(names)}


def s10_inject_defects(
    img: np.ndarray,
    dead_cols: tuple[int, ...] = (),
    hot_pixels: tuple[tuple[int, int], ...] = (),
    dn_max: int = 4095,
) -> tuple[np.ndarray, np.ndarray]:
    """S10 — re-insert blind/defective pixels: dead columns → 0, hot pixels → saturated.

    Returns ``(img_with_defects, qa)`` where ``qa`` (uint8) has bit0 = dead, bit1 = hot.
    (S2C Cal/Val: 3 defective in B11, 1 in B12.)
    """
    img = np.asarray(img, dtype=np.float64).copy()
    qa = np.zeros(img.shape, dtype=np.uint8)
    for c in dead_cols:
        img[:, c] = 0.0
        qa[:, c] |= 1
    for r, c in hot_pixels:
        img[r, c] = float(dn_max)
        qa[r, c] |= 2
    return img, qa


def reverse_full(
    radiance: np.ndarray,
    adf: BandADF,
    rng: np.random.Generator,
    *,
    swir_shifts: np.ndarray | None = None,
    dead_cols: tuple[int, ...] = (),
    hot_pixels: tuple[tuple[int, int], ...] = (),
) -> tuple[np.ndarray, np.ndarray]:
    """Extended per-band reverse chain (Inc 3): adds S8 (SWIR re-stagger) and S10 (defects).

    S1 → S6 → S7 → [S8 if ``swir_shifts``] → [S10 if defects] → S11 → S12 → S13 → S14.
    (S5 un-bin changes width and S9 crosstalk needs multiple bands — applied separately.)
    Returns ``(uint16 L0 DN, qa uint8)``.
    """
    dn = s1_radiance_to_dn(radiance, adf.band.physical_gain)
    dn = s6_psf_reblur(dn, adf.psf)
    dn = s7_impress_relative_response(dn, adf.prnu_gain)
    if swir_shifts is not None:
        dn = s8_restage_swir(dn, swir_shifts)
    qa = np.zeros(dn.shape, dtype=np.uint8)
    if dead_cols or hot_pixels:
        dn, qa = s10_inject_defects(dn, dead_cols, hot_pixels)
    dn = s11_reapply_dark(dn, adf.dark_dn)
    dn = s12_reapply_onboard_eq(dn, adf.eq_gain, adf.eq_offset)
    dn = s13_add_noise(dn, adf.noise_a, adf.noise_b, rng)
    return s14_quantize(dn), qa

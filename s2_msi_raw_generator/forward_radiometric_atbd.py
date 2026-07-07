"""Original implementation of the Sentinel-2 on-ground radiometric model (public L1 ATBD §4.1.1).

Given the per-pixel GIPP coefficients (``s2_msi_raw_generator.gipp.DetectorEq``), this provides the **forward**
radiometric correction (raw L1A → corrected L1B) and its exact **inverse** (the reverse-E2ES impress
step). The model is the published one::

    Z = X − D                                   (dark-signal subtraction; D = COEFF_D)
    Y = G(Z)   with   G = A·Z³+B·Z²+C·Z         (VNIR cubic relative-response)
                or    A1·Z  | A2·Z+(A1−A2)·Zs   (SWIR bilinear, knee at Z = Zs)

Everything is written from the public ATBD equations; no processor source is used. Coefficients are
per across-track pixel (``act``) and broadcast over image lines.
"""

from __future__ import annotations

import numpy as np

from .gipp import DetectorEq


def _b(coeff: np.ndarray, width: int) -> np.ndarray:
    """Broadcast a per-pixel coefficient (act,) to a frame row; crop/pad to ``width`` if needed."""
    c = np.asarray(coeff, dtype=np.float64)
    if c.size != width:  # align to the active frame width (centred)
        if c.size > width:
            start = (c.size - width) // 2
            c = c[start : start + width]
        else:
            c = np.pad(c, (0, width - c.size), mode="edge")
    return c[np.newaxis, :]


def forward_equalize(z: np.ndarray, eq: DetectorEq) -> np.ndarray:
    """Apply the relative-response model ``Y = G(Z)`` (dark-subtracted signal Z → equalized Y)."""
    z = np.asarray(z, dtype=np.float64)
    w = z.shape[1]
    if eq.model == "CUBIC":
        a, b, c = (_b(eq.coeffs[k], w) for k in ("A", "B", "C"))
        return a * z**3 + b * z**2 + c * z
    a1, a2, zs = (_b(eq.coeffs[k], w) for k in ("A1", "A2", "Zs"))
    return np.where(z <= zs, a1 * z, a2 * z + (a1 - a2) * zs)


def inverse_equalize(y: np.ndarray, eq: DetectorEq, iters: int = 6) -> np.ndarray:
    """Invert ``G``: equalized Y → dark-subtracted signal Z (impress the per-pixel relative response)."""
    y = np.asarray(y, dtype=np.float64)
    w = y.shape[1]
    if eq.model == "CUBIC":
        a, b, c = (_b(eq.coeffs[k], w) for k in ("A", "B", "C"))
        z = y / c  # A,B ≈ 0 → excellent start; refine by Newton
        for _ in range(iters):
            f = a * z**3 + b * z**2 + c * z - y
            df = 3.0 * a * z**2 + 2.0 * b * z + c
            z = z - f / df
        return z
    a1, a2, zs = (_b(eq.coeffs[k], w) for k in ("A1", "A2", "Zs"))
    y_knee = a1 * zs
    return np.where(y <= y_knee, y / a1, (y - (a1 - a2) * zs) / a2)


def forward_correct(x_raw: np.ndarray, eq: DetectorEq) -> np.ndarray:
    """Forward radiometric correction L1A→L1B: ``Y = G(X − D)`` (subtract dark, equalize)."""
    x = np.asarray(x_raw, dtype=np.float64)
    z = x - _b(eq.dark, x.shape[1])
    return forward_equalize(z, eq)


def reverse_impress(y: np.ndarray, eq: DetectorEq) -> np.ndarray:
    """Reverse (E2ES) of :func:`forward_correct`: corrected L1B → raw L1A ``X = G⁻¹(Y) + D``."""
    z = inverse_equalize(y, eq)
    return z + _b(eq.dark, z.shape[1])


def reapply_onboard_eq(z_signal: np.ndarray, reob2: dict[str, np.ndarray]) -> np.ndarray:
    """S12 — re-apply the on-board bilinear equalization non-linearity (undo forward step 1).

    The forward ``inverse_equalization`` un-does the on-board companding ``Z = Y/a1 | (Y−(a1−a2)zs)/a2``
    (``X = Z + d``); its E2ES re-application on the **dark-subtracted signal** ``z`` (downlink-
    consistent) is ``y = a1·z`` for ``z ≤ zs`` else ``a2·z + (a1−a2)·zs`` (REOB2 ``a1,a2,zs``). The
    REOB2 dark ``d`` (raw-detector domain, ≈455 DN) cancels the raw-detector dark and is **not**
    re-added here — the downlink L0 pedestal is the separate ``l0_dark_level`` term. For S2B
    ``a1≈1.005, a2≈0.995`` so this is a sub-percent gain with a knee at ``z ≈ zs``.
    """
    z = np.asarray(z_signal, dtype=np.float64)
    w = z.shape[1]
    a1, a2, zs = (_b(reob2[k], w) for k in ("a1", "a2", "zs"))
    return np.where(z <= zs, a1 * z, a2 * z + (a1 - a2) * zs)


def restage_swir_lines(img: np.ndarray, shifts: np.ndarray,
                       kernel: np.ndarray | None = None, method: str = "shift") -> np.ndarray:
    """S8 — re-introduce the SWIR staggered readout (reverse of the forward re-arrangement).

    ``shifts[c] ∈ {−1, 0, +1}`` flags which across-track columns move and the direction. ``method``
    ``"shift"`` (B11/B12) rolls the flagged column by ±1 whole line; ``"interp"`` (B10) applies the
    ±1/3-line sub-pixel shift as a 3-tap ``kernel`` convolution (``kernel`` for +, reversed for −;
    lossy — the forward convolution is not exactly invertible). Along-track roll commutes with the
    per-column radiometric ops, so the exact placement in the chain is not critical. ``shifts`` is
    centre-aligned to the frame width (SWIR blind columns sit at the edges).
    """
    img = np.asarray(img, dtype=np.float64)
    w = img.shape[1]
    s = np.rint(np.asarray(shifts)).astype(int)
    if s.size != w:                                   # align the physical-detector map to the frame
        if s.size > w:
            start = (s.size - w) // 2
            s = s[start : start + w]
        else:
            s = np.pad(s, (0, w - s.size), mode="edge")
    out = img.copy()
    interp = method == "interp" and kernel is not None and np.asarray(kernel).size > 0
    k = np.asarray(kernel, dtype=np.float64) if interp else None
    for c in range(w):
        sc = int(s[c])
        if sc == 0:
            continue
        if interp:
            out[:, c] = np.convolve(img[:, c], k if sc > 0 else k[::-1], mode="same")
        else:
            out[:, c] = np.roll(img[:, c], sc)
    return out


def reverse_l1b_to_l0(
    l1b_dn: np.ndarray,
    eq: DetectorEq,
    *,
    radio_offset_l1b: float,
    l0_dark_level: float,
    unbin_factor: int = 1,
    dn_max: int = 4095,
    swir_shift: tuple[np.ndarray, np.ndarray, str] | None = None,
    defective_cols: np.ndarray | None = None,
    onboard_eq: dict[str, np.ndarray] | None = None,
    nodata: float = 0.0,
) -> np.ndarray:
    """E2ES reverse of the L0→L1B radiometric chain: real L1B digital counts → L0 raw uint16 DN.

    The SentiWiki / EOPF forward chain (ON steps) is ``on-board-eq⁻¹(REOB2) → dark → blind →
    crosstalk(RCRCO) → relative-response(REQOG) → SWIR-rearr(RSWIR) → defective(RDEPI) →
    restoration[OFF] → binning → +RADIO_ADD_OFFSET``. This inverts it in the **downlink DN domain**
    (where both real L1B and L0 live), undoing the steps in reverse order::

        z    = G⁻¹(L1B + radio_offset_l1b)          # undo offset (S4) + impress relative response (S7)
        z    = a·z (on-board-eq non-linearity)      # S12 — undo REOB2 (a1≈a2≈1, sub-percent; optional)
        raw  = z + l0_dark_level · (D/⟨D⟩)           # S11 — L0-domain dark pedestal; DSNU shape from COEFF_D
        raw  = repeat(raw, ×unbin_factor)           # S5 — un-bin (60 m); replication (sub-pixel irrecoverable)
        raw  = restage_swir_lines(raw, swir_shift)  # S8 — re-introduce the staggered SWIR readout
        raw[:, defective_cols] = nodata             # S10 — re-stamp the RDEPI defective columns

    Dark is the *downlink*-domain ``l0_dark_level`` (≈50 DN), **not** the raw-detector ``eq.dark``
    (COEFF_D ≈440 DN, a different domain — its ≈455 DN cancels the REOB2 ``d``, so REOB2 contributes
    only its ``a1/a2`` non-linearity here); ``eq.dark`` supplies only the unitless DSNU column *shape*.

    **Skipped — deliberately:** MTF restoration/deconvolution and de-noising (forward step 8) are
    ``feature_flag_with_deconvolution/denoising = False`` in the operational payload (SentiWiki:
    *"restoration disabled by default — instrument MTF already high"*), so the L1B still carries the
    full instrument PSF and its noise realisation; re-blurring (S6 PSF) or re-noising (S13) would
    double-count and is **not** applied. Crosstalk (S9, RCRCO) is applied at the phase level (needs
    the neighbouring same-resolution bands; ≈0 for S2A/B).

    Optional full-chain inputs (all ``None`` → the validated radiometric-only reverse): ``swir_shift``
    = ``(shifts, kernel, method)`` from :func:`~s2_msi_raw_generator.gipp.read_rswir_eopf`;
    ``defective_cols`` = RDEPI ``singularity_columns``; ``onboard_eq`` = REOB2 coefficients from
    :func:`~s2_msi_raw_generator.gipp.read_reob2_eopf`. Validated against the real 2024-04-08 S2B PPB
    pair (all 13 bands): median ≤~5 %, active-region column FPN matches, CCSDS-122/ISP round-trip
    bit-exact; S8 brings the SWIR (B11/B12) images into spatial agreement.
    """
    x = np.asarray(l1b_dn, dtype=np.float64)
    z = inverse_equalize(x + radio_offset_l1b, eq)          # S4 offset + S7 relative response
    if onboard_eq is not None:                              # S12 on-board-eq non-linearity
        z = reapply_onboard_eq(z, onboard_eq)
    dsnu = np.asarray(eq.dark, dtype=np.float64)
    dsnu = dsnu / dsnu.mean()
    raw = z + l0_dark_level * _b(dsnu, z.shape[1])          # S11 downlink dark pedestal
    if unbin_factor > 1:                                    # S5 un-bin (60 m)
        raw = np.repeat(raw, unbin_factor, axis=1)
    if swir_shift is not None:                              # S8 re-stagger the SWIR readout
        shifts, kernel, method = swir_shift
        raw = restage_swir_lines(raw, shifts, kernel, method)
    if defective_cols is not None and len(defective_cols):  # S10 re-stamp defective columns
        cols = np.asarray(defective_cols, dtype=int)
        cols = cols[(cols >= 0) & (cols < raw.shape[1])]
        raw[:, cols] = nodata
    return np.clip(np.rint(raw), 0, dn_max).astype(np.uint16)


def column_fpn(frame: np.ndarray, smooth: int = 31) -> float:
    """High-frequency across-track fixed-pattern-noise metric: std of (column means − running mean).

    A PRNU-striped image has higher column FPN before equalization than after.
    """
    f = np.asarray(frame, dtype=np.float64)
    pos = f > 0
    count = pos.sum(axis=0)
    col = np.where(count > 0, np.where(pos, f, 0.0).sum(axis=0) / np.maximum(count, 1), np.nan)
    fill = col[np.isfinite(col)].mean() if np.isfinite(col).any() else 0.0
    col = np.where(np.isfinite(col), col, fill)
    k = max(3, min(smooth, (col.size // 2) * 2 + 1))
    pad = k // 2
    trend = np.convolve(np.pad(col, pad, mode="reflect"), np.ones(k) / k, mode="valid")
    return float(np.std((col - trend) / np.maximum(np.abs(trend), 1e-6)))

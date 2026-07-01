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
    if c.size != width:                      # align to the active frame width (centred)
        if c.size > width:
            start = (c.size - width) // 2
            c = c[start:start + width]
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
        z = y / c                                    # A,B ≈ 0 → excellent start; refine by Newton
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

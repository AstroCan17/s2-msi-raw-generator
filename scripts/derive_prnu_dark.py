#!/usr/bin/env python3
"""Derive REAL per-detector PRNU + dark from matched Sentinel-2 products.

This estimates per-detector PRNU + dark directly from the **real** products, as an alternative to the
operational GIPP path (`s2_msi_raw_generator.gipp` / `BandADF.from_gipp`) when only L1A/L1B products are at hand:

* **PRNU relative response** — per-detector-column relative gain, from a L1A (deNUCed DN) or
  L1B granule: normalise each column's robust mean by the cross-track running mean, isolating the
  residual column-to-column streaking that the on-ground equalization did not remove. This is the
  residual PRNU the E2ES re-impresses in S7.
* **Dark** — per-detector dark offset from the lowest-signal lines (low percentile per column),
  matching the L1 ATBD dark-signal definition (S2-PDGS-MPC-ATBD-L1 §4.1.1.2.1: images with the
  lowest possible signal). Use a dark-calibration / night granule for best results.

Output: an ``.npz`` with arrays ``prnu_gain`` and ``dark_dn`` keyed ``{det:02d}_{band}``, consumed
by :meth:`s2_msi_raw_generator.adf.BandADF.from_product`.

Run where the products live (e.g. the T7 archive), with the ``read`` extra (``zarr``):

    python scripts/derive_prnu_dark.py \
        --l1a /media/.../S02MSIL1A_20240403...zarr.zip \
        --bands B02 B03 B04 B08 B11 B12 --detectors 1-12 \
        --out real_prnu_dark.npz
"""

from __future__ import annotations

import argparse

import numpy as np

from s2_msi_raw_generator import io, sensor


def _parse_detectors(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def derive_column_prnu(frame: np.ndarray, smooth: int = 33) -> np.ndarray:
    """Per-detector-column relative response from a granule (robust, DC-normalised to 1.0).

    Each column's median (over lines) divided by a cross-track running mean of those medians, so a
    flat scene → all ones; residual fixed-pattern streaking → the  PRNU relative response.
    """
    col_med = np.median(np.asarray(frame, dtype=np.float64), axis=0)
    col_med = np.where(col_med > 0, col_med, np.nan)
    n = col_med.size
    k = max(3, min(smooth, n // 2 * 2 + 1))
    pad = k // 2
    padded = np.pad(col_med, pad, mode="reflect")
    trend = np.array([np.nanmean(padded[i:i + k]) for i in range(n)])
    rel = col_med / trend
    rel[~np.isfinite(rel)] = 1.0
    return rel / np.nanmedian(rel)  # DC gain 1


def derive_column_dark(frame: np.ndarray, pct: float = 1.0) -> np.ndarray:
    """Per-detector dark offset = low percentile per column (DN of the darkest lines)."""
    return np.percentile(np.asarray(frame, dtype=np.float64), pct, axis=0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--l1a", required=True, help=" L1A/L1B .zarr(.zip) for PRNU (bright scene)")
    ap.add_argument("--dark", help=" DARK-calibration granule (.zarr/.zip) — night/ocean, CSM "
                    "closed (L1 ATBD §4.1.1.2.1). REQUIRED for a dark; a daytime scene floor is "
                    "NOT a dark signal and is never used as one.")
    ap.add_argument("--bands", nargs="+", default=list(sensor.BANDS))
    ap.add_argument("--detectors", default="1-12")
    ap.add_argument("--lines", type=int, default=2048, help="along-track lines to read")
    ap.add_argument("--out", default="real_prnu_dark.npz")
    args = ap.parse_args()

    detectors = _parse_detectors(args.detectors)
    sl = slice(0, args.lines)
    tables: dict[str, np.ndarray] = {}

    for det in detectors:
        for bn in args.bands:
            try:
                frame = io.read_l1b_band(args.l1a, det, bn, lines=sl)
            except Exception as exc:  # noqa: BLE001 - skip missing det/band gracefully
                print(f"skip d{det:02d}/{bn}: {exc}")
                continue
            prnu = derive_column_prnu(frame)
            tables[f"{det:02d}_{bn}_prnu"] = prnu
            msg = f"d{det:02d}/{bn}: prnu σ={prnu.std():.4f}"
            if args.dark: # only from a dark-calibration granule
                try:
                    dark_frame = io.read_l1b_band(args.dark, det, bn, lines=sl)
                    dark = derive_column_dark(dark_frame)
                    tables[f"{det:02d}_{bn}_dark"] = dark
                    msg += f" dark μ={dark.mean():.2f} DN"
                except Exception as exc:  # noqa: BLE001
                    msg += f" (no dark: {exc})"
            print(msg)

    np.savez_compressed(args.out, **tables)
    has_dark = any(k.endswith("_dark") for k in tables)
    print(f"wrote {args.out} ({len(tables)} arrays from products; "
          f"dark={'real' if has_dark else 'NOT derived — pass a --dark granule'})")


if __name__ == "__main__":
    main()

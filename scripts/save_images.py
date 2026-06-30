#!/usr/bin/env python3
"""Save viewable images of the reverse-E2ES outputs on a real L1A, with the real GIPP.

For one band/detector it writes, for each stage, **two** files:
  * a **bit-exact** ``.npy`` (lossless — raw uint16, corrected/residual float32);
  * a **uint8 PNG** for the eye, min-max normalised ``((x − x.min())/(x.max() − x.min())·255)``.

Stages: the real L1A **raw** ``X``; the **forward-corrected** L1B ``Y = G(X − D)``; the round-trip
**residual** ``X′ − X`` (≈ 0 ⇒ near-black, proving the exact inverse); and the synthetic calibration
**dark** + **diffuser** acquisitions from the calibration sub-set.

    python scripts/save_images.py <L1A.zarr> <GIPP_dir> [band] [--detector N] [--lines N] [--out DIR]
"""

from __future__ import annotations

import argparse
import os

import numpy as np

from s2_e2es import adf, calibration as cal, gipp, io, sensor
from s2_e2es import forward_radiometric_atbd as fwd


def _norm_u8(x: np.ndarray) -> np.ndarray:
    """Min-max normalise to uint8: ((x − min)/(max − min))·255, robust to a flat array."""
    x = np.asarray(x, dtype=np.float64)
    lo, hi = np.nanmin(x), np.nanmax(x)
    if hi <= lo:
        return np.zeros(x.shape, dtype=np.uint8)
    return (((x - lo) / (hi - lo)) * 255.0).clip(0, 255).astype(np.uint8)


def _save_png(u8: np.ndarray, path: str) -> bool:
    """Write a grayscale PNG via PIL → imageio → matplotlib (whichever is installed)."""
    try:
        from PIL import Image
        Image.fromarray(u8, mode="L").save(path)
        return True
    except Exception:
        pass
    try:
        import imageio.v3 as iio
        iio.imwrite(path, u8)
        return True
    except Exception:
        pass
    try:
        import matplotlib.image as mpimg
        mpimg.imsave(path, u8, cmap="gray", vmin=0, vmax=255)
        return True
    except Exception:
        return False


def _dump(name: str, arr: np.ndarray, out: str, *, exact_dtype) -> None:
    np.save(os.path.join(out, f"{name}.npy"), np.asarray(arr, dtype=exact_dtype))  # bit-exact
    ok = _save_png(_norm_u8(arr), os.path.join(out, f"{name}.png"))               # viewable u8
    rng = f"min/mean/max={np.nanmin(arr):.1f}/{np.nanmean(arr):.1f}/{np.nanmax(arr):.1f}"
    print(f"  {name:28} {str(arr.shape):14} {rng}  png={'ok' if ok else 'FAILED'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("l1a")
    ap.add_argument("gipp")
    ap.add_argument("band", nargs="?", default="B03")
    ap.add_argument("--detector", type=int, default=1)
    ap.add_argument("--lines", type=int, default=1024)
    ap.add_argument("--out", default="images")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    b, det = sensor.band(args.band), args.detector
    gs = gipp.load_gipp_set(args.gipp, bands=(args.band,))
    eq = gs.band(args.band).detectors[det]
    pfx = f"{args.band}_d{det:02d}"

    print(f"L1A round-trip images — {args.band} d{det:02d}  (real GIPP)")
    x = io.read_l1a_raw(args.l1a, det, args.band, lines=slice(0, args.lines))
    y = fwd.forward_correct(x, eq)             # L1A raw → L1B corrected (dark + equalisation)
    x_back = fwd.reverse_impress(y, eq)        # L1B → L1A' (our reverse, same GIPP)
    valid = (x > 0) & (x < 32768)
    rmse = float(np.sqrt(np.mean((x_back[valid] - x[valid]) ** 2)))

    _dump(f"{pfx}_1_raw_L1A", x, args.out, exact_dtype=np.uint16)
    _dump(f"{pfx}_2_corrected_L1B", y, args.out, exact_dtype=np.float32)
    _dump(f"{pfx}_3_roundtrip_residual", x_back - x, args.out, exact_dtype=np.float32)
    print(f"  round-trip RMSE on real DN = {rmse:.2e}  (residual image ≈ black ⇒ exact inverse)")

    # synthetic calibration acquisitions (calibration sub-set)
    a = adf.BandADF.from_gipp(b, det, gs, active_width=x.shape[1])
    rng = np.random.default_rng(0)
    _dump(f"{pfx}_4_calib_dark", cal.synth_dark_acquisition(a, args.lines, rng), args.out,
          exact_dtype=np.uint16)
    _dump(f"{pfx}_5_calib_diffuser",
          cal.synth_diffuser_acquisition(a, 1.5 * b.lref, args.lines, rng), args.out,
          exact_dtype=np.uint16)

    print(f"\nWrote .npy (bit-exact) + .png (uint8 view) to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Demo: run the MVP reverse chain on a REAL Sentinel-2 L1B granule.

Reads a detector/band radiance window from the EOPF L1B product, runs the radiometric
reverse → synthetic L0 DN, and checks the radiometric round-trip (reverse → forward) recovers
the input radiance. NOTE: this uses the package's own algebraic forward as the inverse, so it is
a *self-consistency* check (not the independent msi-processor V&V, which needs the pinned wheel).

Usage:
    python scripts/demo_reverse_real.py [L1B.zarr.zip] [detector] [band]
"""

from __future__ import annotations

import sys

import numpy as np

from s2_msi_raw_generator import adf, io, reverse, sensor

DEFAULT_L1B = (
    "/media/cando/T7/01_cdk/59_gitlab_repos/Copernicus/raw-data-gen/data/"
    "s2_dataset/S02MSIL1B_20240403T000000_0001_A123_T000.zarr.zip"
)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_L1B
    detector = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    band_name = sys.argv[3] if len(sys.argv) > 3 else "B03"

    b = sensor.band(band_name)
    radiance = io.read_l1b_band(path, detector, band_name, lines=slice(0, 512))
    n_lines, n_det = radiance.shape
    plat = io.read_platform(path)

    print(f"Real L1B  : {path.split('/')[-1]}")
    print(f"Platform  : {plat}   band={band_name}  detector=d{detector:02d}")
    print(f"Radiance  : shape={radiance.shape}  min/mean/max="
          f"{radiance.min():.1f}/{radiance.mean():.1f}/{radiance.max():.1f}  (W·m⁻²·sr⁻¹·µm⁻¹)")
    print(f"Gain      : physical_gain={b.physical_gain}  (real, Annex A.11)   TDI={b.has_tdi}")

    a = adf.synthesize(b, n_det=n_det, seed=2026)
    print(f"ADF (synth): noise a={a.noise_a:.4g} b={a.noise_b:.4g} | "
          f"PSF {a.psf.shape} sum={a.psf.sum():.3f} | PRNU std={a.prnu_gain.std():.4f}")

    rng = np.random.default_rng(0)
    l0 = reverse.reverse_mvp(radiance, a, rng)
    sat = int((l0 >= sensor.DN_MAX).sum())
    print(f"L0 RAW DN : dtype={l0.dtype}  min/mean/max={l0.min()}/{l0.mean():.1f}/{l0.max()}  "
          f"saturated={sat}/{l0.size}")

    # radiometric self-consistency (no PSF/noise/quant): exact recovery
    dn_rad = reverse.reverse_radiometric(radiance, a)
    rec = reverse.forward_radiometric(dn_rad, a)
    rmse = float(np.sqrt(np.mean((rec - radiance) ** 2)))
    print(f"Round-trip: radiometric RMSE={rmse:.3e}  (algebraic self-consistency → ~0)")

    # full MVP self round-trip (with noise+quant): mean radiance recovered
    rec_full = reverse.forward_radiometric(l0.astype(np.float64), a)
    bias = float(np.mean(rec_full - radiance))
    print(f"Full MVP  : mean-radiance bias={bias:+.3f}  ({100*bias/radiance.mean():+.2f} %)  "
          f"[incl. PSF blur + noise + 12-bit quant]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render the single-band stage-by-stage README "Result" figures + quality metrics.

For one band/detector of a real Sentinel-2 L1B product, runs the reverse chain step by
step and writes three stage images (plus the impressed-noise delta) and a markdown
metrics table:

    original (ideal DN, S1)  ->  instrument effects impressed (S6/S7/S13/S11/S12)
                             ->  generated RAW L0 DN (S14, uint16)

Images are pseudo-grayscale PNGs via the stdlib quicklook encoder; each image is
percentile-stretched independently (2-98 %), so the *texture* differences (PSF blur,
PRNU striping, noise speckle) are what changes between panels, not the display range.

Usage:
    python scripts/result_band_stages.py [L1B.zarr[.zip]] [--band B04] [--detector 4]
        [--lines 650] [--gipp DIR] [--seed 0] [--out docs/_static/showcase]

Dependencies: numpy + zarr only (runs in the repo .venv). With --gipp the per-pixel
dark/relative-response come from the real operational GIPP; without it the PSF, SRF
and noise model are still real (packaged ESA data) while dark/PRNU/equalization are
the physically-plausible synthetic fallback (stated in the emitted caption line).
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from s2_msi_raw_generator import adf, io, quicklook, reverse, sensor  # noqa: E402

DEFAULT_L1B = (
    "/media/cando/T7/01_cdk/59_gitlab_repos/Copernicus/raw-data-gen/data/"
    "s2_dataset/S02MSIL1B_20240403T000000_0001_A123_T000.zarr.zip"
)


def _entropy_bits(a: np.ndarray) -> float:
    """First-order Shannon entropy (bits/px) of an integer-quantized array."""
    v = np.round(np.asarray(a, dtype=np.float64)).astype(np.int64).ravel()
    v -= v.min()
    counts = np.bincount(v)
    p = counts[counts > 0] / v.size
    return float(-(p * np.log2(p)).sum())


def _snr_db(a: np.ndarray) -> float:
    s = float(np.std(a))
    return float("inf") if s == 0 else 20.0 * float(np.log10(np.mean(a) / s))


def _save_gray(a: np.ndarray, path: str) -> str:
    return quicklook.save_rgb({"r": a, "g": a, "b": a}, path, rgb=("r", "g", "b"))


def _row(name: str, a: np.ndarray) -> str:
    return (
        f"| {name} | {a.min():.1f} | {a.max():.1f} | {a.mean():.1f} | "
        f"{a.std():.2f} | {_snr_db(a):.1f} | {_entropy_bits(a):.2f} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("l1b", nargs="?", default=DEFAULT_L1B)
    ap.add_argument("--band", default="B04")
    ap.add_argument("--detector", type=int, default=7)
    ap.add_argument("--line-start", type=int, default=8450)
    ap.add_argument("--lines", type=int, default=650)
    ap.add_argument("--gipp", default=os.environ.get("S2_E2ES_GIPP_DIR"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--zoom-line", type=int, default=0)
    ap.add_argument("--zoom-col", type=int, default=0)
    ap.add_argument("--zoom-size", type=int, default=256)
    ap.add_argument("--out", default="docs/_static/showcase")
    args = ap.parse_args()

    b = sensor.band(args.band)
    radiance = io.read_l1b_band(args.l1b, args.detector, args.band,
                            lines=slice(args.line_start, args.line_start + args.lines))
    n_lines, n_det = radiance.shape

    if args.gipp:
        from s2_msi_raw_generator import gipp as gipp_mod
        gs = gipp_mod.load_gipp_set(args.gipp)
        a = adf.BandADF.from_gipp(b, args.detector, gs, active_width=n_det)
        adf_kind = "real operational GIPP (per-pixel dark + relative response)"
    else:
        a = adf.synthesize(b, n_det=n_det, seed=2026)
        adf_kind = ("real PSF/SRF/noise model; synthetic-fallback dark/PRNU/equalization "
                    "(no GIPP dir supplied)")

    rng = np.random.default_rng(args.seed)

    # Stage captures (reverse_mvp order: S1 -> S6 -> S7 -> S13 -> S11 -> S12 -> S14).
    x_ideal = reverse.s1_radiance_to_dn(radiance, a.band.cal_gain)
    x = reverse.s6_psf_reblur(x_ideal, a.psf)
    x_blur = x
    x = reverse.s7_impress_relative_response(x, a.prnu_gain)
    x_nonoise = reverse.s12_reapply_onboard_eq(
        reverse.s11_reapply_dark(x, a.dark_dn), a.eq_gain, a.eq_offset)
    x = reverse.s13_add_noise(x, a.noise_a, a.noise_b, rng)
    x = reverse.s11_reapply_dark(x, a.dark_dn)
    x_fx = reverse.s12_reapply_onboard_eq(x, a.eq_gain, a.eq_offset)
    x_raw = reverse.s14_quantize(x_fx)
    noise_delta = x_fx - x_nonoise

    os.makedirs(args.out, exist_ok=True)
    tag = args.band.lower()
    paths = {
        "original": _save_gray(x_ideal, os.path.join(args.out, f"result_{tag}_original.png")),
        "effects": _save_gray(x_fx, os.path.join(args.out, f"result_{tag}_effects.png")),
        "raw": _save_gray(np.asarray(x_raw, dtype=np.float64),
                          os.path.join(args.out, f"result_{tag}_raw.png")),
        "delta": _save_gray(noise_delta, os.path.join(args.out, f"result_{tag}_delta.png")),
    }
    # Zoomed crops (cloud edge) where the per-stage texture differences are visible.
    cy, cx, cs = args.zoom_line, args.zoom_col, args.zoom_size
    for name, arr in (("original", x_ideal), ("effects", x_fx),
                      ("raw", np.asarray(x_raw, dtype=np.float64))):
        crop = arr[cy:cy + cs, cx:cx + cs]
        p = os.path.join(args.out, f"result_{tag}_{name}_zoom.png")
        paths[f"{name}_zoom"] = quicklook.save_rgb(
            {"r": crop, "g": crop, "b": crop}, p, rgb=("r", "g", "b"), upscale=2)

    # Quality metrics.
    sigma_measured = float(np.std(noise_delta / a.eq_gain[np.newaxis, :]))
    dn_signal = reverse.s7_impress_relative_response(x_blur, a.prnu_gain)
    sigma_model = float(np.mean(np.sqrt(a.noise_a**2 + a.noise_b * np.clip(dn_signal, 0, None))))
    unsat = (x_fx >= 0.0) & (x_fx <= float(sensor.DN_MAX))
    sat_frac = float(1.0 - unsat.mean())
    q_err = (np.asarray(x_raw, dtype=np.float64) - x_fx)[unsat]
    q_rmse = float(np.sqrt(np.mean(q_err ** 2)))
    rec = reverse.forward_radiometric(np.asarray(x_raw, dtype=np.float64), a)
    rt_err = (rec - radiance)[unsat]
    rt_rmse = float(np.sqrt(np.mean(rt_err ** 2)))
    rt_bias = float(np.mean(rt_err))
    peak = float(radiance[unsat].max())
    rt_psnr = 20.0 * float(np.log10(peak / rt_rmse)) if rt_rmse > 0 else float("inf")
    blur_rmse = float(np.sqrt(np.mean((x_blur - x_ideal) ** 2)))

    print(f"Input   : {os.path.basename(args.l1b)}  band={args.band} d{args.detector:02d} "
          f"lines={n_lines} cols={n_det}")
    print(f"ADFs    : {adf_kind}")
    print(f"Images  : {', '.join(os.path.basename(p) for p in paths.values())}\n")
    print("| Stage | DN min | DN max | mean | std | SNR (dB) | entropy (bits/px) |")
    print("|---|---|---|---|---|---|---|")
    print(_row("original — ideal DN (S1)", x_ideal))
    print(_row("effects impressed (S6–S13)", x_fx))
    print(_row("RAW L0 DN (S14, uint16)", np.asarray(x_raw, dtype=np.float64)))
    print()
    print("| Quality figure | Value |")
    print("|---|---|")
    print(f"| PSF re-blur RMSE vs ideal DN (S6) | {blur_rmse:.2f} DN |")
    print(f"| impressed noise σ (measured, signal DN) | {sigma_measured:.2f} DN |")
    print(f"| noise-model σ = √(α²+β·DN) (expected) | {sigma_model:.2f} DN "
          f"({100 * (sigma_measured / sigma_model - 1):+.1f} %) |")
    print(f"| saturated px clipped by S14 (DN > {sensor.DN_MAX}) | {100 * sat_frac:.2f} % |")
    print(f"| quantization RMSE, unsaturated px (expected ≈ 1/√12 ≈ 0.29) | {q_rmse:.2f} DN |")
    print(f"| full-chain radiance recovery RMSE, unsaturated px | {rt_rmse:.2f} "
          f"(PSNR {rt_psnr:.1f} dB) |")
    print(f"| full-chain mean-radiance bias, unsaturated px | {rt_bias:+.3f} "
          f"({100 * rt_bias / radiance[unsat].mean():+.2f} %) |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

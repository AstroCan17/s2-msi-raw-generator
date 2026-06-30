#!/usr/bin/env python3
"""Round-trip V&V on a REAL Sentinel-2 L1A product with the REAL operational GIPP.

For each band/detector: read the real L1A raw counts, run our ATBD forward radiometric correction
(dark subtract + relative-response equalization, real GIPP coefficients) → L1B, then our reverse
(impress) → L1A′, and report the per-band round-trip RMSE (real-DN inverse exactness) plus the
fixed-pattern-noise (FPN) reduction the equalization achieves.

Uses only our own code + the public-ATBD model + the GIPP **data**; no external processor.

    python scripts/roundtrip_real_l1a.py <PDI_MSI_S2_L1A.zarr> <GIPP_dir> [band ...] [--detector N]
"""

from __future__ import annotations

import argparse

import numpy as np

from s2_e2es import forward_radiometric_atbd as fwd
from s2_e2es import gipp, io, sensor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("l1a", help="real L1A .zarr(.zip) (measurements/DDnn/Bxx/l1a_raw_image)")
    ap.add_argument("gipp", help="real GIPP directory (S2A_OPER_GIP_*.xml)")
    ap.add_argument("bands", nargs="*", default=["B02", "B03", "B04", "B08", "B11", "B12"])
    ap.add_argument("--detector", type=int, default=1)
    ap.add_argument("--lines", type=int, default=2048)
    args = ap.parse_args()

    gs = gipp.load_gipp_set(args.gipp, bands=tuple(args.bands))
    det, sl = args.detector, slice(0, args.lines)
    print(f"Real L1A round-trip V&V (detector d{det:02d}) — real GIPP {args.gipp.split('/')[-1]}")
    print(f"{'band':5}{'model':10}{'valid%':>7}{'RMSE(DN)':>12}{'FPN raw':>10}{'FPN corr':>10}{'FPN drop':>10}")
    for b in args.bands:
        eq = gs.band(b).detectors[det]
        try:
            x = io.read_l1a_raw(args.l1a, det, b, lines=sl)
        except Exception as exc:  # noqa: BLE001
            print(f"{b:5}skip: {exc}")
            continue
        valid = (x > 0) & (x < 32768)
        y = fwd.forward_correct(x, eq)
        xp = fwd.reverse_impress(y, eq)
        rmse = float(np.sqrt(np.mean((xp[valid] - x[valid]) ** 2)))
        f_raw, f_cor = fwd.column_fpn(x), fwd.column_fpn(y)
        drop = 100 * (f_cor - f_raw) / f_raw if f_raw else 0.0
        print(f"{b:5}{eq.model:10}{valid.mean()*100:6.0f}%{rmse:12.2e}{f_raw:10.4f}{f_cor:10.4f}{drop:9.0f}%")
    print("\nRMSE≈0 ⇒ our forward and reverse are exact inverses on real L1A DN, with the real GIPP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

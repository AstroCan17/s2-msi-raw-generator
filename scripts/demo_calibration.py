#!/usr/bin/env python3
"""Demo: the S2 radiometric calibration sub-set (CSM sun-diffuser + dark → derived coefficients).

Impresses the true ADF to synthesise a dark + a sun-diffuser L0 acquisition, then derives the dark
``D``, the relative response ``g`` and the absolute coefficient ``A`` back from them (L1 ATBD
§4.1.1.2.2) — the *estimated* calibration a processor would apply, vs. the truth. The small residual
is the inverse-crime cure.

    python scripts/demo_calibration.py [GIPP_dir] # GIPP ADF if given, else synthetic
"""

from __future__ import annotations

import sys

import numpy as np

from s2_msi_raw_generator import adf, calibration as cal, sensor


def main() -> int:
    gipp_dir = sys.argv[1] if len(sys.argv) > 1 else None
    gs = None
    if gipp_dir:
        from s2_msi_raw_generator import gipp
        gs = gipp.load_gipp_set(gipp_dir)
        print(f"ADF source: operational GIPP ({gipp_dir.split('/')[-1]})")
    else:
        print("ADF source: synthetic (pass a GIPP dir for per-pixel coefficients)")

    print(f"{'band':5}{'Ldiff':>7}{'dark truth':>11}{'dark est':>10}{'dark err':>9}"
          f"{'g corr':>8}{'A (≈cal_gain)':>15}")
    for bn in ("B02", "B03", "B04", "B08", "B11", "B12"):
        b = sensor.band(bn)
        a = (adf.BandADF.from_gipp(b, 1, gs, active_width=400) if gs
             else adf.synthesize(b, n_det=400, seed=11))
        c = cal.calibrate(a, n_dark=256, n_diffuser=256, seed=1)
        truth_g = a.prnu_gain / a.prnu_gain.mean()
        corr = float(np.corrcoef(c.relative_response, truth_g)[0, 1])
        print(f"{bn:5}{c.l_diff:7.1f}{a.dark_dn.mean():11.2f}{c.dark.mean():10.2f}"
              f"{(c.dark - a.dark_dn).std():9.3f}{corr:8.4f}{c.abs_coeff:12.3f}  (cg={b.cal_gain:.1f})")
    print("\nDerived ≈ truth ⇒ the calibration sub-set closes the loop; the small residual is the real"
          "\ncalibration uncertainty a processor inherits (inverse-crime cure).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

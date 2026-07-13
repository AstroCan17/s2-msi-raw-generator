#!/usr/bin/env python3
"""Validate the ESA-only NUC (EOPF ``ADF_REQOG``) on an **ESA SAFE** L1B granule.

This closes the objective-measurement loop for the ESA-only correction goal (issue #1): it takes a
genuine ESA L1B band image (JPEG-2000) straight out of a SAFE ``.tar`` (nested granule tars are
handled), re-impresses the non-uniformity with the ESA ``R2EQOG`` per-pixel dark + PRNU
(:func:`forward_radiometric_atbd.reverse_impress`) to synthesise the raw L1A, then forward-corrects it
back (:func:`forward_radiometric_atbd.forward_correct`) and reports:

* **round-trip RMSE** — how well the ESA equalization model inverts on L1B pixels (self-consistency);
* **column-FPN before/after** — the synthetic raw must show more across-track fixed-pattern (PRNU
  stripes) than the corrected L1B, proving the ESA per-pixel structure was actually impressed;
* **temporal validity** — the ADF applicability epoch vs the acquisition sensing date.

No synthetic/derived calibration is used — the NUC comes entirely from the ESA ADF.

Run on the Studio VM (where the SAFE product + ADF live), from a checkout of this branch::

    python scripts/validate_esa_nuc.py --band B03 --detector 1

Env/args override the VM defaults below.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tarfile

import numpy as np

from s2_msi_raw_generator import forward_radiometric_atbd as fwd, gipp

_VM_L1B = ""
_VM_ADF = ""


def _default_eqog_adf() -> str | None:
    from s2_msi_raw_generator import env as s2env

    s2env.load_dotenv()
    p = os.environ.get("S2_EQOG_ADF")
    if p and os.path.exists(p):
        return p
    return s2env.find_adf_eopf("REQOG")


def _jp2_suffix(band: str) -> str:
    return f"_{band.upper()}.jp2"


def _find_granule_jp2(l1b_tar: str, detector: int, band: str) -> tuple[bytes, str]:
    """Return (jp2 bytes, granule name) for one detector+band from a (possibly nested) SAFE L1B tar."""
    det_tag = f"_D{detector:02d}_"
    jp2_tag = _jp2_suffix(band)
    with tarfile.open(l1b_tar) as outer:
        # direct jp2 (flat SAFE) or nested per-detector granule tars
        direct = [m for m in outer.getmembers()
                  if m.isfile() and det_tag in m.name and m.name.endswith(jp2_tag)]
        if direct:
            return outer.extractfile(direct[0]).read(), direct[0].name
        granules = [m for m in outer.getmembers()
                    if m.isfile() and det_tag in m.name and m.name.endswith(".tar")]
        if not granules:
            raise FileNotFoundError(f"no D{detector:02d} granule in {l1b_tar}")
        with tarfile.open(fileobj=io.BytesIO(outer.extractfile(granules[0]).read())) as inner:
            jp2 = [m for m in inner.getmembers() if m.isfile() and m.name.endswith(jp2_tag)]
            if not jp2:
                raise FileNotFoundError(f"no {band} jp2 in granule {granules[0].name}")
            return inner.extractfile(jp2[0]).read(), granules[0].name


def _decode_jp2(data: bytes) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        sys.exit("Pillow (with OpenJPEG) is required to decode the L1B jp2.")
    img = Image.open(io.BytesIO(data))
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"unexpected jp2 shape {arr.shape}")
    return arr


def _sensing_from_granule(name: str) -> str | None:
    m = re.search(r"_S(\d{8}T\d{6})", name)
    return gipp._iso(m.group(1)) if m else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--l1b-tar", default=os.environ.get("S2_VAL_L1B") or None)
    ap.add_argument("--adf", default=os.environ.get("S2_EQOG_ADF") or _default_eqog_adf())
    ap.add_argument("--band", default="B03")
    ap.add_argument("--detector", type=int, default=1)
    ap.add_argument("--lines", type=int, default=2048, help="along-track window (0 = full)")
    ap.add_argument("--acq-date", default=None, help="acquisition UTC; else parsed from granule name")
    ap.add_argument("--json", default=None, help="write the metrics to this json path")
    args = ap.parse_args()

    for label, path in (("L1B tar", args.l1b_tar), ("ADF", args.adf)):
        if not path or not os.path.exists(path):
            sys.exit(f"{label} not found: {path!r} — set --l1b-tar / --adf or S2_VAL_L1B / S2_EQOG_ADF")

    print(f"L1B : {args.l1b_tar}")
    print(f"ADF : {args.adf}")
    print(f"band {args.band}  detector {args.detector}\n")

    data, granule = _find_granule_jp2(args.l1b_tar, args.detector, args.band)
    y = _decode_jp2(data)
    if args.lines:
        y = y[: args.lines]
    valid = y > 0
    print(f"granule: {granule}")
    print(f"L1B image: shape={y.shape} mean={y[valid].mean():.1f} std={y[valid].std():.1f}")

    eq = gipp.read_r2eqog_eopf(args.adf, args.band).detectors[args.detector]
    print(f"ESA R2EQOG: model={eq.model} act_px={eq.dark.size} "
          f"dark_mean={eq.dark.mean():.1f} rel_gain[:3]={np.round(eq.rel_gain[:3], 4)}\n")

    # reverse (E2ES): corrected L1B -> synthetic raw L1A, then forward-correct back
    x_syn = fwd.reverse_impress(y, eq)
    y_rt = fwd.forward_correct(x_syn, eq)

    rmse = float(np.sqrt(np.mean((y_rt[valid] - y[valid]) ** 2)))
    rel = rmse / float(y[valid].mean()) if valid.any() else float("nan")
    fpn_corr = float(fwd.column_fpn(y))
    fpn_raw = float(fwd.column_fpn(x_syn))

    print("=== ESA-NUC round-trip (S2 L1B pixels) ===")
    print(f"round-trip RMSE     : {rmse:.4f} DN  ({100 * rel:.4f} % of mean)")
    print(f"column FPN  L1B/raw : {fpn_corr:.4f} -> {fpn_raw:.4f}  "
          f"({'PRNU impressed OK' if fpn_raw > fpn_corr else 'no FPN increase (check ADF/band)'})")
    print(f"synthetic raw       : mean={x_syn[valid].mean():.1f} std={x_syn[valid].std():.1f}")

    acq = args.acq_date or _sensing_from_granule(granule)
    tv = None
    if acq:
        epoch = gipp.parse_eqog_adf_epoch(args.adf)
        if epoch:
            tv = gipp.temporal_validity(epoch, acq)
            print(f"\n=== temporal validity ===\n{'WARNING — ' if tv['warn'] else ''}{tv['message']}")

    if args.json:
        out = {
            "l1b_tar": args.l1b_tar, "adf": args.adf, "granule": granule,
            "band": args.band, "detector": args.detector,
            "roundtrip_rmse_dn": rmse, "roundtrip_rmse_pct": 100 * rel,
            "column_fpn_l1b": fpn_corr, "column_fpn_raw": fpn_raw,
            "nuc_source": "ESA EOPF ADF_REQOG", "temporal_validity": tv,
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()

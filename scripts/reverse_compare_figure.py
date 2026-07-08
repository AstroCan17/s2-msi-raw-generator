#!/usr/bin/env python3
"""Generate the reverse-ladder validation figure + per-band table (all 13 bands).

Compares the synthetic **L1A** raw counts (``reverse-l1b`` output) against the **original S2B L0 `img`**
for the 2024-04-08 S2B PPB datatake, framing-aligned (ADF_PRDLO ``begin_nb_lines_to_cut`` from the L1B
metadata) with a small cross-correlation refinement for the ~28-line legacy datation drift — the exact
method of ``notebooks/reverse_l1b_compare.ipynb``, extended to every band.

Env: ``S2_E2ES_L1B`` (real L1B), ``S2_E2ES_GIPP_DIR`` + ``S2_E2ES_EQOG_ADF`` (blind columns), the
synthetic L1A dir (``S2_DATA_STORE/l1a`` or ``$S2_E2ES_L1A_DIR``), ``S2_E2ES_REAL_L0`` (real L0 TC7D).
Writes ``reverse_l1b_allbands.png`` + ``reverse_l1b_allbands.json`` to the CWD (or ``$OUT_DIR``).
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import zarr  # noqa: E402

from s2_msi_raw_generator import forward_radiometric_atbd as fwd, gipp, io as gio  # noqa: E402

DET = int(os.environ.get("S2_E2ES_L1B_DETECTORS", "5").split(",")[0])
BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"]
OUT = Path(os.environ.get("OUT_DIR", "."))


def _syn_l1a() -> str:
    d = os.environ.get("S2_E2ES_L1A_DIR")
    if not d:
        base = os.environ.get("S2_DATA_STORE") or os.path.expanduser("~/scratch/ladder2")
        d = os.path.join(base, "l1a")
    hits = sorted(glob.glob(os.path.join(d, "S02MSIL1A__*_reverse.zarr")))
    if not hits:
        raise SystemExit(f"no synthetic L1A under {d}")
    return hits[-1]


def _framing(l1b_path: str) -> dict:
    fr = os.path.expanduser("~/data-store/esa-source/aux/framing/framing_lines_S2B_20240408.json")
    if os.path.exists(fr):
        return json.load(open(fr))["framing"]
    fi = dict(zarr.open_group(l1b_path, mode="r").attrs)["other_metadata"]["Radiometric_Info"][
        "Framing_Information"
    ]
    return {
        b: {d: {"begin": int(fi[b][d]["begin_nb_lines_to_cut"])} for d in fi[b]} for b in fi
    }


def main() -> int:
    l1b = os.environ["S2_E2ES_L1B"]
    real = os.environ.get("S2_E2ES_REAL_L0") or (
        os.path.dirname(l1b) + "/S02MSIL0__20240408T053621_0566_B105_TC7D.zarr"
    )
    syn_l1a = _syn_l1a()
    gs = gipp.load_gipp_set(os.environ["S2_E2ES_GIPP_DIR"], eqog_adf=os.environ.get("S2_E2ES_EQOG_ADF"))
    g_real = zarr.open_group(real, mode="r")
    fr = _framing(l1b)

    def framing_begin(band):
        return int(fr[band.lower()][f"d{DET:02d}"]["begin"])

    def load_pair(band, n_lines=4096, margin=40):
        syn = gio.read_l1a_raw(syn_l1a, DET, band, dtype=np.uint16).astype(np.float64)
        h, w = syn.shape
        off = framing_begin(band)
        lo = max(0, off - margin)
        base = off - lo
        real_big = np.asarray(
            g_real[f"measurements/d{DET:02d}/{band.lower()}/img"][lo : off + h + margin, :w], np.float64
        )
        blind = gs.blind.get(band, {}).get(DET)
        if blind is not None and len(blind) and max(blind) < w and (w - len(blind)) > 0:
            keep = np.setdiff1d(np.arange(w), np.asarray(blind, int))
            syn, real_big = syn[:, keep], real_big[:, keep]
        drift = 0
        if real_big.shape[0] >= base + h + margin:
            y0, y1, x0, x1 = 100, min(1100, h - 1), 200, min(1200, syn.shape[1] - 1)
            p = syn[y0:y1, x0:x1]
            p = (p - p.mean()) / (p.std() + 1e-9)

            def cc(d):
                r = real_big[base + d + y0 : base + d + y1, x0:x1]
                if r.shape != p.shape:
                    return -9.0
                r = (r - r.mean()) / (r.std() + 1e-9)
                return float((p * r).mean())

            drift = max(range(-margin, margin + 1), key=cc)
        realb = real_big[base + drift : base + drift + h]
        return syn[:n_lines], realb[:n_lines], off, drift

    def stretch(a, ref):
        p1, p2 = np.percentile(ref, [2, 98])
        return np.clip((a - p1) / (p2 - p1 + 1e-9), 0, 1)

    rows = [b for b in BANDS]
    fig, ax = plt.subplots(len(rows), 3, figsize=(12, 2.5 * len(rows)))
    table = {}
    for i, bn in enumerate(rows):
        try:
            syn, realb, off, drift = load_pair(bn)
        except Exception as e:  # noqa: BLE001
            for j in range(3):
                ax[i, j].axis("off")
            ax[i, 0].set_title(f"{bn}  skip ({type(e).__name__})", fontsize=8)
            continue
        d = syn - realb
        rmse = float(np.sqrt(np.mean(d**2)))
        med_pct = 100 * (np.median(syn) - np.median(realb)) / max(np.median(realb), 1e-6)
        table[bn] = {
            "framing_off": off,
            "drift": drift,
            "syn_median": round(float(np.median(syn)), 1),
            "real_median": round(float(np.median(realb)), 1),
            "median_pct": round(med_pct, 2),
            "rmse_dn": round(rmse, 2),
            "syn_fpn": round(float(fwd.column_fpn(syn)), 3),
            "real_fpn": round(float(fwd.column_fpn(realb)), 3),
        }
        ax[i, 0].imshow(stretch(syn, realb), cmap="gray", aspect="auto")
        ax[i, 0].set_title(f"{bn} synthetic (reverse)", fontsize=8)
        ax[i, 1].imshow(stretch(realb, realb), cmap="gray", aspect="auto")
        ax[i, 1].set_title(f"{bn} original S2B L0", fontsize=8)
        lim = np.percentile(np.abs(d), 98) + 1e-6
        ax[i, 2].imshow(d, cmap="RdBu_r", aspect="auto", vmin=-lim, vmax=lim)
        ax[i, 2].set_title(f"{bn} diff  rmse={rmse:.1f} DN  off={off} drift={drift:+d}", fontsize=8)
        for a in ax[i]:
            a.axis("off")
    plt.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "reverse_l1b_allbands.png", dpi=110, bbox_inches="tight")
    (OUT / "reverse_l1b_allbands.json").write_text(json.dumps(table, indent=2) + "\n")

    print(f"{'band':4} {'off':>6} {'drift':>5} {'syn_med':>8} {'real_med':>8} {'med%':>6} {'rmse':>7}")
    for bn, r in table.items():
        print(f"{bn:4} {r['framing_off']:6d} {r['drift']:+5d} {r['syn_median']:8.1f} "
              f"{r['real_median']:8.1f} {r['median_pct']:6.1f} {r['rmse_dn']:7.1f}")
    print(f"\nfigure → {OUT / 'reverse_l1b_allbands.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

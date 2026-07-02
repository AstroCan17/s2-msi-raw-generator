#!/usr/bin/env python3
# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Real-L1A end-to-end driver: bucket L1A → packaged L0 (compressed ISPs) → L1A′ → validation.

The authoritative real-data run of the reverse E2ES (REQ-FUNC-093).  Mirrors the real chain:
the S2 L0→L1A relation is *decode/packaging* (SentiWiki: L0 stores compressed ISPs, L1A
decompresses) — so the real L1A DN ``X`` is CCSDS-122 lossless-compressed and packetized into
the canonical L0, ground-decoded back (``X′ == X`` bit-exact), written as the open-container
L0 and pushed through msi-processor ``l0_decode`` → **L1A′** (bit-identical on kept lines).
The GIPP radiometric round-trip (RMSE ~1e-14) is a separate V&V phase, not the data path.

Phases (idempotent; each persists JSON under ``<store>/report/``)::

    fetch-l1a fetch-l0 preflight package ground-decode l0-decode validate
    radiometric-vv scan-l0 quicklook report

    python scripts/run_e2e_real_l1a.py ~/validation-data/e2e-real            # all phases
    python scripts/run_e2e_real_l1a.py <store> --phases preflight,package --lines 4096

The eopf/msi_processor imports are lazy (``l0-decode``/``validate`` only), so every other
phase — and this module's import — works in the plain generator environment (CI).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from s2_msi_raw_generator import ccsds122, datation, io as gio, isp, l0product, naming, quicklook, s3fetch, sensor

ENDPOINT = "https://dpr-common.s3.sbg.io.cloud.ovh.net"
L1A_PREFIX = "s2-msi-l1-example/PDI_MSI_S2_L1A.zarr/"
# The unpacked PSD L0 SAFE mirror (incl. per-band ISP .bin files) is LISTable but its objects
# return **HTTP 403 on GET** (verified 2026-07-02) — the bucket grants read only on selected
# archives. The accessible real-L0 references are the datastrip PDI tar (metadata + QI) and the
# real **SADATA** tars, whose members are genuine downlinked CCSDS packets — exactly what the
# structural scan needs.
REAL_L0_SAFE_PREFIX = ("S2AMSIdataset/S2A_OPER_PRD_MSIL0P_PDMC_20220803T144026_"
                       "R123_V20220803T113642_20220803T113704.SAFE/")
REAL_L0_KEYS = [
    "S2AMSIdataset/S2A_OPER_MSI_L0__DS_ATOS_20221111T083024_S20221111T082158_N04.00.tar",
    "S2AMSIdataset/S2A_OPER_AUX_SADATA_2APS_20241218T042947_"
    "V20241218T034819_20241218T041652_A049565_WP_LN.tar",
    "S2AMSIdataset/S2A_OPER_AUX_SADATA_2APS_20241218T074251_"
    "V20241218T070943_20241218T072345_A049567_WP_LN.tar",
]
DETECTOR = 1                       # the example PDI L1A carries DD01 only
PHASES = ["fetch-l1a", "fetch-l0", "preflight", "package", "ground-decode", "l0-decode",
          "validate", "radiometric-vv", "scan-l0", "quicklook", "report"]

_SENTINEL_SATURATED = 32768        # IF-IN-L1A saturation sentinel in the real product


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _store_paths(store: Path) -> dict[str, Path]:
    p = {
        "inputs": store / "inputs",
        "l0": store / "l0",
        "l1a_prime": store / "l1a_prime",
        "quicklook": store / "quicklook",
        "report": store / "report",
    }
    for d in p.values():
        d.mkdir(parents=True, exist_ok=True)
    return p


def _jdump(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def _jload(path: Path) -> dict:
    return json.loads(path.read_text())


def _trailing_zero_lines(dn: np.ndarray) -> int:
    """The msi-processor line-loss rule: trailing all-zero lines after the last non-zero one."""
    nz = np.flatnonzero((dn != 0).any(axis=1))
    return dn.shape[0] if nz.size == 0 else dn.shape[0] - 1 - int(nz[-1])


def _entropy_bits(dn: np.ndarray) -> float:
    counts = np.bincount(dn.reshape(-1))
    p = counts[counts > 0] / dn.size
    return float(-(p * np.log2(p)).sum())


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------

def phase_fetch_l1a(store: dict[str, Path], args) -> None:
    dest = store["inputs"]
    man = s3fetch.fetch_prefix(ENDPOINT, L1A_PREFIX, dest / "PDI_MSI_S2_L1A.zarr",
                               strip_prefix=L1A_PREFIX, jobs=args.jobs)
    s3fetch.save_manifest(man, store["report"] / "fetch_l1a_manifest.json")
    print(f"[fetch-l1a] {man['n_objects']} objects, {man['total_bytes']/1e6:.1f} MB")


def phase_fetch_l0(store: dict[str, Path], args) -> None:
    """Fetch the accessible real-L0 references (DS + SADATA tars; the SAFE mirror is GET-403)."""
    dest = store["inputs"] / "real_l0"
    results, total = [], 0
    for key in REAL_L0_KEYS:
        try:
            man = s3fetch.fetch_prefix(ENDPOINT, key, dest, strip_prefix="S2AMSIdataset/",
                                       jobs=1)
            results.append(man)
            total += man["total_bytes"]
        except RuntimeError as exc:                        # keep going; report what failed
            results.append({"prefix": key, "error": str(exc)})
    s3fetch.save_manifest({"targets": results, "safe_prefix_status":
                           f"{REAL_L0_SAFE_PREFIX} objects return HTTP 403 on GET "
                           "(bucket policy; verified 2026-07-02)"},
                          store["report"] / "fetch_l0_manifest.json")
    print(f"[fetch-l0] {len(REAL_L0_KEYS)} real-L0 references, {total/1e6:.1f} MB → {dest}")


def _l1a_path(store: dict[str, Path], args) -> str:
    return args.l1a or os.environ.get("S2_E2ES_L1A") or str(store["inputs"] / "PDI_MSI_S2_L1A.zarr")


def phase_preflight(store: dict[str, Path], args) -> None:
    import zarr

    l1a = _l1a_path(store, args)
    attrs = dict(zarr.open_group(l1a, mode="r").attrs)
    bands = args.bands
    per_band, n_lines = {}, 0
    for bn in bands:
        dn = gio.read_l1a_raw(l1a, DETECTOR, bn, lines=args.line_slice, dtype=np.uint16)
        n_lines = max(n_lines, dn.shape[0])
        per_band[bn] = {
            "shape": list(dn.shape),
            "min": int(dn.min()), "max": int(dn.max()),
            "n_gt_4095": int((dn > sensor.DN_MAX).sum()),
            "n_sentinel_32768": int((dn == _SENTINEL_SATURATED).sum()),
            "trailing_zero_lines": _trailing_zero_lines(dn),
            "entropy_bits_px": round(_entropy_bits(dn), 3),
        }
        del dn
        print(f"[preflight] {bn}: {per_band[bn]}")
    max_dn = max(b["max"] for b in per_band.values())
    bit_depth = 12 if max_dn <= sensor.DN_MAX else 16
    line_period_s = sensor.LINE_PERIOD_MS / 1e3
    l0_name, info = naming.from_l1a_context(attrs, n_lines=n_lines,
                                            line_period_s=line_period_s,
                                            product_type="S02MSIL0_")
    l1ap_name, _ = naming.from_l1a_context(attrs, n_lines=n_lines,
                                           line_period_s=line_period_s,
                                           product_type="S02MSIL1A")
    parsed = naming.parse_psfd_name(l0_name)
    _jdump({
        "l1a_path": l1a, "bands": bands, "n_lines": n_lines, "bit_depth": bit_depth,
        "pixel_bit_depth": bit_depth, "per_band": per_band,
        "product_names": {"l0": l0_name, "l0_oc": naming.psfd_name(
            "S02MSIL0_", parsed["start_utc"], parsed["duration_s"],
            unit=parsed["unit"], relative_orbit=parsed["relative_orbit"], z_suffix="OC"),
            "l1a_prime": l1ap_name},
        "naming_fallbacks": info.get("derived_from_defaults", []),
        "start_utc": parsed["start_utc"], "relative_orbit": parsed["relative_orbit"],
        "unit": parsed["unit"],
    }, store["report"] / "preflight.json")
    print(f"[preflight] bit_depth={bit_depth} L0={l0_name}")


def _datation_from_preflight(pre: dict) -> datation.Datation:
    start = str(pre["start_utc"]).replace("+00:00", "Z")
    if "T" in start and not start.endswith("Z"):
        start += "Z"
    return datation.Datation(epoch_utc=start)


def phase_package(store: dict[str, Path], args) -> None:
    pre = _jload(store["report"] / "preflight.json")
    l1a = pre["l1a_path"]
    d = _datation_from_preflight(pre)
    frames = {(DETECTOR, bn): gio.read_l1a_raw(l1a, DETECTOR, bn, lines=args.line_slice,
                                               dtype=np.uint16)
              for bn in pre["bands"]}
    out = str(store["l0"] / pre["product_names"]["l0"])
    l0product.write_l0_product(out, frames, datation=d, with_isp=True,
                               isp_max_payload=args.max_payload,
                               store_decoded=args.store_decoded)
    del frames
    print(f"[package] canonical L0 → {out}")


def phase_ground_decode(store: dict[str, Path], args) -> None:
    pre = _jload(store["report"] / "preflight.json")
    l1a = pre["l1a_path"]
    d = _datation_from_preflight(pre)
    canon = str(store["l0"] / pre["product_names"]["l0"])
    rt = {}
    band_frames = {}
    for bn in pre["bands"]:
        rec = l0product.read_l0_isp_dn(canon, DETECTOR, bn)
        orig = gio.read_l1a_raw(l1a, DETECTOR, bn, lines=args.line_slice, dtype=np.uint16)
        ok = bool(np.array_equal(rec, orig))
        rt[bn] = {"bit_exact": ok}
        if not ok:
            raise SystemExit(f"[ground-decode] {bn}: reconstructed DN != original — codec fault")
        band_frames[bn] = rec
        del orig
        print(f"[ground-decode] {bn}: bit-exact OK")
    # compression accounting from the canonical product's attrs
    import zarr
    g = zarr.open_group(canon, mode="r")
    for bn in pre["bands"]:
        mg = g[f"measurements/d{DETECTOR:02d}/{sensor.zarr_band_key(bn)}"]
        rt[bn].update(dict(mg.attrs)["compression"])
        rt[bn]["n_packets"] = dict(mg.attrs)["n_packets"]
    _jdump(rt, store["report"] / "ground_decode.json")
    # the real-chain order: the open container is written from the RECONSTRUCTED DN
    oc = str(store["l0"] / pre["product_names"]["l0_oc"])
    l0product.write_l0_opencontainer(oc, band_frames, datation=d)
    print(f"[ground-decode] open-container L0 → {oc}")


def phase_l0_decode(store: dict[str, Path], args) -> None:
    import zarr
    from eopf.common.constants import OpeningMode
    from eopf.product import EOProduct, EOVariable
    from eopf.store.zarr import EOZarrStore
    from msi_processor.computing.l0_decode.unit import L0DecodeUnit

    pre = _jload(store["report"] / "preflight.json")
    oc = str(store["l0"] / pre["product_names"]["l0_oc"])
    g = zarr.open_group(oc, mode="r")
    bands = sorted(g["measurements/detector"].array_keys())
    groups = [bands[i::args.band_groups] for i in range(args.band_groups)] \
        if args.band_groups > 1 else [bands]
    outdir = store["l1a_prime"]
    stem = pre["product_names"]["l1a_prime"].removesuffix(".zarr")
    lost = {}
    for gi, grp in enumerate(g_ for g_ in groups if g_):
        prod = EOProduct(f"{stem}.g{gi}")
        for b in grp:
            prod[f"measurements/detector/{b}"] = EOVariable(
                data=np.asarray(g[f"measurements/detector/{b}"]), dims=("line", "detector"))
        prod["conditions/time/line_time"] = EOVariable(
            data=np.asarray(g["conditions/time/line_time"]), dims=("line",))
        l1a = L0DecodeUnit("l0").run({"l0c": prod}, bit_depth=pre["bit_depth"],
                                     max_lost_fraction=0.1, name=f"{stem}.g{gi}")["l1a"]
        lost.update(l1a.attrs["other_metadata"]["quality"]["lines_lost"])
        st = EOZarrStore(str(outdir))
        st.open(mode=OpeningMode.CREATE_OVERWRITE, delayed_writing=False)
        try:
            st[f"{stem}.g{gi}"] = l1a
        finally:
            st.close()
        del prod, l1a
        print(f"[l0-decode] group {gi} ({len(grp)} bands) → {outdir}/{stem}.g{gi}.zarr")
    _jdump({"lines_lost": lost, "groups": len(groups)}, store["report"] / "l0_decode.json")


def phase_validate(store: dict[str, Path], args) -> None:
    import zarr
    from msi_processor.common.metrics import align_extent, compute_metrics

    pre = _jload(store["report"] / "preflight.json")
    dec = _jload(store["report"] / "l0_decode.json")
    l1a = pre["l1a_path"]
    stem = pre["product_names"]["l1a_prime"].removesuffix(".zarr")
    res = {}
    for gp in sorted(store["l1a_prime"].glob(f"{stem}.g*.zarr")):
        gg = zarr.open_group(str(gp), mode="r")
        for b in gg["measurements/detector"].array_keys():
            test = np.asarray(gg[f"measurements/detector/{b}"])
            ref = gio.read_l1a_raw(l1a, DETECTOR, b, lines=args.line_slice, dtype=np.uint16)
            t2, r2 = align_extent(test, ref)
            ms = compute_metrics(t2.astype(np.float64), r2.astype(np.float64),
                                 bit_depth=pre["bit_depth"])
            res[b] = {
                "bit_identical_kept": bool(np.array_equal(t2, r2)),
                "kept_lines": int(test.shape[0]),
                "lines_lost": int(dec["lines_lost"].get(b, 0)),
                "preflight_zero_tail": pre["per_band"][b]["trailing_zero_lines"],
                "rmse": None if np.isnan(ms.rmse) else float(ms.rmse),
                "psnr": None if np.isnan(ms.psnr) else float(ms.psnr),
            }
            ok = res[b]["bit_identical_kept"] and \
                res[b]["lines_lost"] == res[b]["preflight_zero_tail"]
            print(f"[validate] {b}: bit_identical={res[b]['bit_identical_kept']} "
                  f"lost={res[b]['lines_lost']} (preflight {res[b]['preflight_zero_tail']}) "
                  f"rmse={res[b]['rmse']}")
            if not ok:
                res[b]["verdict"] = "KO"
    _jdump(res, store["report"] / "validate.json")
    n_ok = sum(1 for r in res.values() if r["bit_identical_kept"])
    print(f"[validate] bit-identical bands: {n_ok}/{len(res)}")


def phase_radiometric_vv(store: dict[str, Path], args) -> None:
    gipp_dir = args.gipp or os.environ.get("S2_E2ES_GIPP_DIR")
    if not gipp_dir:
        _jdump({"skipped": "no GIPP dir supplied"}, store["report"] / "radiometric_vv.json")
        print("[radiometric-vv] skipped (no --gipp)")
        return
    from s2_msi_raw_generator import forward_radiometric_atbd as fwd, gipp as gipp_mod

    pre = _jload(store["report"] / "preflight.json")
    gs = gipp_mod.load_gipp_set(gipp_dir, bands=tuple(pre["bands"]))
    out = {}
    for bn in pre["bands"]:
        try:
            eq = gs.band(bn).detectors[DETECTOR]      # roundtrip_real_l1a.py pattern
        except (KeyError, AttributeError) as exc:
            out[bn] = {"skipped": f"no GIPP coefficients ({exc})"}
            continue
        x = gio.read_l1a_raw(pre["l1a_path"], DETECTOR, bn, lines=slice(0, 2048))
        y = fwd.forward_correct(x, eq)
        x2 = fwd.reverse_impress(y, eq)
        valid = (x > 0) & (x < _SENTINEL_SATURATED)
        rmse = float(np.sqrt(np.mean((x2[valid] - x[valid]) ** 2))) if valid.any() else 0.0
        out[bn] = {"rmse": rmse,
                   "fpn_raw": float(fwd.column_fpn(x)), "fpn_corrected": float(fwd.column_fpn(y))}
        print(f"[radiometric-vv] {bn}: rmse={rmse:.3e}")
    _jdump(out, store["report"] / "radiometric_vv.json")


def _scan_member(name: str, buf: bytes) -> dict:
    """Header-walk one binary member with the same walker used on our own streams."""
    from s2_msi_raw_generator import sad as sad_mod

    pkts = sad_mod.scan_ccsds_packets(buf)
    covered = 0
    apids: dict[int, int] = {}
    flags: dict[int, int] = {}
    dlens: list[int] = []
    seq_ok = True
    last_seq: dict[int, int] = {}
    for p in pkts:
        dlen = p["data_len"] + 1
        covered = p["offset"] + isp.PRIMARY_HEADER_LEN + dlen
        apids[p["apid"]] = apids.get(p["apid"], 0) + 1
        flags[p["seq_flags"]] = flags.get(p["seq_flags"], 0) + 1
        dlens.append(dlen)
        prev = last_seq.get(p["apid"])
        if prev is not None and p["seq_count"] != (prev + 1) % isp.SEQ_COUNT_MOD:
            seq_ok = False
        last_seq[p["apid"]] = p["seq_count"]
    return {
        "member": name, "bytes": len(buf), "packets": len(pkts),
        "tiles_exactly": covered == len(buf), "coverage_bytes": covered,
        "seq_continuous_per_apid": seq_ok,
        "apids": {str(k): v for k, v in sorted(apids.items())},
        "seq_flags": {str(k): v for k, v in sorted(flags.items())},
        "dlen_min": min(dlens) if dlens else None, "dlen_max": max(dlens) if dlens else None,
    }


def phase_scan_l0(store: dict[str, Path], args) -> None:
    """Structural scan of the accessible real-L0 references (REQ-FUNC-093).

    The real **SADATA** tar members are genuine downlinked CCSDS packet streams — our packet
    walker must tile them; the **DS** tar gives the real PSD datastrip identifiers for the
    naming crosswalk.  (The SAFE image-ISP ``.bin`` files are GET-403 on the bucket; that
    limitation is recorded in the report.)
    """
    import re
    import tarfile

    dest = store["inputs"] / "real_l0"
    tars = sorted(dest.glob("*.tar"))
    if not tars:
        _jdump({"skipped": f"no real-L0 tars under {dest}"},
               store["report"] / "isp_structural.json")
        print("[scan-l0] skipped (real-L0 references not fetched)")
        return
    sad_scans, ds_info = [], {}
    for t in tars:
        with tarfile.open(t, "r:*") as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            if "SADATA" in t.name:
                for m in members:
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    sad_scans.append(_scan_member(f"{t.name}::{m.name}", f.read()))
            elif "_MSI_L0__DS_" in t.name:
                ds_info["tar"] = t.name
                ds_info["members"] = [{"name": m.name, "bytes": m.size} for m in members]
                for m in members:                       # datastrip metadata → PSD identifiers
                    if m.name.upper().endswith(".XML") and "MTD" in m.name.upper():
                        xml = tf.extractfile(m).read().decode("utf-8", "replace")
                        ds_info["mtd_member"] = m.name
                        ids = sorted(set(re.findall(r"S2A_OPER_MSI_L0__DS_[A-Z0-9_]+", xml)))
                        times = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", xml)))
                        ds_info["psd_datastrip_ids"] = ids[:5]
                        ds_info["sensing_times"] = times[:6]
    # naming crosswalk: our PSD-style metadata id + PSFD file names vs the real PSD forms
    pre = _jload(store["report"] / "preflight.json")
    crosswalk = {"ours_psfd_l0": pre["product_names"]["l0"],
                 "real_psd_ds_tar": ds_info.get("tar"),
                 "real_psd_datastrip_ids": ds_info.get("psd_datastrip_ids", [])}
    canon = store["l0"] / pre["product_names"]["l0"]
    if canon.exists():
        import zarr
        g = zarr.open_group(str(canon), mode="r")
        crosswalk["ours_psd_datastrip_id"] = dict(g.attrs)["stac_discovery"]["properties"].get(
            "eopf:datastrip_id")
        crosswalk["psd_pattern_match"] = bool(
            crosswalk["ours_psd_datastrip_id"] and
            re.fullmatch(r"S2[ABC]_OPER_MSI_L0__DS_\d{8}T\d{6}_A\d{6}",
                         crosswalk["ours_psd_datastrip_id"]))
        ours = {}
        for bn in pre["bands"]:
            mg = g[f"measurements/d{DETECTOR:02d}/{sensor.zarr_band_key(bn)}"]
            stream = np.asarray(mg["isp"])
            ours[bn] = {"packets": sum(1 for _ in isp.iter_packets(stream)),
                        "bytes": int(stream.size),
                        "ratio": dict(mg.attrs)["compression"]["ratio"]}
    else:
        ours = {}
    n_tiled = sum(1 for s in sad_scans if s["tiles_exactly"])
    _jdump({"safe_limitation": "PSD L0 SAFE image-ISP .bin objects are HTTP 403 on GET "
                               "(bucket policy) — image-packet accounting not possible; "
                               "structural ISP validation done on real SADATA packet streams",
            "real_sadata": sad_scans, "real_ds": ds_info,
            "naming_crosswalk": crosswalk, "ours": ours,
            "sadata_members_tiling": f"{n_tiled}/{len(sad_scans)}"},
           store["report"] / "isp_structural.json")
    print(f"[scan-l0] SADATA members tiling exactly: {n_tiled}/{len(sad_scans)}; "
          f"DS ids: {ds_info.get('psd_datastrip_ids', [])[:2]}")


def phase_quicklook(store: dict[str, Path], args) -> None:
    pre = _jload(store["report"] / "preflight.json")
    l1a = pre["l1a_path"]
    rgb = ("B04", "B03", "B02")
    if not all(b in pre["bands"] for b in rgb):
        print("[quicklook] skipped (RGB bands not in selection)")
        return
    full = {b: gio.read_l1a_raw(l1a, DETECTOR, b, lines=args.line_slice,
                                dtype=np.uint16)[::8] for b in rgb}
    p1 = quicklook.save_rgb(full, store["quicklook"] / "l1a_rgb_strip.png")
    crop = {b: v[: min(650, v.shape[0])] for b, v in full.items()}
    p2 = quicklook.save_rgb(crop, store["quicklook"] / "l1a_rgb_crop.png")
    del full, crop
    # L1A′ pair (from the persisted products, decimated identically)
    import zarr
    stem = pre["product_names"]["l1a_prime"].removesuffix(".zarr")
    prime: dict[str, np.ndarray] = {}
    for gp in sorted(store["l1a_prime"].glob(f"{stem}.g*.zarr")):
        gg = zarr.open_group(str(gp), mode="r")
        for b in rgb:
            if b in gg["measurements/detector"]:
                prime[b] = np.asarray(gg[f"measurements/detector/{b}"])[::8]
    p3 = None
    if len(prime) == 3:
        p3 = quicklook.save_rgb(prime, store["quicklook"] / "l1a_prime_rgb_strip.png")
    # DWT subband visualisation of a B04 window (codec showcase)
    win = gio.read_l1a_raw(l1a, DETECTOR, "B04", lines=slice(0, 1296), dtype=np.uint16)
    bands = ccsds122.dwt97m_forward(win[:, :1296].astype(np.int64))
    ll = np.abs(bands["LL3"]); hl = np.abs(bands["HL1"])
    p4 = quicklook.save_rgb({"r": ll, "g": ll, "b": ll}, store["quicklook"] / "dwt_ll3.png",
                            rgb=("r", "g", "b"))
    p5 = quicklook.save_rgb({"r": hl, "g": hl, "b": hl}, store["quicklook"] / "dwt_hl1.png",
                            rgb=("r", "g", "b"))
    print(f"[quicklook] {p1}\n            {p2}\n            {p3}\n            {p4}\n            {p5}")


def phase_report(store: dict[str, Path], args) -> None:
    rep = store["report"]
    sections = {}
    for name in ["fetch_l1a_manifest", "fetch_l0_manifest", "preflight", "ground_decode",
                 "l0_decode", "validate", "radiometric_vv", "isp_structural"]:
        p = rep / f"{name}.json"
        sections[name] = _jload(p) if p.exists() else {"missing": True}
    pre = sections["preflight"]
    lines = ["# Real-L1A E2E run report", ""]
    if not pre.get("missing"):
        lines += [f"- L1A: `{pre['l1a_path']}` · bands {len(pre['bands'])} · "
                  f"lines {pre['n_lines']} · bit_depth {pre['bit_depth']}",
                  f"- Products: `{pre['product_names']['l0']}` / "
                  f"`{pre['product_names']['l0_oc']}` / `{pre['product_names']['l1a_prime']}`",
                  f"- Naming fallbacks: {pre['naming_fallbacks'] or 'none'}", ""]
    gd = sections["ground_decode"]
    if not gd.get("missing"):
        lines += ["## Compression + ground decode (bit-exact)", "",
                  "| band | ratio | packets | bit-exact |", "|---|---|---|---|"]
        lines += [f"| {b} | {v.get('ratio')} | {v.get('n_packets')} | {v.get('bit_exact')} |"
                  for b, v in sorted(gd.items())]
        lines.append("")
    va = sections["validate"]
    if not va.get("missing"):
        lines += ["## L1A′ vs original L1A", "",
                  "| band | bit-identical (kept) | lines lost | rmse |", "|---|---|---|---|"]
        lines += [f"| {b} | {v['bit_identical_kept']} | {v['lines_lost']} | {v['rmse']} |"
                  for b, v in sorted(va.items())]
        lines.append("")
    rv = sections["radiometric_vv"]
    if not rv.get("missing") and not rv.get("skipped"):
        lines += ["## Radiometric GIPP round-trip", "", "| band | rmse | fpn raw → corrected |",
                  "|---|---|---|"]
        lines += [f"| {b} | {v.get('rmse'):.3e} | {v.get('fpn_raw', 0):.3f} → "
                  f"{v.get('fpn_corrected', 0):.3f} |"
                  for b, v in sorted(rv.items()) if "rmse" in v]
        lines.append("")
    st = sections["isp_structural"]
    if not st.get("missing") and not st.get("skipped"):
        lines += ["## Real-L0 ISP structural scan", "",
                  f"- {st.get('safe_limitation', '')}",
                  f"- Real SADATA members tiling exactly: {st.get('sadata_members_tiling')}",
                  ""]
        if st.get("real_sadata"):
            lines += ["| member | packets | tiles | seq continuous | data-len min..max |",
                      "|---|---|---|---|---|"]
            lines += [f"| {s['member']} | {s['packets']} | {s['tiles_exactly']} | "
                      f"{s['seq_continuous_per_apid']} | {s['dlen_min']}..{s['dlen_max']} |"
                      for s in st["real_sadata"]]
            lines.append("")
        cw = st.get("naming_crosswalk", {})
        if cw:
            lines += ["### Naming crosswalk (PSD ↔ PSFD)", "",
                      f"- ours (PSFD file): `{cw.get('ours_psfd_l0')}`",
                      f"- ours (PSD datastrip id in metadata): `{cw.get('ours_psd_datastrip_id')}` "
                      f"(pattern match: {cw.get('psd_pattern_match')})",
                      f"- real (PSD DS tar): `{cw.get('real_psd_ds_tar')}`",
                      f"- real datastrip ids: {cw.get('real_psd_datastrip_ids')}", ""]
    (rep / "e2e_report.md").write_text("\n".join(lines) + "\n")
    _jdump(sections, rep / "summary.json")
    print(f"[report] {rep/'e2e_report.md'}")


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("store", help="data-store root (e.g. ~/validation-data/e2e-real)")
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--l1a", default=None, help="override L1A path (else store download / $S2_E2ES_L1A)")
    ap.add_argument("--gipp", default=None, help="GIPP dir for the radiometric V&V phase")
    ap.add_argument("--bands", default=",".join(sensor.BANDS))
    ap.add_argument("--lines", type=int, default=0, help="window: first N lines (0 = full)")
    ap.add_argument("--band-groups", type=int, default=1, dest="band_groups")
    ap.add_argument("--max-payload", type=int, default=isp.DEFAULT_MAX_PAYLOAD, dest="max_payload")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--store-decoded", default="yes", choices=("yes", "no"), dest="store_decoded_s")
    args = ap.parse_args(argv)
    args.bands = [b.strip().upper() for b in args.bands.split(",") if b.strip()]
    args.line_slice = slice(0, args.lines) if args.lines else None
    args.store_decoded = args.store_decoded_s == "yes"

    store = _store_paths(Path(os.path.expanduser(args.store)))
    todo = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = [p for p in todo if p not in PHASES]
    if unknown:
        ap.error(f"unknown phases: {unknown} (choose from {PHASES})")
    fns = {
        "fetch-l1a": phase_fetch_l1a, "fetch-l0": phase_fetch_l0, "preflight": phase_preflight,
        "package": phase_package, "ground-decode": phase_ground_decode,
        "l0-decode": phase_l0_decode, "validate": phase_validate,
        "radiometric-vv": phase_radiometric_vv, "scan-l0": phase_scan_l0,
        "quicklook": phase_quicklook, "report": phase_report,
    }
    for p in PHASES:
        if p in todo:
            fns[p](store, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

"""The reverse-E2ES pipeline — the repository's single driver script.

One phase-structured, idempotent pipeline covers every production path; all product file
names come from :mod:`s2_msi_raw_generator.naming` (EOPF PSFD §3 — REQ-FUNC-091), and one
data-store root holds every product (``inputs/ caldb/ l0/ l1a_prime/ l1b/ quicklook/
figures/ report/``).

**Real-data chain** (REQ-FUNC-093; the default phase set). Mirrors the real chain: the S2
L0→L1A relation is *decode/packaging* (SentiWiki: L0 stores compressed ISPs, L1A
decompresses) — the real L1A DN ``X`` is CCSDS-122 lossless-compressed and packetized into
the canonical L0, ground-decoded back (``X′ == X`` bit-exact), written as the open-container
L0 and pushed through msi-processor ``l0_decode`` → **L1A′** (bit-identical on kept lines)::

    fetch-l1a fetch-l0 preflight package ground-decode l0-decode validate
    radiometric-vv scan-l0 quicklook report

**Synthetic chain** (REQ-FUNC-042; selected by ``--synthetic``). Builds the flat-field
open-container L0 + cal-DB and runs the processor to an L1B TOA-reflectance product::

    build-l0-synth l0-to-l1b

**On-demand phases** (never in a default set): ``build-caldb`` (the full 13-band derived
Option-Y cal-DB, :mod:`s2_msi_raw_generator.caldb`), ``derive-adf`` (real per-detector
PRNU/dark from matched products, → ``BandADF.from_product``), ``figures`` (the single-band
stage-by-stage README/docs figures + quality metrics).

Examples::

    python scripts/run_pipeline.py ~/data-store                              # real chain
    python scripts/run_pipeline.py <store> --phases preflight,package --lines 4096
    python scripts/run_pipeline.py data/output --synthetic                    # synthetic chain
    python scripts/run_pipeline.py <store> --phases figures --fig-l1b <L1B.zarr[.zip]>

The eopf/msi_processor imports are lazy (``l0-decode``/``validate``/``l0-to-l1b`` only), so
every other phase — and this module's import — works in the plain generator environment (CI).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from s2_msi_raw_generator import (adf as adfmod, caldb as caldb_mod, ccsds122, datation,
                                  io as gio, isp, l0product, naming, quicklook, reverse,
                                  s3fetch, sensor)
from s2_msi_raw_generator.adf_writer import BandCal, write_calibration_db

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
# Bands grouped by ground resolution: line counts differ per resolution in a real product
# (10 m = 2× the 20 m, 6× the 60 m line count), and a persisted EOPF product must not mix
# 'line' sizes in one group (PSFD: different resolutions use different dimensions) — so
# l0_decode + persist run per resolution group.
RES_GROUPS = {
    "r10m": ["B02", "B03", "B04", "B08"],
    "r20m": ["B05", "B06", "B07", "B8A", "B11", "B12"],
    "r60m": ["B01", "B09", "B10"],
}
PHASES = ["fetch-store", "fetch-l1a", "fetch-l0", "preflight", "build-caldb", "build-l0-synth",
          "package", "ground-decode", "l0-decode", "validate", "l0-to-l1b", "radiometric-vv",
          "derive-adf", "scan-l0", "quicklook", "figures", "report", "publish-store"]
#: Default phase sets: the real-data chain and the --synthetic flat-field chain.
REAL_PHASES = ["fetch-l1a", "fetch-l0", "preflight", "package", "ground-decode", "l0-decode",
               "validate", "radiometric-vv", "scan-l0", "quicklook", "report"]
SYNTH_PHASES = ["build-l0-synth", "l0-to-l1b"]

_SENTINEL_SATURATED = 32768        # IF-IN-L1A saturation sentinel in the real product

# Synthetic flat-field chain constants (REQ-FUNC-042). One common detector width across all
# bands so nuc.gain[band] length == detector-axis width (the hard open-container invariant).
SYNTH_N_DET = 64
SYNTH_N_LINES = 48
SYNTH_BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]   # 10 m group + SWIR
SYNTH_SUN_ZENITH_DEG = 35.0
_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _store_paths(store: Path) -> dict[str, Path]:
    p = {
        "inputs": store / "inputs",
        "caldb": store / "caldb",
        "l0": store / "l0",
        "l1a_prime": store / "l1a_prime",
        "l1b": store / "l1b",
        "quicklook": store / "quicklook",
        "figures": store / "figures",
        "report": store / "report",
    }
    for d in p.values():
        d.mkdir(parents=True, exist_ok=True)
    return p


def _synth_names(n_lines: int) -> dict[str, str]:
    """PSFD names for the synthetic chain's products (module defaults, flagged context)."""
    dur = n_lines * sensor.LINE_PERIOD_MS / 1e3
    common = dict(unit=naming.DEFAULT_UNIT, relative_orbit=naming.DEFAULT_RELATIVE_ORBIT)
    return {
        "l0_oc": naming.psfd_name("S02MSIL0_", naming.DEFAULT_START, dur, z_suffix="OC", **common),
        "l1b": naming.psfd_name("S02MSIL1B", naming.DEFAULT_START, dur, **common),
    }


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
    # Operational decoder = the CONSUMER's (msi-processor ground_decode — the real-chain
    # L1A-side decompression); the generator's read_l0_isp_dn stays as the E2ES-side
    # reference decoder and cross-checks it when the consumer is importable.
    try:
        from msi_processor.computing.l0_decode.ground_decode import decode_canonical_l0
    except ImportError:
        decode_canonical_l0 = None
    rt = {}
    band_frames = {}
    for bn in pre["bands"]:
        rec_ref = l0product.read_l0_isp_dn(canon, DETECTOR, bn)
        cross = None
        if decode_canonical_l0 is not None:
            rec = decode_canonical_l0(canon, DETECTOR, bn)
            cross = bool(np.array_equal(rec, rec_ref))
            if not cross:
                raise SystemExit(f"[ground-decode] {bn}: consumer and reference decoders disagree")
        else:
            rec = rec_ref
        orig = gio.read_l1a_raw(l1a, DETECTOR, bn, lines=args.line_slice, dtype=np.uint16)
        ok = bool(np.array_equal(rec, orig))
        rt[bn] = {"bit_exact": ok,
                  "decoder": "msi-processor" if decode_canonical_l0 else "e2es-reference",
                  "decoder_cross_check": cross}
        if not ok:
            raise SystemExit(f"[ground-decode] {bn}: reconstructed DN != original — codec fault")
        band_frames[bn] = rec
        del orig
        print(f"[ground-decode] {bn}: bit-exact OK"
              + (f" (consumer decoder, cross-check {cross})" if cross is not None else ""))
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
    # resolution groups keep 'line' uniform within each persisted product (real products mix
    # 10 m / 20 m / 60 m line counts); --band-groups > 1 subdivides them further for RAM.
    groups: list[list[str]] = []
    for res_bands in RES_GROUPS.values():
        grp = [b for b in bands if b in res_bands]
        if args.band_groups > 1:
            groups += [grp[i::args.band_groups] for i in range(args.band_groups)]
        else:
            groups.append(grp)
    groups += [[b for b in bands if not any(b in r for r in RES_GROUPS.values())]]
    outdir = store["l1a_prime"]
    stem = pre["product_names"]["l1a_prime"].removesuffix(".zarr")
    lost = {}
    for gi, grp in enumerate(g_ for g_ in groups if g_):
        prod = EOProduct(f"{stem}.g{gi}")
        grp_lines = None
        for b in grp:
            arr = np.asarray(g[f"measurements/detector/{b}"])
            grp_lines = arr.shape[0] if grp_lines is None else grp_lines
            prod[f"measurements/detector/{b}"] = EOVariable(data=arr, dims=("line", "detector"))
        # line_time is sampled at the finest (10 m) line rate; stride it to this group's line
        # count so the persisted product keeps one consistent 'line' dimension per resolution.
        lt = np.asarray(g["conditions/time/line_time"])
        stride = max(1, lt.shape[0] // grp_lines) if grp_lines else 1
        prod["conditions/time/line_time"] = EOVariable(data=lt[::stride][:grp_lines], dims=("line",))
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


# ---------------------------------------------------------------------------
# data-store sync (ipf/data-store: registry = DB, local store = working copy)
# ---------------------------------------------------------------------------

DATASTORE_API = ("https://gitlab.eopf.copernicus.eu/api/v4/projects/ipf%2Fdata-store"
                 "/packages/generic")
DATASTORE_PACKAGES_API = ("https://gitlab.eopf.copernicus.eu/api/v4/projects/ipf%2Fdata-store"
                          "/packages")


def _store_auth_headers() -> dict[str, str]:
    """Registry write auth: CI job token (allowlisted) or a personal token from the env."""
    if os.environ.get("CI_JOB_TOKEN"):
        return {"JOB-TOKEN": os.environ["CI_JOB_TOKEN"]}
    tok = os.environ.get("DATASTORE_TOKEN") or os.environ.get("GITLAB_TOKEN")
    if tok:
        return {"PRIVATE-TOKEN": tok}
    raise SystemExit("[publish-store] needs CI_JOB_TOKEN (CI) or DATASTORE_TOKEN/GITLAB_TOKEN")


def _http(url: str, *, headers: dict | None = None, method: str = "GET", data=None) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip_dir(src: Path, dest_zip: Path) -> None:
    import zipfile

    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(src.parent))


def phase_fetch_store(store: dict[str, Path], args) -> None:
    """Pull the shared data-store (manifest → missing packages → sha256 → unpack).

    Anonymous read (the ipf/data-store project is public); idempotent — files already
    present in the local store are skipped. The "git pull" of the data DB.
    """
    import hashlib
    import io as _io
    import zipfile

    root = store["report"].parent
    manifest = json.loads(_http(f"{DATASTORE_API}/manifest/latest/manifest.json").decode())
    fetched = skipped = 0
    for pkg in manifest.get("packages", []):
        for f in pkg["files"]:
            target = root / (f["path"][:-4] if f["path"].endswith(".zip") else f["path"])
            # _store_paths pre-creates the standard dirs, so "present" means non-empty
            if target.is_file() or (target.is_dir() and any(target.iterdir())):
                skipped += 1
                continue
            blob = _http(f"{DATASTORE_API}/{pkg['name']}/{pkg['version']}/{f['file']}")
            got = hashlib.sha256(blob).hexdigest()
            if got != f["sha256"]:
                raise SystemExit(f"[fetch-store] sha256 mismatch for {f['file']}: {got}")
            if f["path"].endswith(".zip"):
                (root / f["path"]).parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(_io.BytesIO(blob)) as zf:
                    zf.extractall((root / f["path"]).parent)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            fetched += 1
            print(f"[fetch-store] {pkg['name']}/{pkg['version']}: {f['file']} → {target}")
    print(f"[fetch-store] done — {fetched} fetched, {skipped} already present")


def phase_publish_store(store: dict[str, Path], args) -> None:
    """Publish the local store's products to the shared registry + refresh the manifest.

    Packages are immutable versions (``--publish-name/--publish-version``); only the
    ``manifest/latest`` entry is replaced in place. The "git push" of the data DB.
    """
    if not args.publish_version:
        raise SystemExit("[publish-store] needs --publish-version (immutable package version)")
    name, version = args.publish_name, args.publish_version
    headers = _store_auth_headers()
    root = store["report"].parent
    stage = root / ".publish-stage"
    stage.mkdir(exist_ok=True)

    entries = []
    if args.publish_layer == "inputs":
        # auxiliary inputs (e.g. the operational GIPP) live under inputs/
        for d in sorted((root / "inputs").iterdir()) if (root / "inputs").is_dir() else []:
            if d.is_dir() and any(d.iterdir()):
                zp = stage / f"{d.name}.zip"
                _zip_dir(d, zp)
                entries.append((zp, f"inputs/{d.name}.zip"))
    else:
        # product zarr dirs → PSFD .zarr.zip; plain dirs (caldb/quicklook/…) → dir.zip
        for sub in ("l0", "l1a_prime", "l1b"):
            for z in sorted((root / sub).glob("*.zarr")):
                zp = stage / f"{z.name}.zip"
                _zip_dir(z, zp)
                entries.append((zp, f"{sub}/{z.name}.zip"))
        for sub in ("caldb", "quicklook", "report", "figures"):
            d = root / sub
            if d.is_dir() and any(d.iterdir()):
                zp = stage / f"{sub}.zip"
                _zip_dir(d, zp)
                entries.append((zp, f"{sub}.zip"))
    if not entries:
        raise SystemExit(f"[publish-store] nothing to publish under {root}")

    files = []
    for zp, rel in entries:
        flat = rel.replace("/", "__")
        _http(f"{DATASTORE_API}/{name}/{version}/{flat}", headers=headers, method="PUT",
              data=zp.read_bytes())
        files.append({"file": flat, "path": rel, "sha256": _sha256_file(zp),
                      "bytes": zp.stat().st_size})
        print(f"[publish-store] {name}/{version}: {flat} ({zp.stat().st_size/1e6:.1f} MB)")

    # merge into the manifest and replace manifest/latest atomically (delete old package first)
    try:
        manifest = json.loads(_http(f"{DATASTORE_API}/manifest/latest/manifest.json").decode())
    except Exception:  # noqa: BLE001 - first publish ever
        manifest = {"schema": 1, "packages": [], "external": []}
    manifest["packages"] = [p for p in manifest["packages"]
                            if not (p["name"] == name and p["version"] == version)]
    manifest["packages"].append({"name": name, "version": version, "layer": args.publish_layer,
                                 "files": files, "source": args.publish_source})
    pkgs = json.loads(_http(f"{DATASTORE_PACKAGES_API}?package_name=manifest",
                            headers=headers).decode())
    for p in pkgs:
        if p.get("version") == "latest":
            _http(f"{DATASTORE_PACKAGES_API}/{p['id']}", headers=headers, method="DELETE")
    _http(f"{DATASTORE_API}/manifest/latest/manifest.json", headers=headers, method="PUT",
          data=json.dumps(manifest, indent=2).encode())
    print(f"[publish-store] manifest updated — {len(manifest['packages'])} packages")


# ---------------------------------------------------------------------------
# synthetic chain (REQ-FUNC-042) + on-demand phases
# ---------------------------------------------------------------------------

def phase_build_caldb(store: dict[str, Path], args) -> None:
    """Full 13-band derived Option-Y cal-DB (:func:`s2_msi_raw_generator.caldb.build`)."""
    paths = caldb_mod.build(store["caldb"], n_det=args.caldb_n_det, seed=args.seed)
    print(f"[build-caldb] {len(paths)} ADFs → {store['caldb']}")


def build_inputs(work_dir=None, *, n_det: int = SYNTH_N_DET, n_lines: int = SYNTH_N_LINES,
                 bands=SYNTH_BANDS, seed: int = 0):
    """Build the cal-DB (with ESUN) + a synthetic open-container L0 at a common ``n_det``.

    Pure numpy/zarr. Writes to ``work_dir`` (default: the repo's ``data/output/``):
    ``l0/<PSFD>_OC.zarr`` + ``caldb/``. Returns ``(l0_path, caldb_dir, band_frames)``.
    This is the CI-verified half of the synthetic E2E (``tests/test_e2e_l1b.py``).
    """
    work = Path(work_dir) if work_dir is not None else _REPO_ROOT / "data" / "output"
    l0_dir = work / "l0"
    l0_dir.mkdir(parents=True, exist_ok=True)
    caldb = work / "caldb"

    # cal-DB coefficients at n_det, with per-band ESUN so the toa unit can emit reflectance.
    rng = np.random.default_rng(seed)
    cals = []
    band_frames: dict[str, np.ndarray] = {}
    for bn in bands:
        b = sensor.band(bn)
        gain = (1.0 + rng.normal(0, 0.02, n_det)).astype(np.float32)   # PRNU ~1
        offset = np.zeros(n_det, np.float32)
        cals.append(BandCal(band=bn, nuc_gain=gain, nuc_offset=offset,
                            dark_offset=float(sensor.DARK_PEDESTAL_LSB),
                            radio_gain=float(1.0 / b.cal_gain), radio_offset=0.0,
                            esun=float(sensor.esun(bn)),
                            noise_alpha=float(b.noise_alpha), noise_beta=float(b.noise_beta)))
        radiance = np.full((n_lines, n_det), b.lref * 0.7)
        band_frames[bn] = l0product.reverse_to_l0_frames({(1, bn): radiance}, seed=seed)[(1, bn)]
    write_calibration_db(caldb, cals, unit="S2A")

    l0_path = str(l0_dir / _synth_names(n_lines)["l0_oc"])
    l0product.write_l0_opencontainer(l0_path, band_frames, datation=datation.Datation())
    return l0_path, str(caldb), band_frames


def run_processor(l0_path, caldb_dir, *, sun_zenith_deg: float = SYNTH_SUN_ZENITH_DEG,
                  earth_sun_distance_au: float = 1.0):
    """Run msi-processor ``l0_decode → radiometric → enhancement → toa`` (emit_reflectance) → L1B.

    Needs ``eopf==2.8.1`` + ``msi_processor`` (the SDE or the manual ``e2e-l1b`` CI job);
    imported lazily so this file stays importable in generator CI.
    """
    import zarr
    from eopf.computing.abstract import AuxiliaryDataFile
    from eopf.product import EOProduct, EOVariable
    from msi_processor.computing.enhancement.unit import EnhancementUnit
    from msi_processor.computing.l0_decode.unit import L0DecodeUnit
    from msi_processor.computing.radiometric.unit import RadiometricUnit
    from msi_processor.computing.toa.unit import ToaUnit

    def _adf(name, data_ptr):
        return AuxiliaryDataFile(name=name, path=f"{name}.zarr", data_ptr=data_ptr)

    def _grp(name):
        return zarr.open_group(f"{caldb_dir}/{name}.zarr", mode="r")

    # open-container L0 (zarr v2 on disk) → EOProduct with EOVariable detector frames + conditions
    g = zarr.open_group(l0_path, mode="r")
    det = g["measurements/detector"]
    bands = sorted(det.array_keys())
    prod = EOProduct("L0C_E2E")
    for b in bands:
        prod[f"measurements/detector/{b}"] = EOVariable(data=np.asarray(det[b]),
                                                        dims=("line", "detector"))
    prod["conditions/time/line_time"] = EOVariable(
        data=np.asarray(g["conditions/time/line_time"]), dims=("line",))

    # cal-DB zarr → ADFs in the processor's nested ``data_ptr`` convention
    nz, dz, rz, sz = _grp("nuc"), _grp("dark"), _grp("radiometric"), _grp("spectral")
    nuc = _adf("nuc", {"gain": {b: np.asarray(nz[f"gain/{b}"]) for b in bands},
                       "offset": {b: np.asarray(nz[f"offset/{b}"]) for b in bands}})
    dark = _adf("dark", {"dark_offset": {b: float(np.asarray(dz[f"dark_offset/{b}"]))
                                         for b in bands}})
    radiom = _adf("radiometric", {"gain": {b: float(np.asarray(rz[f"gain/{b}"])) for b in bands},
                                  "offset": {b: float(np.asarray(rz[f"offset/{b}"]))
                                             for b in bands}})
    spec = _adf("spectral", {"esun": {b: float(np.asarray(sz[f"esun/{b}"])) for b in bands}})
    psf = _adf("psf", {"kernel": {b: np.array([[1.0]], dtype=np.float32) for b in bands}})

    # l0_decode → radiometric → enhancement (identity MTFC, no denoise) → toa (emit_reflectance)
    l1a = L0DecodeUnit("l0").run({"l0c": prod})["l1a"]
    rad = RadiometricUnit("rad").run({"l1a": l1a}, adfs={"dark": dark, "nuc": nuc})["rad"]
    enh = EnhancementUnit("enh").run({"rad": rad}, adfs={"psf": psf}, denoise_method="none")["enh"]
    l1b = ToaUnit("toa").run(
        {"enh": enh},
        adfs={"radiometric": radiom, "spectral": spec},
        emit_reflectance=True, sun_zenith_deg=sun_zenith_deg,
        earth_sun_distance_au=earth_sun_distance_au,
    )["l1b"]
    return l1b


def write_l1b(l1b, out_dir, name: str | None = None) -> str:
    """Persist the L1B ``EOProduct`` to ``out_dir/<name>.zarr`` with eopf's native zarr store.

    ``name`` defaults to the PSFD L1B name of the synthetic chain. ``EOZarrStore(url)``
    requires ``url`` to already exist and writes ``url / key + ".zarr"`` on
    ``store[key] = product``; ``delayed_writing=False`` so the product is fully on disk.
    """
    from eopf.common.constants import OpeningMode
    from eopf.store.zarr import EOZarrStore

    if name is None:
        name = _synth_names(SYNTH_N_LINES)["l1b"].removesuffix(".zarr")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    store = EOZarrStore(str(out))
    store.open(mode=OpeningMode.CREATE_OVERWRITE, delayed_writing=False)
    try:
        store[name] = l1b
    finally:
        store.close()
    return str(out / f"{name}.zarr")


def phase_build_l0_synth(store: dict[str, Path], args) -> None:
    """Synthetic flat-field open-container L0 + cal-DB (the CI-verified E2E half)."""
    l0_path, caldb, band_frames = build_inputs(store["l0"].parent, seed=args.seed)
    ql = quicklook.save_rgb(band_frames, store["quicklook"] / "l0_rgb.png", upscale=4)
    _jdump({"l0": l0_path, "caldb": caldb, "bands": sorted(band_frames),
            "n_det": SYNTH_N_DET, "n_lines": SYNTH_N_LINES},
           store["report"] / "build_l0_synth.json")
    print(f"[build-l0-synth] open-container L0 → {l0_path}\n"
          f"                 cal-DB (incl. spectral/ESUN) → {caldb}\n"
          f"                 L0 quicklook → {ql}")


def phase_l0_to_l1b(store: dict[str, Path], args) -> None:
    """Open-container L0 + cal-DB → processor chain → PSFD-named L1B reflectance product."""
    oc = sorted(store["l0"].glob("*_OC.zarr"))
    if not oc:
        raise SystemExit(f"[l0-to-l1b] no *_OC.zarr under {store['l0']} "
                         "(run build-l0-synth or ground-decode first)")
    caldb = store["caldb"]
    if not (caldb / "nuc.zarr").exists():
        raise SystemExit(f"[l0-to-l1b] no cal-DB under {caldb} "
                         "(run build-l0-synth or build-caldb first)")
    import zarr
    bands = sorted(zarr.open_group(str(oc[-1]), mode="r")["measurements/detector"].array_keys())
    l1b = run_processor(str(oc[-1]), str(caldb))
    refl = {}
    stats = {}
    for b in bands:
        r = np.asarray(l1b[f"measurements/reflectance/{b}"].data)
        refl[b] = r
        stats[b] = {"min": float(np.nanmin(r)), "max": float(np.nanmax(r)),
                    "mean": float(np.nanmean(r))}
        print(f"[l0-to-l1b] {b}: min={stats[b]['min']:.4f} max={stats[b]['max']:.4f} "
              f"mean={stats[b]['mean']:.4f}")
    l1b_path = write_l1b(l1b, store["l1b"])
    ql = quicklook.save_rgb(refl, store["quicklook"] / "l1b_rgb.png", upscale=4)
    _jdump({"l1b": l1b_path, "reflectance": stats}, store["report"] / "l0_to_l1b.json")
    print(f"[l0-to-l1b] L1B product → {l1b_path}\n            L1B quicklook → {ql}")


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
    """Per-detector-column relative response from a granule (robust, DC-normalised to 1.0)."""
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


def phase_derive_adf(store: dict[str, Path], args) -> None:
    """Real per-detector PRNU (+ dark from a dark-calibration granule) → ``.npz`` for
    :meth:`s2_msi_raw_generator.adf.BandADF.from_product` (alternative to the GIPP path)."""
    src = args.l1a or os.environ.get("S2_E2ES_L1A")
    if not src:
        raise SystemExit("[derive-adf] needs --l1a (a real L1A/L1B .zarr[.zip])")
    sl = slice(0, args.lines or 2048)
    tables: dict[str, np.ndarray] = {}
    for det in _parse_detectors(args.detectors):
        for bn in args.bands:
            try:
                frame = gio.read_l1b_band(src, det, bn, lines=sl)
            except Exception as exc:  # noqa: BLE001 - skip missing det/band gracefully
                print(f"[derive-adf] skip d{det:02d}/{bn}: {exc}")
                continue
            tables[f"{det:02d}_{bn}_prnu"] = derive_column_prnu(frame)
            if args.dark:  # only from a dark-calibration granule (L1 ATBD §4.1.1.2.1)
                try:
                    dark_frame = gio.read_l1b_band(args.dark, det, bn, lines=sl)
                    tables[f"{det:02d}_{bn}_dark"] = derive_column_dark(dark_frame)
                except Exception as exc:  # noqa: BLE001
                    print(f"[derive-adf] d{det:02d}/{bn}: no dark ({exc})")
    out = store["inputs"] / "real_prnu_dark.npz"
    np.savez_compressed(out, **tables)
    has_dark = any(k.endswith("_dark") for k in tables)
    print(f"[derive-adf] wrote {out} ({len(tables)} arrays; "
          f"dark={'real' if has_dark else 'NOT derived — pass a --dark granule'})")


def _snr_db(a: np.ndarray) -> float:
    s = float(np.std(a))
    return float("inf") if s == 0 else 20.0 * float(np.log10(np.mean(a) / s))


def _entropy_bits_f(a: np.ndarray) -> float:
    """First-order Shannon entropy (bits/px) of an integer-quantized array (float-safe)."""
    v = np.round(np.asarray(a, dtype=np.float64)).astype(np.int64).ravel()
    v -= v.min()
    counts = np.bincount(v)
    p = counts[counts > 0] / v.size
    return float(-(p * np.log2(p)).sum())


def _save_gray(a: np.ndarray, path, upscale: int = 1) -> str:
    return quicklook.save_rgb({"r": a, "g": a, "b": a}, path, rgb=("r", "g", "b"),
                              upscale=upscale)


def _stage_row(name: str, a: np.ndarray) -> str:
    return (f"| {name} | {a.min():.1f} | {a.max():.1f} | {a.mean():.1f} | "
            f"{a.std():.2f} | {_snr_db(a):.1f} | {_entropy_bits_f(a):.2f} |")


def phase_figures(store: dict[str, Path], args) -> None:
    """Single-band stage-by-stage README/docs figures + quality metrics (real L1B input).

    Runs the reverse chain step by step on one band/detector of a real L1B and writes the
    three stage images (+ zoom crops + impressed-noise field) and a markdown metrics table.
    Each image is percentile-stretched independently (2–98 %) so the *texture* differences
    (PSF blur, PRNU striping, noise speckle) are what changes between panels.
    """
    src = args.fig_l1b or os.environ.get("S2_E2ES_L1B")
    if not src:
        print("[figures] skipped (needs --fig-l1b, a real L1B .zarr[.zip])")
        return
    b = sensor.band(args.fig_band)
    radiance = gio.read_l1b_band(src, args.fig_detector, args.fig_band,
                                 lines=slice(args.fig_line_start,
                                             args.fig_line_start + args.fig_lines))
    n_lines, n_det = radiance.shape

    gipp_dir = args.gipp or os.environ.get("S2_E2ES_GIPP_DIR")
    if gipp_dir:
        from s2_msi_raw_generator import gipp as gipp_mod
        gs = gipp_mod.load_gipp_set(gipp_dir)
        a = adfmod.BandADF.from_gipp(b, args.fig_detector, gs, active_width=n_det)
        adf_kind = "real operational GIPP (per-pixel dark + relative response)"
    else:
        a = adfmod.synthesize(b, n_det=n_det, seed=2026)
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

    out = Path(args.fig_out) if args.fig_out else store["figures"]
    out.mkdir(parents=True, exist_ok=True)
    tag = args.fig_band.lower()
    _save_gray(x_ideal, out / f"result_{tag}_original.png")
    _save_gray(x_fx, out / f"result_{tag}_effects.png")
    _save_gray(np.asarray(x_raw, dtype=np.float64), out / f"result_{tag}_raw.png")
    _save_gray(noise_delta, out / f"result_{tag}_delta.png")
    cy, cx, cs = args.fig_zoom_line, args.fig_zoom_col, args.fig_zoom_size
    for name, arr in (("original", x_ideal), ("effects", x_fx),
                      ("raw", np.asarray(x_raw, dtype=np.float64))):
        _save_gray(arr[cy:cy + cs, cx:cx + cs], out / f"result_{tag}_{name}_zoom.png", upscale=2)

    # Quality metrics.
    sigma_measured = float(np.std(noise_delta / a.eq_gain[np.newaxis, :]))
    dn_signal = reverse.s7_impress_relative_response(x_blur, a.prnu_gain)
    sigma_model = float(np.mean(np.sqrt(a.noise_a**2 + a.noise_b * np.clip(dn_signal, 0, None))))
    unsat = (x_fx >= 0.0) & (x_fx <= float(sensor.DN_MAX))
    sat_frac = float(1.0 - unsat.mean())
    q_rmse = float(np.sqrt(np.mean(((np.asarray(x_raw, dtype=np.float64) - x_fx)[unsat]) ** 2)))
    rec = reverse.forward_radiometric(np.asarray(x_raw, dtype=np.float64), a)
    rt_err = (rec - radiance)[unsat]
    rt_rmse = float(np.sqrt(np.mean(rt_err ** 2)))
    rt_bias = float(np.mean(rt_err))
    peak = float(radiance[unsat].max())
    rt_psnr = 20.0 * float(np.log10(peak / rt_rmse)) if rt_rmse > 0 else float("inf")
    blur_rmse = float(np.sqrt(np.mean((x_blur - x_ideal) ** 2)))

    print(f"[figures] {os.path.basename(src)}  band={args.fig_band} "
          f"d{args.fig_detector:02d} lines={n_lines} cols={n_det}\n"
          f"[figures] ADFs: {adf_kind}\n[figures] out: {out}\n")
    print("| Stage | DN min | DN max | mean | std | SNR (dB) | entropy (bits/px) |")
    print("|---|---|---|---|---|---|---|")
    print(_stage_row("original — ideal DN (S1)", x_ideal))
    print(_stage_row("effects impressed (S6–S13)", x_fx))
    print(_stage_row("RAW L0 DN (S14, uint16)", np.asarray(x_raw, dtype=np.float64)))
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
            eq = gs.band(bn).detectors[DETECTOR]      # GIPP forward/reverse round-trip pattern
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
    ap.add_argument("store", help="data-store root (e.g. ~/data-store on the SDE, or data/output)")
    ap.add_argument("--phases", default=None,
                    help=f"comma list from {PHASES} (default: the real chain, "
                         "or the synthetic chain with --synthetic)")
    ap.add_argument("--synthetic", action="store_true",
                    help="default to the synthetic flat-field chain "
                         f"({','.join(SYNTH_PHASES)}) instead of the real chain")
    ap.add_argument("--l1a", default=None, help="override L1A path (else store download / $S2_E2ES_L1A)")
    ap.add_argument("--dark", default=None, help="dark-calibration granule for derive-adf")
    ap.add_argument("--gipp", default=None, help="GIPP dir (radiometric-vv / figures phases)")
    ap.add_argument("--bands", default=",".join(sensor.BANDS))
    ap.add_argument("--detectors", default="1-12", help="detector list for derive-adf")
    ap.add_argument("--lines", type=int, default=0, help="window: first N lines (0 = full)")
    ap.add_argument("--band-groups", type=int, default=1, dest="band_groups")
    ap.add_argument("--max-payload", type=int, default=isp.DEFAULT_MAX_PAYLOAD, dest="max_payload")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--caldb-n-det", type=int, default=400, dest="caldb_n_det")
    ap.add_argument("--store-decoded", default="yes", choices=("yes", "no"), dest="store_decoded_s")
    # data-store sync (ipf/data-store registry)
    ap.add_argument("--publish-name", default="products", dest="publish_name")
    ap.add_argument("--publish-version", default=None, dest="publish_version",
                    help="immutable package version for publish-store (required by the phase)")
    ap.add_argument("--publish-layer", default="products", choices=("products", "inputs"),
                    dest="publish_layer")
    ap.add_argument("--publish-source", default="run_pipeline publish-store",
                    dest="publish_source")
    # figures phase
    ap.add_argument("--fig-l1b", default=None, dest="fig_l1b",
                    help="real L1B .zarr[.zip] for the figures phase (or $S2_E2ES_L1B)")
    ap.add_argument("--fig-band", default="B04", dest="fig_band")
    ap.add_argument("--fig-detector", type=int, default=7, dest="fig_detector")
    ap.add_argument("--fig-line-start", type=int, default=8450, dest="fig_line_start")
    ap.add_argument("--fig-lines", type=int, default=650, dest="fig_lines")
    ap.add_argument("--fig-zoom-line", type=int, default=0, dest="fig_zoom_line")
    ap.add_argument("--fig-zoom-col", type=int, default=0, dest="fig_zoom_col")
    ap.add_argument("--fig-zoom-size", type=int, default=256, dest="fig_zoom_size")
    ap.add_argument("--fig-out", default=None, dest="fig_out",
                    help="figures output dir (default: <store>/figures; the committed set "
                         "lives in docs/_static/showcase)")
    args = ap.parse_args(argv)
    args.bands = [b.strip().upper() for b in args.bands.split(",") if b.strip()]
    args.line_slice = slice(0, args.lines) if args.lines else None
    args.store_decoded = args.store_decoded_s == "yes"

    store = _store_paths(Path(os.path.expanduser(args.store)))
    default_phases = SYNTH_PHASES if args.synthetic else REAL_PHASES
    todo = [p.strip() for p in (args.phases or ",".join(default_phases)).split(",") if p.strip()]
    unknown = [p for p in todo if p not in PHASES]
    if unknown:
        ap.error(f"unknown phases: {unknown} (choose from {PHASES})")
    fns = {
        "fetch-store": phase_fetch_store, "publish-store": phase_publish_store,
        "fetch-l1a": phase_fetch_l1a, "fetch-l0": phase_fetch_l0, "preflight": phase_preflight,
        "build-caldb": phase_build_caldb, "build-l0-synth": phase_build_l0_synth,
        "package": phase_package, "ground-decode": phase_ground_decode,
        "l0-decode": phase_l0_decode, "validate": phase_validate,
        "l0-to-l1b": phase_l0_to_l1b, "radiometric-vv": phase_radiometric_vv,
        "derive-adf": phase_derive_adf, "scan-l0": phase_scan_l0,
        "quicklook": phase_quicklook, "figures": phase_figures, "report": phase_report,
    }
    for p in PHASES:
        if p in todo:
            fns[p](store, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

    fetch-l1a fetch-l0 import-l0 preflight package ground-decode l0-decode validate
    radiometric-vv scan-l0 quicklook report

**Calibration mode** (the ``calibration`` positional; REQ-FUNC-048). Synthesizes the
calibration campaign — a dark acquisition (CSM closed / deep space; ``DASC``) and a
Lambertian sun-diffuser acquisition (``ABSR``) — and packages each **as a real downlink
L0 product** (CCSDS-122 compressed ISPs, PSFD type codes ``S02MSIDCA`` / ``S02MSISCA``,
operation-mode metadata), then derives the Option-Y cal-DB ADFs from the same frames.
Every calibration product lands under ``<store>/caldb/`` (nominal L0s under ``l0/``)::

    cal-acquire cal-package build-caldb report

**On-demand phases** (never in a default set): ``inventory`` (metadata-only store report),
``import-l0`` (public-L0 same-scene bridge), ``derive-adf`` (real per-detector PRNU/dark from
matched products, → ``BandADF.from_product``), ``figures`` (the single-band stage-by-stage
README/docs figures + quality metrics).

Configuration is environment-only — the CLI takes just the mode::

    S2_DATA_STORE          store root (default ~/data-store)
    S2_E2ES_PHASES         comma phase list (default set follows the mode)
    S2_E2ES_LINES          line window, 0 = full     S2_E2ES_BANDS      band list
    S2_E2ES_SEED           RNG seed                  S2_E2ES_NDET       cal detector width
    S2_E2ES_CAL_LINES      cal lines per frame
    S2_E2ES_JOBS           parallel workers (default: all cores) — CCSDS-122 compress
                           (package/cal-package), ground-decode, S3 fetch threads
    S2_E2ES_L1A  S2_E2ES_PUBLIC_L0  S2_E2ES_IMPORT_DETECTOR            input paths
    S2_E2ES_DARK  S2_E2ES_GIPP_DIR  S2_E2ES_L1B
    S2_E2ES_EQOG_ADF       EOPF ADF_REQOG json = ESA NUC source (overrides XML GIPP equalization)
    S2_E2ES_PUBLISH_NAME  S2_E2ES_PUBLISH_VERSION  S2_E2ES_PUBLISH_LAYER  publish-store

Examples::

    python scripts/run_pipeline.py                    # real chain → ~/data-store
    python scripts/run_pipeline.py calibration        # cal campaign → <store>/caldb/
    S2_E2ES_PHASES=preflight,package S2_E2ES_LINES=4096 python scripts/run_pipeline.py
    S2_E2ES_PHASES=figures S2_E2ES_L1B=<L1B.zarr[.zip]> python scripts/run_pipeline.py

The eopf/msi_processor imports are lazy (``ground-decode``/``l0-decode``/``validate``), so
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

from s2_msi_raw_generator import (
    _fsutil,
    _parallel,
    adf as adfmod,
    caldb as caldb_mod,
    ccsds122,
    datation,
    io as gio,
    isp,
    import_l0,
    inventory,
    l0product,
    naming,
    quicklook,
    reverse,
    s3fetch,
    sensor,
)
from s2_msi_raw_generator.adf_writer import BandCal, write_calibration_db

ENDPOINT = "https://dpr-common.s3.sbg.io.cloud.ovh.net"
L1A_PREFIX = "s2-msi-l1-example/PDI_MSI_S2_L1A.zarr/"
# The unpacked PSD L0 SAFE mirror (incl. per-band ISP .bin files) is LISTable but its objects
# return **HTTP 403 on GET** (verified 2026-07-02) — the bucket grants read only on selected
# archives. The accessible real-L0 references are the datastrip PDI tar (metadata + QI) and the
# real **SADATA** tars, whose members are genuine downlinked CCSDS packets — exactly what the
# structural scan needs.
REAL_L0_SAFE_PREFIX = (
    "S2AMSIdataset/S2A_OPER_PRD_MSIL0P_PDMC_20220803T144026_" "R123_V20220803T113642_20220803T113704.SAFE/"
)
REAL_L0_KEYS = [
    "S2AMSIdataset/S2A_OPER_MSI_L0__DS_ATOS_20221111T083024_S20221111T082158_N04.00.tar",
    "S2AMSIdataset/S2A_OPER_AUX_SADATA_2APS_20241218T042947_" "V20241218T034819_20241218T041652_A049565_WP_LN.tar",
    "S2AMSIdataset/S2A_OPER_AUX_SADATA_2APS_20241218T074251_" "V20241218T070943_20241218T072345_A049567_WP_LN.tar",
]
DETECTOR = 1  # the example PDI L1A carries DD01 only
# Bands grouped by ground resolution: line counts differ per resolution in a real product
# (10 m = 2× the 20 m, 6× the 60 m line count), and a persisted EOPF product must not mix
# 'line' sizes in one group (PSFD: different resolutions use different dimensions) — so
# l0_decode + persist run per resolution group.
RES_GROUPS = {
    "r10m": ["B02", "B03", "B04", "B08"],
    "r20m": ["B05", "B06", "B07", "B8A", "B11", "B12"],
    "r60m": ["B01", "B09", "B10"],
}
PHASES = [
    "fetch-store",
    "fetch-l1a",
    "fetch-l0",
    "import-l0",
    "preflight",
    "cal-acquire",
    "cal-package",
    "build-caldb",
    "package",
    "reverse-l1b",
    "ground-decode",
    "l0-decode",
    "validate",
    "radiometric-vv",
    "derive-adf",
    "scan-l0",
    "quicklook",
    "figures",
    "report",
    "publish-store",
    "inventory",
]
#: Default phase sets per --mode: the nominal (real-data) chain and the calibration campaign.
NOMINAL_PHASES = [
    "fetch-l1a",
    "fetch-l0",
    "preflight",
    "package",
    "ground-decode",
    "l0-decode",
    "validate",
    "radiometric-vv",
    "scan-l0",
    "quicklook",
    "report",
]
CALIBRATION_PHASES = ["cal-acquire", "cal-package", "build-caldb", "report"]

#: Baked-in run defaults so the pipeline runs with a bare
#: ``python scripts/run_pipeline.py [nominal|calibration]`` — no shell ``export`` needed.
#: Paths hang off ``~/data-store`` (the store symlink in $HOME), so this works on any machine
#: whose home holds that link. Anything already set in the environment wins, so
#: ``export S2_E2ES_GIPP_DIR=...`` (etc.) still overrides a value here for a one-off run.
_LOCAL_STORE = Path.home() / "data-store"
LOCAL_ENV_DEFAULTS: dict[str, str] = {
    "S2_DATA_STORE": str(_LOCAL_STORE),
    "S2_E2ES_GIPP_DIR": str(_LOCAL_STORE / "inputs/s2-sensor/GIPP"),
    "S2_E2ES_PUBLIC_L0": str(
        _LOCAL_STORE / "inputs/public-data/level-0/S02MSIL0__20230216T182840_0001_A123_T000.zarr.zip"
    ),
    "S2_E2ES_IMPORT_DETECTOR": "1",
    "S2_E2ES_JOBS": "16",
}


def _eqog_adf_path(args) -> str | None:
    """Optional EOPF ``ADF_REQOG`` json = ESA-provided NUC source (dark + PRNU) for the reverse chain.

    Selected via ``S2_E2ES_EQOG_ADF`` (or ``args.eqog_adf``). When set to an existing file, the
    equalization is read from this ESA ADF instead of the XML GIPP (see ``gipp.load_gipp_set``);
    returns ``None`` (→ XML GIPP) when unset or the path is missing.
    """
    p = getattr(args, "eqog_adf", None) or os.environ.get("S2_E2ES_EQOG_ADF")
    return p if (p and os.path.exists(p)) else None


def _full_reverse_adf(args, env_var: str, adf_type: str) -> str | None:
    """Locate an EOPF ADF json for the full reverse chain (RSWIR / REOB2 / RCRCO).

    ``env_var`` override first, else auto-find ``S0*_ADF_<adf_type>_*.json`` alongside the
    ADF_REQOG (same ``adf-eopf`` directory). Returns ``None`` when nothing is found → the step is
    skipped and the reverse falls back to the radiometric-only chain.
    """
    import glob

    p = os.environ.get(env_var)
    if p and os.path.exists(p):
        return p
    eqog = _eqog_adf_path(args)
    if not eqog:
        return None
    hits = sorted(glob.glob(os.path.join(os.path.dirname(eqog), f"S0*_ADF_{adf_type}_*.json")))
    return hits[0] if hits else None


def _reverse_crosstalk(sig_by_band: dict[str, np.ndarray], matrix) -> dict[str, np.ndarray]:
    """S9 (reverse) — add inter-band crosstalk back within same-resolution groups.

    For each impacted band ``k``, ``X_k += Σ_l dtalk[k,l]·X_l`` over same-shape neighbours ``l``
    (``matrix`` = RCRCO ``dtalk`` in ``sensor.BANDS`` order). Cross-resolution pairs (which the
    forward resamples) are skipped. ≈0 for S2A/B, so this is effectively a no-op kept for
    completeness. Returns a new dict; the input is left unchanged.
    """
    if matrix is None:
        return sig_by_band
    from collections import defaultdict

    idx = {b: i for i, b in enumerate(sensor.BANDS)}
    groups: dict[tuple, list[str]] = defaultdict(list)
    for b, arr in sig_by_band.items():
        groups[arr.shape].append(b)
    out = dict(sig_by_band)
    for members in groups.values():
        if len(members) < 2:
            continue
        for k in members:
            add = np.zeros(sig_by_band[k].shape, dtype=np.float64)
            for other in members:
                if other == k:
                    continue
                c = float(matrix[idx[k], idx[other]])
                if c:
                    add = add + c * sig_by_band[other]
            if add.any():
                out[k] = sig_by_band[k] + add
    return out


#: Default phase chain applied for ``nominal`` mode only (the public-L0 same-scene bridge +
#: inventory alongside the standard package/decode/validate chain).
LOCAL_NOMINAL_PHASES = "import-l0,preflight,package,ground-decode,l0-decode,validate," "radiometric-vv,inventory,report"

_SENTINEL_SATURATED = 32768  # IF-IN-L1A saturation sentinel in the real product


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
    # S2_E2ES_L0_DIR re-homes the produced-L0 directory outside the work store (e.g. the curated
    # data-store's synthetic-raw-generated/outputs/L0). Every phase that writes or reads packaged
    # L0 resolves it through p["l0"], so the single override moves producer and consumers together.
    if os.environ.get("S2_E2ES_L0_DIR"):
        p["l0"] = Path(os.environ["S2_E2ES_L0_DIR"]).expanduser()
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
    man = s3fetch.fetch_prefix(
        ENDPOINT,
        L1A_PREFIX,
        dest / "PDI_MSI_S2_L1A.zarr",
        strip_prefix=L1A_PREFIX,
        jobs=args.jobs,
    )
    s3fetch.save_manifest(man, store["report"] / "fetch_l1a_manifest.json")
    print(f"[fetch-l1a] {man['n_objects']} objects, {man['total_bytes']/1e6:.1f} MB")


def phase_fetch_l0(store: dict[str, Path], args) -> None:
    """Fetch the accessible real-L0 references (DS + SADATA tars; the SAFE mirror is GET-403)."""
    dest = store["inputs"] / "real_l0"
    results, total = [], 0
    for key in REAL_L0_KEYS:
        try:
            man = s3fetch.fetch_prefix(ENDPOINT, key, dest, strip_prefix="S2AMSIdataset/", jobs=1)
            results.append(man)
            total += man["total_bytes"]
        except RuntimeError as exc:  # keep going; report what failed
            results.append({"prefix": key, "error": str(exc)})
    s3fetch.save_manifest(
        {
            "targets": results,
            "safe_prefix_status": f"{REAL_L0_SAFE_PREFIX} objects return HTTP 403 on GET "
            "(bucket policy; verified 2026-07-02)",
        },
        store["report"] / "fetch_l0_manifest.json",
    )
    print(f"[fetch-l0] {len(REAL_L0_KEYS)} real-L0 references, {total/1e6:.1f} MB → {dest}")


def _default_public_l0(store: dict[str, Path]) -> Path | None:
    candidates = sorted(
        (store["inputs"] / "public-data" / "level-0").glob("S02MSIL0__*.zarr.zip"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def phase_import_l0(store: dict[str, Path], args) -> None:
    """Import a public distribution L0 image product as the same-scene pipeline L1A input."""
    src = Path(args.public_l0) if args.public_l0 else _default_public_l0(store)
    if src is None:
        raise SystemExit("[import-l0] needs $S2_E2ES_PUBLIC_L0 or " "inputs/public-data/level-0/S02MSIL0__*.zarr.zip")
    report = import_l0.convert(
        src,
        store["inputs"],
        detector=args.import_detector,
        bands=args.bands,
        jobs=args.jobs,
    )
    _jdump(report, store["report"] / "import_l0.json")
    os.environ["S2_E2ES_L1A"] = report["output"]
    args.l1a = report["output"]
    print(f"[import-l0] d{args.import_detector:02d} {len(report['bands'])} bands → " f"{report['output']}")


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
            "min": int(dn.min()),
            "max": int(dn.max()),
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
    acq = naming.acquisition_context(attrs)
    l0_name, info = naming.from_l1a_context(
        attrs, n_lines=n_lines, line_period_s=line_period_s, product_type="S02MSIL0_"
    )
    l1ap_name, _ = naming.from_l1a_context(
        attrs, n_lines=n_lines, line_period_s=line_period_s, product_type="S02MSIL1A"
    )
    parsed = naming.parse_psfd_name(l0_name)
    _jdump(
        {
            "l1a_path": l1a,
            "bands": bands,
            "n_lines": n_lines,
            "bit_depth": bit_depth,
            "pixel_bit_depth": bit_depth,
            "per_band": per_band,
            "product_names": {
                "l0": l0_name,
                "l0_oc": naming.psfd_name(
                    "S02MSIL0_",
                    parsed["start_utc"],
                    parsed["duration_s"],
                    unit=parsed["unit"],
                    relative_orbit=parsed["relative_orbit"],
                    z_suffix="OC",
                ),
                "l1a_prime": l1ap_name,
            },
            "naming_fallbacks": info.get("derived_from_defaults", []),
            "start_utc": parsed["start_utc"],
            "relative_orbit": parsed["relative_orbit"],
            "unit": parsed["unit"],
            "platform": acq["platform"],
            "orbit": {
                "relative_orbit": acq["relative_orbit"],
                "absolute_orbit": acq["absolute_orbit"],
                "orbit_state": acq["orbit_state"],
            },
            "orbit_fallbacks": acq.get("orbit_derived_from_defaults", []),
        },
        store["report"] / "preflight.json",
    )
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
    frames = {
        (DETECTOR, bn): gio.read_l1a_raw(l1a, DETECTOR, bn, lines=args.line_slice, dtype=np.uint16)
        for bn in pre["bands"]
    }
    out = str(store["l0"] / pre["product_names"]["l0"])
    l0product.write_l0_product(
        out,
        frames,
        datation=d,
        with_isp=True,
        isp_max_payload=args.max_payload,
        store_decoded=args.store_decoded,
        platform=pre.get("platform", "Sentinel-2A"),
        orbit=pre.get("orbit"),
        jobs=args.jobs,
    )
    del frames
    print(f"[package] canonical L0 → {out}")


def _l1b_props(attrs: dict) -> dict:
    """STAC properties of an EOPF L1B product (tolerant to the nested ``stac_discovery`` layouts)."""
    sd = attrs.get("stac_discovery", {})
    if isinstance(sd, dict):
        p = sd.get("properties")
        if not isinstance(p, dict):
            p = sd.get("stac_discovery", {}).get("properties", {}) if isinstance(sd.get("stac_discovery"), dict) else {}
        if isinstance(p, dict):
            return p
    return {}


def _l1b_platform(props: dict) -> str:
    p = str(props.get("platform", "sentinel-2a")).lower()
    return "Sentinel-2B" if "2b" in p else ("Sentinel-2C" if "2c" in p else "Sentinel-2A")


def _reinsert_blind(active: np.ndarray, blind_cols, fill: int) -> np.ndarray:
    """S10 (blind side): put the active columns back at their non-blind positions in the physical
    frame, filling BLINDP's blind columns with the dark level. Best-effort — returns ``active``
    unchanged if the BLINDP indices are absent or inconsistent with the active width."""
    if blind_cols is None or len(blind_cols) == 0:
        return active
    blind = np.asarray(blind_cols, dtype=int)
    phys_w = active.shape[1] + blind.size
    if blind.size and blind.max() >= phys_w:
        return active
    keep = np.setdiff1d(np.arange(phys_w), blind)
    if keep.size != active.shape[1]:
        return active
    out = np.full((active.shape[0], phys_w), fill, dtype=active.dtype)
    out[:, keep] = active
    return out


def phase_reverse_l1b(store: dict[str, Path], args) -> None:
    """``reverse-l1b`` — real L1B digital counts → L0 raw, the vault-canonical inverse of the full
    L0→L1B radiometric chain in the downlink DN domain (``forward_radiometric_atbd.reverse_l1b_to_l0``).

    Inverts every ON forward step: remove the R2PARA offset (S4), impress the relative response
    (R2EQOG cubic/bilinear, S7), re-apply the on-board equalization non-linearity (REOB2, S12),
    add the L0-domain dark (``sensor.L0_DARK_LSB`` × R2EQOG DSNU shape, S11), un-bin 60 m (S5),
    re-introduce the SWIR staggered readout (RSWIR, S8), re-stamp defective columns (R2DEPI, S10),
    add inter-band crosstalk back (RCRCO, S9 — phase-level, same-resolution groups), re-insert blind
    columns (BLINDP), then CCSDS-122 + ISP package (S15). MTF restoration/deconvolution (forward
    step 8) is off in the operational chain, so PSF/noise are NOT re-applied (see DPM). The S8/S9/S10/
    S12 ADFs are auto-found next to the ADF_REQOG (or ``$S2_E2ES_{RSWIR,REOB2,RCRCO}_ADF``); set
    ``S2_E2ES_REVERSE_FULL=0`` for the radiometric-only reverse. Detectors via
    ``$S2_E2ES_L1B_DETECTORS`` (default ``5``); bands via ``args.bands``.
    """
    import zarr

    from s2_msi_raw_generator import forward_radiometric_atbd as fwd, gipp as gipp_mod

    src = os.environ.get("S2_E2ES_L1B")
    if not src:
        print("[reverse-l1b] skipped (needs $S2_E2ES_L1B, a real L1B .zarr[.zip])")
        return
    gipp_dir = args.gipp or os.environ.get("S2_E2ES_GIPP_DIR")
    if not gipp_dir:
        raise SystemExit("[reverse-l1b] needs $S2_E2ES_GIPP_DIR")
    eqog = _eqog_adf_path(args)
    full = str(os.environ.get("S2_E2ES_REVERSE_FULL", "1")).lower() not in ("0", "false", "no")
    rswir_adf = _full_reverse_adf(args, "S2_E2ES_RSWIR_ADF", "RSWIR") if full else None
    reob2_adf = _full_reverse_adf(args, "S2_E2ES_REOB2_ADF", "REOB2") if full else None
    rcrco_adf = _full_reverse_adf(args, "S2_E2ES_RCRCO_ADF", "RCRCO") if full else None
    gs = gipp_mod.load_gipp_set(gipp_dir, bands=tuple(args.bands), eqog_adf=eqog,
                                rswir_adf=rswir_adf, reob2_adf=reob2_adf, rcrco_adf=rcrco_adf)
    print(f"[reverse-l1b] full chain: S8(SWIR)={'on' if rswir_adf else 'off'} "
          f"S12(onboard-eq)={'on' if reob2_adf else 'off'} S9(crosstalk)={'on' if rcrco_adf else 'off'}")
    try:
        offsets = gipp_mod.read_r2para(gipp_dir).radiance_offset_l1b
    except Exception:  # R2PARA optional — fall back to the sensor constant
        offsets = {}
    detectors = [int(d) for d in str(os.environ.get("S2_E2ES_L1B_DETECTORS", "5")).split(",") if d.strip()]
    l0_dark = sensor.L0_DARK_LSB
    props = _l1b_props(dict(zarr.open_group(src, mode="r").attrs))
    start = props.get("start_datetime") or props.get("datetime")
    d = datation.Datation(epoch_utc=start) if start and start != "null" else datation.Datation()
    platform = _l1b_platform(props)

    frames: dict[tuple[int, str], np.ndarray] = {}
    applied: set[str] = set()
    for det in detectors:
        # read every band for this detector, then undo inter-band crosstalk (S9) as a group
        l1b_by_band = {bn: gio.read_l1b_band(src, det, bn, lines=args.line_slice).astype(np.float64)
                       for bn in args.bands}
        if gs.crosstalk_matrix is not None:
            l1b_by_band = _reverse_crosstalk(l1b_by_band, gs.crosstalk_matrix)
            applied.add("S9-crosstalk")
        for bn in args.bands:
            eq = gs.band(bn).detectors[det]
            off = float(offsets.get(bn, sensor.RADIO_ADD_OFFSET_L1B))
            factor = 3 if bn in RES_GROUPS["r60m"] else 1
            swir_shift = gs.swir_shift(bn, det)
            onboard = gs.onboard_eq(bn, det)
            defcols = gs.defective.get(bn, {}).get(det)
            active = fwd.reverse_l1b_to_l0(
                l1b_by_band[bn], eq, radio_offset_l1b=off, l0_dark_level=l0_dark,
                unbin_factor=factor, swir_shift=swir_shift, defective_cols=defcols, onboard_eq=onboard)
            raw = _reinsert_blind(active, gs.blind.get(bn, {}).get(det), int(round(l0_dark)))
            frames[(det, bn)] = raw
            tags = []
            if swir_shift is not None:
                tags.append("+S8"); applied.add("S8-swir")
            if onboard is not None:
                tags.append("+S12"); applied.add("S12-onboard-eq")
            if defcols is not None and len(defcols):
                tags.append(f"+S10({len(defcols)})"); applied.add("S10-defective")
            print(
                f"[reverse-l1b] d{det:02d} {bn} ({eq.model}): L1B {tuple(l1b_by_band[bn].shape)} → "
                f"L0 {tuple(raw.shape)} offset{off:+.0f} unbin×{factor} {' '.join(tags)}"
            )
    stamp = str(start or "unknown").replace("-", "").replace(":", "")[:15]
    l0_dir = Path(os.environ["S2_E2ES_L0_DIR"]).expanduser() if os.environ.get("S2_E2ES_L0_DIR") else store["l0"]
    l0_dir.mkdir(parents=True, exist_ok=True)
    out = str(l0_dir / f"S02MSIL0__{stamp}_reverse.zarr")
    l0product.write_l0_product(
        out,
        frames,
        datation=d,
        with_isp=True,
        isp_max_payload=args.max_payload,
        store_decoded=args.store_decoded,
        platform=platform,
        jobs=args.jobs,
    )
    _jdump(
        {
            "source_l1b": src,
            "platform": platform,
            "detectors": detectors,
            "bands": list(args.bands),
            "n_frames": len(frames),
            "l0_dark_lsb": l0_dark,
            "radio_offset_l1b": {bn: float(offsets.get(bn, sensor.RADIO_ADD_OFFSET_L1B)) for bn in args.bands},
            "full_reverse_steps_applied": sorted(applied),
            "adf_sources": {"rswir": rswir_adf, "reob2": reob2_adf, "rcrco": rcrco_adf},
            "restoration_deconvolution": "skipped — off in forward chain (feature_flag_with_deconvolution=False); L1B keeps instrument PSF, no re-blur/re-noise (see DPM)",
            "output": out,
        },
        store["report"] / "reverse_l1b.json",
    )
    print(f"[reverse-l1b] {len(frames)} frames → {out}")


def phase_ground_decode(store: dict[str, Path], args) -> None:
    pre = _jload(store["report"] / "preflight.json")
    l1a = pre["l1a_path"]
    d = _datation_from_preflight(pre)
    canon = str(store["l0"] / pre["product_names"]["l0"])
    # Operational decoder = the CONSUMER's (msi-processor ground_decode — the real-chain
    # L1A-side decompression); the generator's read_l0_isp_dn stays as the E2ES-side
    # reference decoder and cross-checks it when the consumer is importable. The codec's
    # decompression is pure-Python/GIL-bound → bands fan out to worker processes.
    jobs = min(args.jobs, len(pre["bands"]))
    if jobs > 1:
        decoded = _parallel.run_in_process_pool(
            {
                bn: (
                    l0product.decode_verify_band,
                    (canon, DETECTOR, bn, l1a, args.line_slice),
                )
                for bn in pre["bands"]
            },
            jobs,
        )
    else:
        decoded = {bn: l0product.decode_verify_band(canon, DETECTOR, bn, l1a, args.line_slice) for bn in pre["bands"]}
    rt = {}
    band_frames = {}
    for bn in pre["bands"]:
        rec, ok, cross = decoded[bn]
        if cross is False:
            raise SystemExit(f"[ground-decode] {bn}: consumer and reference decoders disagree")
        rt[bn] = {
            "bit_exact": ok,
            "decoder": "msi-processor" if cross is not None else "e2es-reference",
            "decoder_cross_check": cross,
        }
        if not ok:
            raise SystemExit(f"[ground-decode] {bn}: reconstructed DN != original — codec fault")
        band_frames[bn] = rec
        print(
            f"[ground-decode] {bn}: bit-exact OK"
            + (f" (consumer decoder, cross-check {cross})" if cross is not None else "")
        )
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
    l0product.write_l0_opencontainer(
        oc,
        band_frames,
        datation=d,
        platform=pre.get("platform", "Sentinel-2A"),
        orbit=pre.get("orbit"),
    )
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
    # 10 m / 20 m / 60 m line counts).
    groups: list[list[str]] = [[b for b in bands if b in res_bands] for res_bands in RES_GROUPS.values()]
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
        l1a = L0DecodeUnit("l0").run(
            {"l0c": prod},
            bit_depth=pre["bit_depth"],
            max_lost_fraction=0.1,
            name=f"{stem}.g{gi}",
        )["l1a"]
        lost.update(l1a.attrs["other_metadata"]["quality"]["lines_lost"])
        st = EOZarrStore(str(outdir))
        st.open(mode=OpeningMode.CREATE_OVERWRITE, delayed_writing=False)
        try:
            st[f"{stem}.g{gi}"] = l1a
        finally:
            st.close()
        del prod, l1a
        print(f"[l0-decode] group {gi} ({len(grp)} bands) → {outdir}/{stem}.g{gi}.zarr")
    _jdump(
        {"lines_lost": lost, "groups": sum(1 for g_ in groups if g_)},
        store["report"] / "l0_decode.json",
    )


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
            ms = compute_metrics(t2.astype(np.float64), r2.astype(np.float64), bit_depth=pre["bit_depth"])
            res[b] = {
                "bit_identical_kept": bool(np.array_equal(t2, r2)),
                "kept_lines": int(test.shape[0]),
                "lines_lost": int(dec["lines_lost"].get(b, 0)),
                "preflight_zero_tail": pre["per_band"][b]["trailing_zero_lines"],
                "rmse": None if np.isnan(ms.rmse) else float(ms.rmse),
                "psnr": None if np.isnan(ms.psnr) else float(ms.psnr),
            }
            ok = res[b]["bit_identical_kept"] and res[b]["lines_lost"] == res[b]["preflight_zero_tail"]
            print(
                f"[validate] {b}: bit_identical={res[b]['bit_identical_kept']} "
                f"lost={res[b]['lines_lost']} (preflight {res[b]['preflight_zero_tail']}) "
                f"rmse={res[b]['rmse']}"
            )
            if not ok:
                res[b]["verdict"] = "KO"
    _jdump(res, store["report"] / "validate.json")
    n_ok = sum(1 for r in res.values() if r["bit_identical_kept"])
    print(f"[validate] bit-identical bands: {n_ok}/{len(res)}")


# ---------------------------------------------------------------------------
# data-store sync (ipf/data-store: registry = DB, local store = working copy)
# ---------------------------------------------------------------------------

DATASTORE_API = "https://gitlab.eopf.copernicus.eu/api/v4/projects/ipf%2Fdata-store" "/packages/generic"
DATASTORE_PACKAGES_API = "https://gitlab.eopf.copernicus.eu/api/v4/projects/ipf%2Fdata-store" "/packages"


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

    Packages are immutable versions (``S2_E2ES_PUBLISH_NAME``/``_VERSION``); only the
    ``manifest/latest`` entry is replaced in place. The "git push" of the data DB.
    """
    if not args.publish_version:
        raise SystemExit("[publish-store] needs S2_E2ES_PUBLISH_VERSION (immutable package version)")
    name, version = args.publish_name, args.publish_version
    headers = _store_auth_headers()
    root = store["report"].parent
    stage = root / ".publish-stage"
    stage.mkdir(exist_ok=True)

    entries = []
    if args.publish_layer == "inputs":
        # auxiliary inputs (e.g. the operational GIPP) live under inputs/; products the
        # pipeline can re-fetch itself (bucket .zarr, real_l0 tars) stay external
        for d in (sorted((root / "inputs").iterdir()) if (root / "inputs").is_dir() else []):
            if d.name.endswith(".zarr") or d.name == "real_l0":
                continue
            if d.is_dir() and any(d.iterdir()):
                zp = stage / f"{d.name}.zip"
                _fsutil.zip_dir(d, zp, base="parent")
                entries.append((zp, f"inputs/{d.name}.zip"))
    else:
        # product zarr dirs → PSFD .zarr.zip; plain dirs (caldb/quicklook/…) → dir.zip
        for sub in ("l0", "l1a_prime", "l1b"):
            for z in sorted((root / sub).glob("*.zarr")):
                zp = stage / f"{z.name}.zip"
                _fsutil.zip_dir(z, zp, base="parent")
                entries.append((zp, f"{sub}/{z.name}.zip"))
        for sub in ("caldb", "quicklook", "report", "figures"):
            d = root / sub
            if d.is_dir() and any(d.iterdir()):
                zp = stage / f"{sub}.zip"
                _fsutil.zip_dir(d, zp, base="parent")
                entries.append((zp, f"{sub}.zip"))
    if not entries:
        raise SystemExit(f"[publish-store] nothing to publish under {root}")

    files = []
    for zp, rel in entries:
        flat = rel.replace("/", "__")
        _http(
            f"{DATASTORE_API}/{name}/{version}/{flat}",
            headers=headers,
            method="PUT",
            data=zp.read_bytes(),
        )
        files.append(
            {
                "file": flat,
                "path": rel,
                "sha256": _sha256_file(zp),
                "bytes": zp.stat().st_size,
            }
        )
        print(f"[publish-store] {name}/{version}: {flat} ({zp.stat().st_size/1e6:.1f} MB)")

    # merge into the manifest and replace manifest/latest atomically (delete old package first)
    try:
        manifest = json.loads(_http(f"{DATASTORE_API}/manifest/latest/manifest.json").decode())
    except Exception:  # noqa: BLE001 - first publish ever
        manifest = {"schema": 1, "packages": [], "external": []}
    manifest["packages"] = [p for p in manifest["packages"] if not (p["name"] == name and p["version"] == version)]
    manifest["packages"].append(
        {
            "name": name,
            "version": version,
            "layer": args.publish_layer,
            "files": files,
            "source": args.publish_source,
        }
    )
    pkgs = json.loads(_http(f"{DATASTORE_PACKAGES_API}?package_name=manifest", headers=headers).decode())
    for p in pkgs:
        if p.get("version") == "latest":
            _http(f"{DATASTORE_PACKAGES_API}/{p['id']}", headers=headers, method="DELETE")
    _http(
        f"{DATASTORE_API}/manifest/latest/manifest.json",
        headers=headers,
        method="PUT",
        data=json.dumps(manifest, indent=2).encode(),
    )
    print(f"[publish-store] manifest updated — {len(manifest['packages'])} packages")


def phase_inventory(store: dict[str, Path], args) -> None:
    """Write metadata-only inventory and consistency reports for the data store."""
    del args
    payload = inventory.write_outputs(store["report"].parent)
    print(
        f"[inventory] {len(payload['records'])} items, {len(payload['findings'])} findings → "
        f"{store['report'].parent/'INVENTORY.md'}"
    )


# ---------------------------------------------------------------------------
# calibration campaign (REQ-FUNC-048) + on-demand phases
# ---------------------------------------------------------------------------


def phase_cal_acquire(store: dict[str, Path], args) -> None:
    """Synthesize the calibration-campaign acquisitions per band (dark + sun-diffuser).

    Dark = CSM-closed / deep-space datatake (zero radiance through the full instrument
    model); flat = Lambertian sun-diffuser datatake at ``DIFFUSER_LEVEL_FACTOR·Lref``.
    Frames are quantized 12-bit DN (integer-valued, clip-free at this level).
    """
    from s2_msi_raw_generator import adf as adfmod, calibration

    acq: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    summary = {}
    for bn in args.bands:
        b = sensor.band(bn)
        truth = adfmod.synthesize(b, n_det=args.n_det, seed=args.seed)
        rng = np.random.default_rng(args.seed + sensor.BANDS.index(bn))
        l_diff = calibration.DIFFUSER_LEVEL_FACTOR * b.lref
        dark = calibration.synth_dark_acquisition(truth, args.cal_lines, rng)
        flat = calibration.synth_diffuser_acquisition(truth, l_diff, args.cal_lines, rng)
        acq[bn] = (dark, flat)
        summary[bn] = {
            "dark_mean": float(dark.mean()),
            "flat_mean": float(flat.mean()),
            "flat_max": float(flat.max()),
        }
    _ctx_acq[id(store["report"])] = acq
    _jdump(
        {
            "n_det": args.n_det,
            "n_lines": args.cal_lines,
            "bands": args.bands,
            "per_band": summary,
        },
        store["report"] / "cal_acquire.json",
    )
    print(f"[cal-acquire] {len(acq)} bands × (dark + diffuser), " f"{args.cal_lines}×{args.n_det} frames")


#: In-process handoff between the calibration phases (keyed by the run's report dir).
_ctx_acq: dict[int, dict[str, tuple[np.ndarray, np.ndarray]]] = {}


def _cal_names(args) -> dict[str, str]:
    """PSFD names of the campaign products (PSFD §3 type codes DCA/SCA)."""
    dur = args.cal_lines * sensor.LINE_PERIOD_MS / 1e3
    common = dict(unit=naming.DEFAULT_UNIT, relative_orbit=naming.DEFAULT_RELATIVE_ORBIT)
    return {
        "dark": naming.psfd_name("S02MSIDCA", naming.DEFAULT_START, dur, **common),
        "diffuser": naming.psfd_name("S02MSISCA", naming.DEFAULT_START, dur, **common),
    }


def phase_cal_package(store: dict[str, Path], args) -> None:
    """Package the campaign acquisitions as REAL downlink L0 products (compressed ISPs).

    Two canonical L0 products — dark ``S02MSIDCA`` (operation mode ``DASC``) and
    sun-diffuser ``S02MSISCA`` (``ABSR``) — with the same CCSDS-122 + space-packet
    carrier, PSFD naming and metadata as any nominal datatake (ICD-IF-L0-CAL).
    Calibration products live under ``<store>/caldb/`` (nominal L0s under ``l0/``).
    """
    acq = _ctx_acq.get(id(store["report"]))
    if acq is None:
        raise SystemExit("[cal-package] run cal-acquire first (same invocation)")
    names = _cal_names(args)
    d = datation.Datation()
    specs = [
        ("dark", 0, "S2MSIDCA", "DASC", "INS-DASC"),
        ("diffuser", 1, "S2MSISCA", "ABSR", "INS-ABSR"),
    ]
    report = {}
    for kind, idx, eopf_type, op_mode, dt_type in specs:
        frames = {(1, bn): acq[bn][idx].astype(np.uint16) for bn in acq}
        out = str(store["caldb"] / names[kind])
        l0product.write_l0_product(
            out,
            frames,
            datation=d,
            with_isp=True,
            isp_max_payload=args.max_payload,
            store_decoded=args.store_decoded,
            eopf_type=eopf_type,
            operation_mode=op_mode,
            datatake_type=dt_type,
            jobs=args.jobs,
        )
        import zarr

        g = zarr.open_group(out, mode="r")
        n_pkts = sum(int(dict(g[f"measurements/d01/{sensor.zarr_band_key(bn)}"].attrs)["n_packets"]) for bn in acq)
        report[kind] = {
            "product": names[kind],
            "operation_mode": op_mode,
            "datatake_type": dt_type,
            "n_packets": n_pkts,
        }
        ql = {bn: acq[bn][idx] for bn in list(acq)[:1]}
        b0 = next(iter(ql))
        quicklook.save_rgb(
            {"r": ql[b0], "g": ql[b0], "b": ql[b0]},
            store["quicklook"] / f"cal_{kind}_{b0.lower()}.png",
            rgb=("r", "g", "b"),
        )
        print(f"[cal-package] {kind} → {out} ({n_pkts} packets, {op_mode})")
    _jdump(report, store["report"] / "cal_package.json")


def phase_build_caldb(store: dict[str, Path], args) -> None:
    """Option-Y cal-DB ADFs — derived from the campaign acquisitions when present.

    Inside the calibration mode the coefficients come from the very frames just
    packaged as L0 products (:func:`s2_msi_raw_generator.caldb.derive_from_acquisitions`);
    standalone (``S2_E2ES_PHASES=build-caldb``) it synthesizes deterministically-identical
    frames via :func:`s2_msi_raw_generator.caldb.build` — same numbers either way.
    """
    acq = _ctx_acq.get(id(store["report"]))
    if acq is not None:
        from s2_msi_raw_generator.adf_writer import write_calibration_db

        cals = [caldb_mod.derive_from_acquisitions(bn, dark, flat) for bn, (dark, flat) in acq.items()]
        paths = write_calibration_db(store["caldb"], cals)
    else:
        paths = caldb_mod.build(store["caldb"], n_det=args.n_det, seed=args.seed)
    print(f"[build-caldb] {len(paths)} ADFs → {store['caldb']}")


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
    trend = np.array([np.nanmean(padded[i : i + k]) for i in range(n)])
    rel = col_med / trend
    rel[~np.isfinite(rel)] = 1.0
    return rel / np.nanmedian(rel)  # DC gain 1


def derive_column_dark(frame: np.ndarray, pct: float = 1.0) -> np.ndarray:
    """Per-detector dark offset = low percentile per column (DN of the darkest lines)."""
    return np.percentile(np.asarray(frame, dtype=np.float64), pct, axis=0)


def phase_derive_adf(store: dict[str, Path], args) -> None:
    """Real per-detector PRNU (+ dark from a dark-calibration granule) → ``.npz`` for
    :meth:`s2_msi_raw_generator.adf.BandADF.from_product` (alternative to the GIPP path).
    """
    src = args.l1a or os.environ.get("S2_E2ES_L1A")
    if not src:
        raise SystemExit("[derive-adf] needs $S2_E2ES_L1A (a real L1A/L1B .zarr[.zip])")
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
    print(
        f"[derive-adf] wrote {out} ({len(tables)} arrays; "
        f"dark={'real' if has_dark else 'NOT derived — set $S2_E2ES_DARK'})"
    )


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
    return quicklook.save_rgb({"r": a, "g": a, "b": a}, path, rgb=("r", "g", "b"), upscale=upscale)


def _stage_row(name: str, a: np.ndarray) -> str:
    return (
        f"| {name} | {a.min():.1f} | {a.max():.1f} | {a.mean():.1f} | "
        f"{a.std():.2f} | {_snr_db(a):.1f} | {_entropy_bits_f(a):.2f} |"
    )


def phase_figures(store: dict[str, Path], args) -> None:
    """Single-band stage-by-stage README/docs figures + quality metrics (real L1B input).

    Runs the reverse chain step by step on one band/detector of a real L1B and writes the
    three stage images (+ zoom crops + impressed-noise field) and a markdown metrics table.
    Each image is percentile-stretched independently (2–98 %) so the *texture* differences
    (PSF blur, PRNU striping, noise speckle) are what changes between panels.
    """
    src = args.fig_l1b or os.environ.get("S2_E2ES_L1B")
    if not src:
        print("[figures] skipped (needs $S2_E2ES_L1B, a real L1B .zarr[.zip])")
        return
    b = sensor.band(args.fig_band)
    radiance = gio.read_l1b_band(
        src,
        args.fig_detector,
        args.fig_band,
        lines=slice(args.fig_line_start, args.fig_line_start + args.fig_lines),
    )
    n_lines, n_det = radiance.shape

    gipp_dir = args.gipp or os.environ.get("S2_E2ES_GIPP_DIR")
    if gipp_dir:
        from s2_msi_raw_generator import gipp as gipp_mod

        eqog_adf = _eqog_adf_path(args)
        gs = gipp_mod.load_gipp_set(gipp_dir, eqog_adf=eqog_adf)
        a = adfmod.BandADF.from_gipp(b, args.fig_detector, gs, active_width=n_det)
        adf_kind = (
            f"ESA EOPF ADF_REQOG ({os.path.basename(eqog_adf)})"
            if eqog_adf
            else "real operational GIPP (per-pixel dark + relative response)"
        )
    else:
        a = adfmod.synthesize(b, n_det=n_det, seed=2026)
        adf_kind = "real PSF/SRF/noise model; synthetic-fallback dark/PRNU/equalization " "(no GIPP dir supplied)"

    rng = np.random.default_rng(args.seed)
    # Stage captures (reverse_mvp order: S1 -> S6 -> S7 -> S13 -> S11 -> S12 -> S14).
    x_ideal = reverse.s1_radiance_to_dn(radiance, a.band.cal_gain)
    x = reverse.s6_psf_reblur(x_ideal, a.psf)
    x_blur = x
    x = reverse.s7_impress_relative_response(x, a.prnu_gain)
    x_nonoise = reverse.s12_reapply_onboard_eq(reverse.s11_reapply_dark(x, a.dark_dn), a.eq_gain, a.eq_offset)
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
    for name, arr in (
        ("original", x_ideal),
        ("effects", x_fx),
        ("raw", np.asarray(x_raw, dtype=np.float64)),
    ):
        _save_gray(
            arr[cy : cy + cs, cx : cx + cs],
            out / f"result_{tag}_{name}_zoom.png",
            upscale=2,
        )

    # Quality metrics.
    sigma_measured = float(np.std(noise_delta / a.eq_gain[np.newaxis, :]))
    dn_signal = reverse.s7_impress_relative_response(x_blur, a.prnu_gain)
    sigma_model = float(np.mean(np.sqrt(a.noise_a**2 + a.noise_b * np.clip(dn_signal, 0, None))))
    unsat = (x_fx >= 0.0) & (x_fx <= float(sensor.DN_MAX))
    sat_frac = float(1.0 - unsat.mean())
    q_rmse = float(np.sqrt(np.mean(((np.asarray(x_raw, dtype=np.float64) - x_fx)[unsat]) ** 2)))
    rec = reverse.forward_radiometric(np.asarray(x_raw, dtype=np.float64), a)
    rt_err = (rec - radiance)[unsat]
    rt_rmse = float(np.sqrt(np.mean(rt_err**2)))
    rt_bias = float(np.mean(rt_err))
    peak = float(radiance[unsat].max())
    rt_psnr = 20.0 * float(np.log10(peak / rt_rmse)) if rt_rmse > 0 else float("inf")
    blur_rmse = float(np.sqrt(np.mean((x_blur - x_ideal) ** 2)))

    print(
        f"[figures] {os.path.basename(src)}  band={args.fig_band} "
        f"d{args.fig_detector:02d} lines={n_lines} cols={n_det}\n"
        f"[figures] ADFs: {adf_kind}\n[figures] out: {out}\n"
    )
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
    print(
        f"| noise-model σ = √(α²+β·DN) (expected) | {sigma_model:.2f} DN "
        f"({100 * (sigma_measured / sigma_model - 1):+.1f} %) |"
    )
    print(f"| saturated px clipped by S14 (DN > {sensor.DN_MAX}) | {100 * sat_frac:.2f} % |")
    print(f"| quantization RMSE, unsaturated px (expected ≈ 1/√12 ≈ 0.29) | {q_rmse:.2f} DN |")
    print(f"| full-chain radiance recovery RMSE, unsaturated px | {rt_rmse:.2f} " f"(PSNR {rt_psnr:.1f} dB) |")
    print(
        f"| full-chain mean-radiance bias, unsaturated px | {rt_bias:+.3f} "
        f"({100 * rt_bias / radiance[unsat].mean():+.2f} %) |"
    )


def phase_radiometric_vv(store: dict[str, Path], args) -> None:
    gipp_dir = args.gipp or os.environ.get("S2_E2ES_GIPP_DIR")
    if not gipp_dir:
        _jdump({"skipped": "no GIPP dir supplied"}, store["report"] / "radiometric_vv.json")
        print("[radiometric-vv] skipped (no $S2_E2ES_GIPP_DIR)")
        return
    from s2_msi_raw_generator import forward_radiometric_atbd as fwd, gipp as gipp_mod

    pre = _jload(store["report"] / "preflight.json")
    eqog_adf = _eqog_adf_path(args)
    gs = gipp_mod.load_gipp_set(gipp_dir, bands=tuple(pre["bands"]), eqog_adf=eqog_adf)
    out = {}
    if eqog_adf:
        print(f"[radiometric-vv] NUC source: ESA EOPF ADF_REQOG ({os.path.basename(eqog_adf)})")
        epoch = gipp_mod.parse_eqog_adf_epoch(eqog_adf)
        acq_utc = pre.get("start_utc")
        if epoch and acq_utc:
            tv = gipp_mod.temporal_validity(epoch, acq_utc)
            out["_adf_temporal_validity"] = tv
            print(f"[radiometric-vv] {'WARNING — ' if tv['warn'] else ''}temporal-validity: {tv['message']}")
        else:
            out["_adf_temporal_validity"] = {"skipped": "no ADF epoch or acquisition date"}
    for bn in pre["bands"]:
        try:
            eq = gs.band(bn).detectors[DETECTOR]  # GIPP forward/reverse round-trip pattern
        except (KeyError, AttributeError) as exc:
            out[bn] = {"skipped": f"no GIPP coefficients ({exc})"}
            continue
        x = gio.read_l1a_raw(pre["l1a_path"], DETECTOR, bn, lines=slice(0, 2048))
        y = fwd.forward_correct(x, eq)
        x2 = fwd.reverse_impress(y, eq)
        valid = (x > 0) & (x < _SENTINEL_SATURATED)
        rmse = float(np.sqrt(np.mean((x2[valid] - x[valid]) ** 2))) if valid.any() else 0.0
        out[bn] = {
            "rmse": rmse,
            "fpn_raw": float(fwd.column_fpn(x)),
            "fpn_corrected": float(fwd.column_fpn(y)),
        }
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
        "member": name,
        "bytes": len(buf),
        "packets": len(pkts),
        "tiles_exactly": covered == len(buf),
        "coverage_bytes": covered,
        "seq_continuous_per_apid": seq_ok,
        "apids": {str(k): v for k, v in sorted(apids.items())},
        "seq_flags": {str(k): v for k, v in sorted(flags.items())},
        "dlen_min": min(dlens) if dlens else None,
        "dlen_max": max(dlens) if dlens else None,
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
        _jdump(
            {"skipped": f"no real-L0 tars under {dest}"},
            store["report"] / "isp_structural.json",
        )
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
                for m in members:  # datastrip metadata → PSD identifiers
                    if m.name.upper().endswith(".XML") and "MTD" in m.name.upper():
                        xml = tf.extractfile(m).read().decode("utf-8", "replace")
                        ds_info["mtd_member"] = m.name
                        ids = sorted(set(re.findall(r"S2A_OPER_MSI_L0__DS_[A-Z0-9_]+", xml)))
                        times = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", xml)))
                        ds_info["psd_datastrip_ids"] = ids[:5]
                        ds_info["sensing_times"] = times[:6]
    # naming crosswalk: our PSD-style metadata id + PSFD file names vs the real PSD forms
    pre = _jload(store["report"] / "preflight.json")
    crosswalk = {
        "ours_psfd_l0": pre["product_names"]["l0"],
        "real_psd_ds_tar": ds_info.get("tar"),
        "real_psd_datastrip_ids": ds_info.get("psd_datastrip_ids", []),
    }
    canon = store["l0"] / pre["product_names"]["l0"]
    if canon.exists():
        import zarr

        g = zarr.open_group(str(canon), mode="r")
        crosswalk["ours_psd_datastrip_id"] = dict(g.attrs)["stac_discovery"]["properties"].get("eopf:datastrip_id")
        crosswalk["psd_pattern_match"] = bool(
            crosswalk["ours_psd_datastrip_id"]
            and re.fullmatch(
                r"S2[ABC]_OPER_MSI_L0__DS_\d{8}T\d{6}_A\d{6}",
                crosswalk["ours_psd_datastrip_id"],
            )
        )
        ours = {}
        for bn in pre["bands"]:
            mg = g[f"measurements/d{DETECTOR:02d}/{sensor.zarr_band_key(bn)}"]
            stream = np.asarray(mg["isp"])
            ours[bn] = {
                "packets": sum(1 for _ in isp.iter_packets(stream)),
                "bytes": int(stream.size),
                "ratio": dict(mg.attrs)["compression"]["ratio"],
            }
    else:
        ours = {}
    n_tiled = sum(1 for s in sad_scans if s["tiles_exactly"])
    _jdump(
        {
            "safe_limitation": "PSD L0 SAFE image-ISP .bin objects are HTTP 403 on GET "
            "(bucket policy) — image-packet accounting not possible; "
            "structural ISP validation done on real SADATA packet streams",
            "real_sadata": sad_scans,
            "real_ds": ds_info,
            "naming_crosswalk": crosswalk,
            "ours": ours,
            "sadata_members_tiling": f"{n_tiled}/{len(sad_scans)}",
        },
        store["report"] / "isp_structural.json",
    )
    print(
        f"[scan-l0] SADATA members tiling exactly: {n_tiled}/{len(sad_scans)}; "
        f"DS ids: {ds_info.get('psd_datastrip_ids', [])[:2]}"
    )


def phase_quicklook(store: dict[str, Path], args) -> None:
    pre = _jload(store["report"] / "preflight.json")
    l1a = pre["l1a_path"]
    rgb = ("B04", "B03", "B02")
    if not all(b in pre["bands"] for b in rgb):
        print("[quicklook] skipped (RGB bands not in selection)")
        return
    full = {b: gio.read_l1a_raw(l1a, DETECTOR, b, lines=args.line_slice, dtype=np.uint16)[::8] for b in rgb}
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
    ll = np.abs(bands["LL3"])
    hl = np.abs(bands["HL1"])
    p4 = quicklook.save_rgb(
        {"r": ll, "g": ll, "b": ll},
        store["quicklook"] / "dwt_ll3.png",
        rgb=("r", "g", "b"),
    )
    p5 = quicklook.save_rgb(
        {"r": hl, "g": hl, "b": hl},
        store["quicklook"] / "dwt_hl1.png",
        rgb=("r", "g", "b"),
    )
    print(f"[quicklook] {p1}\n            {p2}\n            {p3}\n            {p4}\n            {p5}")


def phase_report(store: dict[str, Path], args) -> None:
    rep = store["report"]
    sections = {}
    for name in [
        "fetch_l1a_manifest",
        "fetch_l0_manifest",
        "preflight",
        "ground_decode",
        "l0_decode",
        "validate",
        "radiometric_vv",
        "isp_structural",
    ]:
        p = rep / f"{name}.json"
        sections[name] = _jload(p) if p.exists() else {"missing": True}
    pre = sections["preflight"]
    lines = ["# Real-L1A E2E run report", ""]
    if not pre.get("missing"):
        lines += [
            f"- L1A: `{pre['l1a_path']}` · bands {len(pre['bands'])} · "
            f"lines {pre['n_lines']} · bit_depth {pre['bit_depth']}",
            f"- Products: `{pre['product_names']['l0']}` / "
            f"`{pre['product_names']['l0_oc']}` / `{pre['product_names']['l1a_prime']}`",
            f"- Naming fallbacks: {pre['naming_fallbacks'] or 'none'}",
            "",
        ]
    gd = sections["ground_decode"]
    if not gd.get("missing"):
        lines += [
            "## Compression + ground decode (bit-exact)",
            "",
            "| band | ratio | packets | bit-exact |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {b} | {v.get('ratio')} | {v.get('n_packets')} | {v.get('bit_exact')} |" for b, v in sorted(gd.items())
        ]
        lines.append("")
    va = sections["validate"]
    if not va.get("missing"):
        lines += [
            "## L1A′ vs original L1A",
            "",
            "| band | bit-identical (kept) | lines lost | rmse |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {b} | {v['bit_identical_kept']} | {v['lines_lost']} | {v['rmse']} |" for b, v in sorted(va.items())
        ]
        lines.append("")
    rv = sections["radiometric_vv"]
    if not rv.get("missing") and not rv.get("skipped"):
        lines += [
            "## Radiometric GIPP round-trip",
            "",
            "| band | rmse | fpn raw → corrected |",
            "|---|---|---|",
        ]
        lines += [
            f"| {b} | {v.get('rmse'):.3e} | {v.get('fpn_raw', 0):.3f} → " f"{v.get('fpn_corrected', 0):.3f} |"
            for b, v in sorted(rv.items())
            if "rmse" in v
        ]
        lines.append("")
    st = sections["isp_structural"]
    if not st.get("missing") and not st.get("skipped"):
        lines += [
            "## Real-L0 ISP structural scan",
            "",
            f"- {st.get('safe_limitation', '')}",
            f"- Real SADATA members tiling exactly: {st.get('sadata_members_tiling')}",
            "",
        ]
        if st.get("real_sadata"):
            lines += [
                "| member | packets | tiles | seq continuous | data-len min..max |",
                "|---|---|---|---|---|",
            ]
            lines += [
                f"| {s['member']} | {s['packets']} | {s['tiles_exactly']} | "
                f"{s['seq_continuous_per_apid']} | {s['dlen_min']}..{s['dlen_max']} |"
                for s in st["real_sadata"]
            ]
            lines.append("")
        cw = st.get("naming_crosswalk", {})
        if cw:
            lines += [
                "### Naming crosswalk (PSD ↔ PSFD)",
                "",
                f"- ours (PSFD file): `{cw.get('ours_psfd_l0')}`",
                f"- ours (PSD datastrip id in metadata): `{cw.get('ours_psd_datastrip_id')}` "
                f"(pattern match: {cw.get('psd_pattern_match')})",
                f"- real (PSD DS tar): `{cw.get('real_psd_ds_tar')}`",
                f"- real datastrip ids: {cw.get('real_psd_datastrip_ids')}",
                "",
            ]
    (rep / "e2e_report.md").write_text("\n".join(lines) + "\n")
    _jdump(sections, rep / "summary.json")
    print(f"[report] {rep/'e2e_report.md'}")


# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _settings(mode: str) -> argparse.Namespace:
    """The pipeline's knobs — environment-only; the CLI takes just the mode.

    Returns a namespace with the exact attribute names the phase functions expect;
    unset variables fall back to the documented defaults (module docstring).
    """
    e = os.environ.get
    s = argparse.Namespace(mode=mode)
    s.phases = e("S2_E2ES_PHASES") or None
    s.l1a = e("S2_E2ES_L1A") or None
    s.public_l0 = e("S2_E2ES_PUBLIC_L0") or None
    s.import_detector = _env_int("S2_E2ES_IMPORT_DETECTOR", 1)
    s.dark = e("S2_E2ES_DARK") or None
    s.gipp = e("S2_E2ES_GIPP_DIR") or None
    s.eqog_adf = e("S2_E2ES_EQOG_ADF") or None
    s.bands = [b.strip().upper() for b in (e("S2_E2ES_BANDS") or ",".join(sensor.BANDS)).split(",") if b.strip()]
    s.lines = _env_int("S2_E2ES_LINES", 0)
    s.line_slice = slice(0, s.lines) if s.lines else None
    s.seed = _env_int("S2_E2ES_SEED", 0)
    s.n_det = _env_int("S2_E2ES_NDET", 400)
    s.cal_lines = _env_int("S2_E2ES_CAL_LINES", 256)
    s.jobs = _env_int("S2_E2ES_JOBS", os.cpu_count() or 8)
    # fixed internals — formerly niche flags no consumer ever overrode
    s.detectors = "1-12"
    s.max_payload = isp.DEFAULT_MAX_PAYLOAD
    s.store_decoded = True
    s.fig_l1b = e("S2_E2ES_L1B") or None
    s.fig_band, s.fig_detector = "B04", 7
    s.fig_line_start, s.fig_lines = 8450, 650
    s.fig_zoom_line, s.fig_zoom_col, s.fig_zoom_size = 0, 0, 256
    s.fig_out = None
    # data-store sync (ipf/data-store registry)
    s.publish_name = e("S2_E2ES_PUBLISH_NAME") or "products"
    s.publish_version = e("S2_E2ES_PUBLISH_VERSION") or None
    s.publish_layer = e("S2_E2ES_PUBLISH_LAYER") or "products"
    if s.publish_layer not in ("products", "inputs"):
        raise SystemExit(f"S2_E2ES_PUBLISH_LAYER must be products|inputs, got {s.publish_layer!r}")
    job = e("CI_JOB_URL")
    s.publish_source = f"run_pipeline publish-store ({job})" if job else "run_pipeline publish-store"
    return s


def main(argv=None, *, use_local_defaults: bool = False) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="runs with no exports via the baked-in LOCAL_ENV_DEFAULTS (store root, GIPP dir, "
        "public L0, detector, jobs); export any S2_E2ES_* / S2_DATA_STORE var to override "
        "(full list in the module docstring)",
    )
    ap.add_argument(
        "mode",
        nargs="?",
        default="nominal",
        choices=("nominal", "calibration"),
        help="nominal (default): real S2 product -> synthetic RAW downlink; "
        "calibration: campaign acquisitions -> S02MSIDCA/S02MSISCA L0 + cal-DB "
        "under <store>/caldb/",
    )
    mode = ap.parse_args(argv).mode
    # Command-line runs (``use_local_defaults``, set from ``__main__``) get the baked-in
    # LOCAL_ENV_DEFAULTS so a bare ``python scripts/run_pipeline.py`` needs no shell exports;
    # an already-exported value always wins (setdefault). Programmatic callers (tests) opt out
    # so the process environment stays clean. Phases default per mode.
    if use_local_defaults:
        for key, value in LOCAL_ENV_DEFAULTS.items():
            os.environ.setdefault(key, value)
        if mode == "nominal":
            os.environ.setdefault("S2_E2ES_PHASES", LOCAL_NOMINAL_PHASES)
    args = _settings(mode)

    store = _store_paths(Path(os.environ.get("S2_DATA_STORE") or "~/data-store").expanduser())
    default_phases = CALIBRATION_PHASES if args.mode == "calibration" else NOMINAL_PHASES
    todo = [p.strip() for p in (args.phases or ",".join(default_phases)).split(",") if p.strip()]
    unknown = [p for p in todo if p not in PHASES]
    if unknown:
        ap.error(f"unknown phases: {unknown} (S2_E2ES_PHASES: choose from {PHASES})")
    fns = {
        "fetch-store": phase_fetch_store,
        "publish-store": phase_publish_store,
        "inventory": phase_inventory,
        "fetch-l1a": phase_fetch_l1a,
        "fetch-l0": phase_fetch_l0,
        "import-l0": phase_import_l0,
        "preflight": phase_preflight,
        "cal-acquire": phase_cal_acquire,
        "cal-package": phase_cal_package,
        "build-caldb": phase_build_caldb,
        "package": phase_package,
        "reverse-l1b": phase_reverse_l1b,
        "ground-decode": phase_ground_decode,
        "l0-decode": phase_l0_decode,
        "validate": phase_validate,
        "radiometric-vv": phase_radiometric_vv,
        "derive-adf": phase_derive_adf,
        "scan-l0": phase_scan_l0,
        "quicklook": phase_quicklook,
        "figures": phase_figures,
        "report": phase_report,
    }
    for p in PHASES:
        if p in todo:
            fns[p](store, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(use_local_defaults=True))

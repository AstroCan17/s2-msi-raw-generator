"""Data-store inventory and consistency reporting.

The scanner is intentionally metadata-only: it walks the store layout, reads Zarr attributes from
directories or ``.zarr.zip`` archives with stdlib JSON/zipfile support, and classifies products
without loading image arrays.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from . import metadata, naming

_LENIENT_NAME_RE = re.compile(
    r"^(?P<product_type>[A-Z0-9_]{9})_(?P<start>\d{8}T\d{6})_"
    r"(?P<duration>\d{4})_(?P<unit>[A-Z])(?P<relative_orbit>\d{3})_"
    r"(?P<consolidation>[T_S])(?P<discriminator>[0-9A-F]{3})"
    r"(?:_(?P<z_suffix>[A-Za-z0-9_]+))?(?P<ext>\.zarr\.zip|\.zarr|\.tar)?$"
)
_PSD_RE = re.compile(
    r"(?P<unit>S2[ABC])_OPER_(?P<kind>[A-Z0-9_]+?)_"
    r"(?P<creation>\d{8}T\d{6})_?(?P<validity>V\d{8}T\d{6}_\d{8}T\d{6})?"
    r".*?(?:_A(?P<absolute_orbit>\d{6}))?"
)


def _json_loads(data: str | bytes) -> dict:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {}


def _read_attrs_dir(path: Path) -> dict:
    for rel in (".zattrs", ".zmetadata"):
        p = path / rel
        if p.exists():
            data = _json_loads(p.read_text())
            if rel == ".zmetadata":
                return data.get("metadata", {}).get(".zattrs", {})
            return data
    return {}


def _read_attrs_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        candidates = [n for n in names if n.endswith(".zattrs")]
        candidates.sort(key=lambda n: (n.count("/"), len(n)))
        for name in candidates:
            data = _json_loads(zf.read(name))
            if data:
                return data
        for name in sorted(n for n in names if n.endswith(".zmetadata")):
            meta = _json_loads(zf.read(name)).get("metadata", {})
            for key, value in meta.items():
                if key.endswith(".zattrs") and isinstance(value, dict):
                    return value
    return {}


def _group_counts_dir(path: Path) -> dict[str, int]:
    out = {"detectors": 0, "bands": 0, "arrays": 0}
    meas = path / "measurements"
    if not meas.exists():
        return out
    dets = [p for p in meas.iterdir() if p.is_dir() and re.fullmatch(r"d\d{2}|DD\d{2}", p.name)]
    out["detectors"] = len(dets)
    bands: set[str] = set()
    arrays = 0
    for det in dets:
        for band in det.iterdir():
            if band.is_dir():
                bands.add(band.name.upper())
                arrays += sum(1 for p in band.iterdir() if p.is_dir() or p.is_file())
    out["bands"] = len(bands)
    out["arrays"] = arrays
    return out


def _group_counts_zip(path: Path) -> dict[str, int]:
    out = {"detectors": 0, "bands": 0, "arrays": 0}
    with zipfile.ZipFile(path) as zf:
        dets: set[str] = set()
        bands: set[str] = set()
        arrays: set[str] = set()
        for name in zf.namelist():
            parts = name.split("/")
            if "measurements" not in parts:
                continue
            i = parts.index("measurements")
            if len(parts) < i + 4:
                continue
            det, band, arr = parts[i + 1], parts[i + 2], parts[i + 3]
            if re.fullmatch(r"d\d{2}|DD\d{2}", det):
                dets.add(det)
                bands.add(band.upper())
                arrays.add("/".join(parts[: i + 4]))
        out.update(detectors=len(dets), bands=len(bands), arrays=len(arrays))
    return out


def read_zarr_identity(path: str | Path) -> dict:
    """Read best-effort acquisition identity from a Zarr directory or zip archive."""
    p = Path(path)
    attrs = _read_attrs_zip(p) if p.suffix == ".zip" else _read_attrs_dir(p)
    _stac, props, flags = metadata.normalise_stac(attrs)
    identity: dict[str, Any] = {
        "datetime": None,
        "start_datetime": None,
        "platform": None,
        "relative_orbit": None,
        "absolute_orbit": None,
        "datastrip_id": None,
        "active_detectors": None,
        "counts": {},
    }
    if not attrs:
        return {"identity": identity, "flags": ["no_zarr_attrs"], "identity_source": "none"}
    dt = props.get("start_datetime") or props.get("datetime")
    if dt is not None and str(dt).lower() == "null":
        flags.append("datetime_null")
        dt = None
    identity["datetime"] = props.get("datetime")
    identity["start_datetime"] = dt
    identity["platform"] = props.get("platform")
    identity["relative_orbit"], bad_rel = metadata.coerce_int(props.get("sat:relative_orbit"))
    identity["absolute_orbit"], bad_abs = metadata.coerce_int(props.get("sat:absolute_orbit"))
    if bad_rel:
        flags.append("relative_orbit_not_int")
    if bad_abs:
        flags.append("absolute_orbit_unfilled_xpath")
    identity["datastrip_id"] = props.get("eopf:data_take_id") or props.get("eopf:datastrip_id")
    if identity["absolute_orbit"] is None and identity["datastrip_id"]:
        recovered = metadata.absolute_orbit_from_datatake_id(identity["datastrip_id"])
        if recovered is not None:
            identity["absolute_orbit"] = recovered
            flags.append("absolute_orbit_from_datatake_id")

    acq = (
        attrs.get("other_metadata", {})
        .get("sensor_configuration", {})
        .get("acquisition_configuration")
    )
    if acq is None:
        acq = (
            attrs.get("other_metadata", {})
            .get("sensor_configuration", {})
            .get("aquisition_configuration")
        )
        if acq is not None:
            flags.append("aquisition_configuration_typo")
    if isinstance(acq, dict):
        identity["active_detectors"] = acq.get("active_detectors_list")
    try:
        identity["counts"] = _group_counts_zip(p) if p.suffix == ".zip" else _group_counts_dir(p)
    except Exception as exc:  # noqa: BLE001 - inventory should keep walking
        flags.append(f"count_error:{exc.__class__.__name__}")
    return {"identity": identity, "flags": flags, "identity_source": "stac_discovery"}


def parse_name_lenient(name: str) -> dict:
    """Parse PSFD names first, then known public/PSD-like names."""
    try:
        parsed = naming.parse_psfd_name(name)
        parsed["psfd"] = True
        return parsed
    except ValueError:
        pass
    m = _LENIENT_NAME_RE.match(name)
    if m:
        d = m.groupdict()
        d["relative_orbit"] = int(d["relative_orbit"])
        d["psfd"] = d["product_type"] in naming.TYPE_CODES
        return d
    m = _PSD_RE.match(name)
    if m:
        d = m.groupdict()
        d["psfd"] = False
        if d.get("absolute_orbit"):
            d["absolute_orbit"] = int(d["absolute_orbit"])
        return d
    return {"psfd": False}


def _classify(path: Path, store: Path) -> tuple[str, str, str]:
    rel = path.relative_to(store).as_posix() if path.is_relative_to(store) else path.as_posix()
    name = path.name
    if path.is_symlink() and not path.exists():
        return "broken-symlink", "input", "local"
    if "/.publish-stage/" in f"/{rel}/" or rel.startswith(".publish-stage/"):
        return "staging-zip", "stage", "local"
    if rel.startswith("report/"):
        return "report", "report", "local"
    if rel.startswith("quicklook/"):
        return "quicklook", "quicklook", "local"
    if rel.startswith("l1a_prime/"):
        return "our-l1a-prime", "derived", "local"
    if rel.startswith("caldb/") and name.startswith(("S02MSIDCA", "S02MSISCA")):
        return "our-cal-l0", "calibration", "local"
    if rel.startswith("caldb/"):
        return "caldb-adf", "calibration", "local"
    if rel.startswith("l0/") and name.endswith("_OC.zarr"):
        return "our-l0-oc", "derived", "local"
    if rel.startswith("l0/"):
        return "our-l0-canonical", "derived", "local"
    if rel.startswith("inputs/public-data/level-0/") and name.startswith("S02MSIL0P"):
        return "external-l0p-annotation", "reference", "public"
    if rel.startswith("inputs/public-data/level-0/") and name.startswith("S02MSIL0__"):
        return "external-l0-public", "reference", "public"
    if rel.startswith("inputs/") and name == "PDI_MSI_S2_L1A.zarr":
        return "external-l1a", "input", "public"
    if rel.startswith("inputs/real_l0/") and name.endswith(".tar"):
        return "external-psd-tar", "reference", "public"
    if rel.startswith("inputs/") and ("GIP" in name.upper() or "gipp" in rel.lower()):
        return "reference-gipp", "reference", "local"
    if rel.startswith("inputs/") and "psf" in rel.lower():
        return "reference-psf", "reference", "local"
    if ".pytest_cache" in rel or "__pycache__" in rel:
        return "ci-scratch", "scratch", "local"
    return "other", "other", "local"


def _iter_items(store: Path):
    for root, dirs, files in os.walk(store, followlinks=False):
        rootp = Path(root)
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        for d in list(dirs):
            p = rootp / d
            if p.name.endswith(".zarr"):
                dirs.remove(d)
                yield p
            elif p.is_symlink():
                yield p
        for f in files:
            p = rootp / f
            if p.name.endswith((".zarr.zip", ".tar", ".json", ".md", ".zip")):
                yield p


def scan_store(store: str | Path) -> list[dict]:
    """Return inventory records for the known data-store layout."""
    root = Path(store).expanduser()
    records: list[dict] = []
    for path in sorted(_iter_items(root), key=lambda p: p.as_posix()):
        kind, role, source = _classify(path, root)
        flags: list[str] = []
        identity: dict[str, Any] = {}
        identity_source = "name"
        if path.is_symlink() and not path.exists():
            flags.append("broken_symlink")
        if path.name.endswith((".zarr", ".zarr.zip")):
            got = read_zarr_identity(path)
            identity = got["identity"]
            flags.extend(got["flags"])
            identity_source = got["identity_source"]
        parsed = parse_name_lenient(path.name)
        if parsed:
            identity.setdefault("name", parsed)
        try:
            size = path.stat().st_size if path.is_file() else sum(
                p.stat().st_size for p in path.rglob("*") if p.is_file()
            )
        except OSError:
            size = 0
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "name": path.name,
                "kind": kind,
                "bytes": int(size),
                "role": role,
                "source": source,
                "identity": identity,
                "identity_source": identity_source,
                "flags": sorted(set(flags)),
            }
        )
    assign_groups(records)
    return records


def _acq_key(rec: dict) -> str:
    ident = rec.get("identity", {})
    name = ident.get("name", {})
    start = ident.get("start_datetime") or ident.get("datetime")
    rel = ident.get("relative_orbit")
    abs_orb = ident.get("absolute_orbit")
    if start and rel is not None:
        return f"{start}|R{rel}|A{abs_orb}"
    if name.get("start") and name.get("relative_orbit"):
        return f"{name['start']}|R{name['relative_orbit']}|A{name.get('absolute_orbit')}"
    return "unknown"


def assign_groups(records: list[dict]) -> None:
    """Annotate records with acquisition grouping and comparability hints."""
    keys = {_acq_key(r) for r in records if _acq_key(r) != "unknown"}
    for rec in records:
        key = _acq_key(rec)
        rec["group"] = key
        if rec["kind"].startswith("our-") and key == "unknown":
            rec["comparable_with"] = "Group A only (placeholder identity)"
        elif rec["kind"] == "external-l0-public":
            rec["comparable_with"] = (
                "same-scene" if any(r["kind"].startswith("our-") and _acq_key(r) == key for r in records)
                else "distribution-level only"
            )
        elif key in keys:
            rec["comparable_with"] = "same acquisition group"
        else:
            rec["comparable_with"] = "unknown"


def _finding(fid: str, severity: str, evidence: str, impact: str, fix: str) -> dict:
    return {"id": fid, "severity": severity, "evidence": evidence, "impact": impact, "fix": fix}


def consistency_findings(records: list[dict], store: str | Path) -> list[dict]:
    """Build the consistency finding list described in the plan."""
    out: list[dict] = []
    for rec in records:
        name = rec.get("identity", {}).get("name", {})
        ident = rec.get("identity", {})
        if name.get("relative_orbit") and ident.get("relative_orbit") and name["relative_orbit"] != ident["relative_orbit"]:
            out.append(_finding(
                "orbit-name-stac-mismatch",
                "HIGH",
                f"{rec['path']}: name R{name['relative_orbit']} vs STAC R{ident['relative_orbit']}",
                "Products from the same chain can sort into contradictory acquisitions.",
                "Thread the acquisition context into product writers.",
            ))
    if any(r["kind"] == "external-l1a" and "no_zarr_attrs" in r["flags"] for r in records):
        out.append(_finding(
            "pdi-stac-missing",
            "HIGH",
            "PDI_MSI_S2_L1A.zarr has no readable STAC discovery attributes.",
            "The pipeline falls back to placeholder naming and orbit context.",
            "Import or supply real STAC identity before packaging.",
        ))
    public = [r for r in records if r["kind"] == "external-l0-public"]
    ours = [r for r in records if r["kind"].startswith("our-l0")]
    for p in public:
        if ours and all(_acq_key(o) != _acq_key(p) for o in ours):
            out.append(_finding(
                "public-l0-different-datatake",
                "CRITICAL",
                f"{p['path']} groups as {_acq_key(p)}, while generated L0 groups differ.",
                "Direct DN comparisons are cross-scene and cannot validate bit identity.",
                "Use import-l0 to bridge the public L0 into the same scene.",
            ))
    if any(r["kind"] == "external-l0p-annotation" and r["identity_source"] == "none" for r in records):
        out.append(_finding(
            "l0p-annotations-no-stac",
            "LOW",
            "One or more S02MSIL0P companions have no STAC properties.",
            "They are useful as distribution annotations, not as science-image identity anchors.",
            "Keep them classified separately from image L0 products.",
        ))
    root = Path(store)
    if (root / ".publish-stage/gipp.zip").exists() and not (root / "inputs/gipp").exists():
        out.append(_finding(
            "radiometric-vv-gipp-skipped",
            "MEDIUM",
            ".publish-stage/gipp.zip exists but inputs/gipp is missing or broken.",
            "radiometric_vv can skip even though the GIPP payload is available.",
            "Set S2_E2ES_GIPP_DIR or restore the inputs/gipp link.",
        ))
    l0_decode = root / "report/l0_decode.json"
    if l0_decode.exists():
        data = _json_loads(l0_decode.read_text())
        if data.get("groups") == 4:
            out.append(_finding(
                "l0-decode-empty-group-count",
                "INFO",
                "report/l0_decode.json reports 4 groups including an empty residual group.",
                "Report-only overcount; persisted products are unaffected.",
                "Count only non-empty groups.",
            ))
    if not out:
        out.append(_finding(
            "inventory-no-blockers",
            "INFO",
            "No high-severity inventory inconsistencies detected in this store snapshot.",
            "Inventory is still a point-in-time report.",
            "Re-run after regenerating products.",
        ))
    return out


def render_markdown(records: list[dict], findings: list[dict]) -> str:
    lines = ["# Data-store inventory", ""]
    lines += ["## Items", "", "| kind | path | group | comparable | flags |", "|---|---|---|---|---|"]
    for rec in records:
        lines.append(
            f"| {rec['kind']} | `{rec['path']}` | `{rec.get('group', '')}` | "
            f"{rec.get('comparable_with', '')} | {', '.join(rec['flags']) or '-'} |"
        )
    lines += ["", "## Consistency findings", "", "| severity | id | evidence | fix |", "|---|---|---|---|"]
    for f in findings:
        lines.append(f"| {f['severity']} | `{f['id']}` | {f['evidence']} | {f['fix']} |")
    return "\n".join(lines) + "\n"


def write_outputs(store: str | Path) -> dict:
    """Scan ``store`` and write ``INVENTORY.md`` plus ``report/inventory.json``."""
    root = Path(store).expanduser()
    (root / "report").mkdir(parents=True, exist_ok=True)
    records = scan_store(root)
    findings = consistency_findings(records, root)
    payload = {"records": records, "findings": findings}
    (root / "INVENTORY.md").write_text(render_markdown(records, findings))
    (root / "report/inventory.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return payload

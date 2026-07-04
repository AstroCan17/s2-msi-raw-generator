"""Import a public distribution L0 image product as a PDI-style L1A input.

The bridge does not synthesize data: it copies one public detector's per-band DN arrays into the
``measurements/DD01/Bxx/l1a_raw_image`` layout consumed by the pipeline, preserving acquisition
identity in root STAC metadata and recording per-band provenance.
"""

from __future__ import annotations

import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import _zarrio, io as gio, metadata, naming, sensor


def read_public_l0_identity(public_l0_path: str | Path) -> dict:
    """Read acquisition identity from a public L0 Zarr/Zip product."""
    g = gio._open(str(public_l0_path))
    attrs = dict(g.attrs)
    stac, props, _ = metadata.normalise_stac(attrs)
    found: dict[str, str] = {}
    start = metadata.parse_iso(props.get("start_datetime")) or metadata.parse_iso(
        props.get("datetime")
    )
    if start:
        found["start_datetime"] = "stac"
    rel, _ = metadata.coerce_int(props.get("sat:relative_orbit"))
    if rel is not None:
        found["relative_orbit"] = "stac"
    abs_orb, _ = metadata.coerce_int(props.get("sat:absolute_orbit"))
    if abs_orb is not None:
        found["absolute_orbit"] = "stac"
    dtid = props.get("eopf:data_take_id") or props.get("eopf:datastrip_id")
    if abs_orb is None and dtid:
        recovered = metadata.absolute_orbit_from_datatake_id(dtid)
        if recovered is not None:
            abs_orb = recovered
            found["absolute_orbit"] = "datatake_id"
    platform = props.get("platform") or "Sentinel-2A"
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
            found["acquisition_configuration"] = "typo:aquisition_configuration"
    return {
        "start_datetime": start or naming.DEFAULT_START,
        "relative_orbit": rel or naming.DEFAULT_RELATIVE_ORBIT,
        "absolute_orbit": abs_orb or 0,
        "orbit_state": props.get("sat:orbit_state") or "descending",
        "platform": platform,
        "end_datetime": metadata.parse_iso(props.get("end_datetime")),
        "instrument_mode": (acq or {}).get("operation_mode") if isinstance(acq, dict) else None,
        "active_detectors": (acq or {}).get("active_detectors_list") if isinstance(acq, dict) else None,
        "data_take_id": dtid,
        "stac": stac,
        "properties": props,
        "found": found,
    }


def _source_array(group, detector: int, band: str):
    candidates = [
        f"measurements/d{detector:02d}/{sensor.zarr_band_key(band)}/img",
        f"measurements/DD{detector:02d}/{band.upper()}/img",
        f"measurements/d{detector:02d}/{sensor.zarr_band_key(band)}/band{sensor.band_number(band)}",
        f"measurements/DD{detector:02d}/{band.upper()}/l1a_raw_image",
    ]
    for key in candidates:
        try:
            return group[key]
        except Exception:  # noqa: BLE001 - zarr raises version-specific lookup errors
            continue
    raise KeyError(f"no public L0 image array for detector {detector:02d} band {band}")


def _available_bands(group, detector: int, requested: list[str]) -> list[str]:
    out: list[str] = []
    for band in requested:
        try:
            _source_array(group, detector, band)
        except KeyError:
            continue
        out.append(band)
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def convert(
    public_l0_path: str | Path,
    out_dir: str | Path,
    *,
    detector: int = 1,
    bands: list[str] | tuple[str, ...] | None = None,
    jobs: int = 1,
) -> dict:
    """Convert one public L0 detector into a PDI-style L1A Zarr directory.

    ``jobs`` is accepted for pipeline symmetry; writes stay serial so memory remains bounded by one
    band array at a time.
    """
    del jobs
    src_path = Path(public_l0_path)
    out_root = Path(out_dir)
    identity = read_public_l0_identity(src_path)
    g = gio._open(str(src_path))
    requested = [b.upper() for b in (bands or sensor.BANDS)]
    selected = _available_bands(g, detector, requested)
    if not selected:
        raise ValueError(f"no requested bands found in {src_path} for detector {detector:02d}")

    first = np.asarray(_source_array(g, detector, selected[0]))
    duration_s = first.shape[0] * sensor.LINE_PERIOD_MS / 1e3
    name = naming.psfd_name(
        "S02MSIL1A",
        identity["start_datetime"],
        duration_s,
        unit=naming._unit_from_platform(identity["platform"]) or naming.DEFAULT_UNIT,
        relative_orbit=identity["relative_orbit"],
        z_suffix=f"IMP{detector:02d}",
    )
    out_path = out_root / name
    root = _zarrio.open_group_w(out_path)
    meas = root.create_group("measurements").create_group("DD01")
    per_band: dict[str, dict] = {}
    for band in selected:
        src = np.asarray(_source_array(g, detector, band), dtype=np.uint16)
        bg = meas.create_group(band)
        _zarrio.put_array(bg, "l1a_raw_image", src, dtype="uint16")
        reread = np.asarray(root[f"measurements/DD01/{band}/l1a_raw_image"])
        if not np.array_equal(src, reread):
            raise ValueError(f"A0 import copy mismatch for {band}")
        per_band[band] = {
            "shape": list(src.shape),
            "min": int(src.min(initial=0)),
            "max": int(src.max(initial=0)),
            "crc32": f"{zlib.crc32(src.tobytes()):08x}",
        }
        del src, reread

    start = identity["start_datetime"]
    end = identity["end_datetime"] or start
    props = {
        **identity.get("properties", {}),
        "platform": identity["platform"],
        "constellation": "sentinel-2",
        "instrument": "Multi Spectral Imager MSI",
        "product:type": "S02MSIL1A",
        "eopf:type": "S02MSIL1A",
        "processing:level": "L1A",
        "datetime": _iso(start),
        "start_datetime": _iso(start),
        "end_datetime": _iso(end),
        "sat:relative_orbit": identity["relative_orbit"],
        "sat:absolute_orbit": identity["absolute_orbit"],
        "sat:orbit_state": identity["orbit_state"],
    }
    root.attrs.update(
        {
            "stac_discovery": {
                "type": identity.get("stac", {}).get("type", "Feature"),
                "bbox": identity.get("stac", {}).get("bbox"),
                "geometry": identity.get("stac", {}).get("geometry"),
                "properties": props,
            },
            "other_metadata": {
                "import_provenance": {
                    "source_product": str(src_path),
                    "source_detector": detector,
                    "target_detector": 1,
                    "detector_mapping": f"d{detector:02d}->DD01",
                    "identity_fields": identity["found"],
                    "bands": per_band,
                }
            },
        }
    )
    # Re-open through the public reader path used by the pipeline for the final A0 assertion.
    for band in selected:
        imported = gio.read_l1a_raw(str(out_path), 1, band, dtype=np.uint16)
        source = np.asarray(_source_array(g, detector, band), dtype=np.uint16)
        if not np.array_equal(imported, source):
            raise ValueError(f"A0 import re-read mismatch for {band}")
    return {
        "source": str(src_path),
        "output": str(out_path),
        "product_name": name,
        "detector": detector,
        "bands": selected,
        "identity": {
            "start_datetime": _iso(start),
            "relative_orbit": identity["relative_orbit"],
            "absolute_orbit": identity["absolute_orbit"],
            "platform": identity["platform"],
        },
        "per_band": per_band,
    }

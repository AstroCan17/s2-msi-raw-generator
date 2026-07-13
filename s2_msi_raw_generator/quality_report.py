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

"""EOPF EOQC-style per-product quality report (machine-readable ``OK``/``KO`` JSON).

Emulates the minimum content of the EOPF ``eopf.qualitycontrol`` (EOQC) per-product report — product
name/type, station, facility, sensing times, orbit numbers, an overall flag and a per-check list —
self-asserted from the Synthetic L0 product the generator just wrote. Pure ``json``/stdlib (no ``eopf`` dependency);
when the ``EOQCProcessor`` is available (in the SDE) it may additionally be run. ECSS-Q-ST-20C.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

# The generic EOQC checks the generator can self-assert from the product metadata it produced.
_MANDATORY_STAC_KEYS = ("platform", "instrument", "eopf:type", "datetime")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_qc_report(
    root_metadata: dict,
    *,
    product_name: str,
    software_version: str = __version__,
    inspection_time: str | None = None,
    has_measurements: bool = True,
) -> dict:
    """Build the EOQC per-product QC report from the L0 root metadata. Overall ``OK`` iff all checks pass."""
    disc = root_metadata.get("stac_discovery", {})
    props = disc.get("properties", {})
    geom = disc.get("geometry", {})
    ts = root_metadata.get("other_metadata", {}).get("sensor_configuration", {}).get("time_stamp", {})
    start, stop = props.get("start_datetime", ""), props.get("end_datetime", "")
    rel, ab = props.get("sat:relative_orbit"), props.get("sat:absolute_orbit")
    ring = (geom.get("coordinates") or [[]])[0]

    checks = {
        "STAC_metadata_content": all(k in props for k in _MANDATORY_STAC_KEYS),
        "STAC_geometry_polygon": geom.get("type") == "Polygon" and len(ring) >= 4 and ring[0] == ring[-1],
        "Sensing_Time": bool(start) and bool(stop) and start <= stop,
        "ISO_Time": start.endswith("Z") and stop.endswith("Z"),
        "Datation_Sync": float(ts.get("acquisition_epoch_gps_s") or 0.0) > 0.0,
        "Time_Correlation": "acquisition_epoch_utc" in ts,
        "Relative_Orbit": isinstance(rel, int) and 1 <= rel <= 143,
        # A000000 is the explicit placeholder orbit used when source STAC has no absolute orbit.
        "Absolute_Orbit": isinstance(ab, int) and ab >= 0,
        "Product_Structure": bool(has_measurements),
    }
    inspection = inspection_time or _now_iso()
    return {
        "product_name": product_name,
        "product_type": props.get("product:type") or props.get("eopf:type"),
        "acquisition_station": "synthetic (reverse E2ES)",
        "processing_facility": "s2_msi_raw_generator",
        "processing_datetime": inspection,
        "sensing_start": start,
        "sensing_stop": stop,
        "absolute_orbit": ab,
        "relative_orbit": rel,
        "inspection_datetime": inspection,
        "software": {
            "s2_msi_raw_generator": software_version,
            "eoqc_emulation": "s2_msi_raw_generator.quality_report",
        },
        "checks": [{"name": name, "result": "pass" if ok else "fail"} for name, ok in checks.items()],
        "overall_flag": "OK" if all(checks.values()) else "KO",
    }


def write_qc_report(path, report: dict) -> Path:
    """Write the QC report as standalone JSON (``QC_report_{name}.json`` convention). Returns the path."""
    p = Path(path)
    p.write_text(json.dumps(report, indent=2, sort_keys=False))
    return p

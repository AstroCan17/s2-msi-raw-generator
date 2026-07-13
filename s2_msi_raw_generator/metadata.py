"""Shared STAC / acquisition-identity metadata helpers.

Structure- and value-level parsing that ``io``, ``naming``, ``inventory`` and ``import_l0`` all need
for the same ESA-product quirks (the doubled ``stac_discovery`` nesting, ``"null"`` datetimes,
unfilled orbit XPaths, and the data-take id orbit fallback). The helpers only normalise structure and
coerce values; the *field-preference order* (``datetime`` vs ``start_datetime`` first, etc.) is left to
each caller because those orders are intentionally different.

Depends only on the standard library so it never introduces an import cycle within the package.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

#: Recovers the 6-digit absolute orbit embedded in EOPF data-take / datastrip id
#: (``GS2A_..._<orbit>_N...``).
DATATAKE_RE = re.compile(r"GS2[ABC]_[A-Z0-9_]+?_(?P<orbit>\d{6})_N")


def normalise_stac(attrs: dict) -> tuple[dict, dict, list[str]]:
    """Flatten root attributes to ``(stac, properties, flags)``.

    Handles the doubled ``stac_discovery.stac_discovery`` nesting seen in some ESA products,
    recording ``"double_stac_discovery"`` in ``flags`` when it is collapsed. Always returns plain
    dicts, even when the metadata is missing or malformed.
    """
    flags: list[str] = []
    stac = attrs.get("stac_discovery", {}) if isinstance(attrs, dict) else {}
    if isinstance(stac, dict) and isinstance(stac.get("stac_discovery"), dict):
        stac = stac["stac_discovery"]
        flags.append("double_stac_discovery")
    props = stac.get("properties", {}) if isinstance(stac, dict) else {}
    return (
        stac if isinstance(stac, dict) else {},
        props if isinstance(props, dict) else {},
        flags,
    )


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime; ``None``/``"null"`` yield ``None``."""
    if value is None or str(value).lower() == "null":
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def coerce_int(value: Any) -> tuple[int | None, bool]:
    """Coerce to ``int``; return ``(value, unparseable)``.

    A ``None`` input is treated as simply absent — ``(None, False)`` — whereas a present but
    non-integer value (e.g. an unfilled ``@@...@@`` XPath token) yields ``(None, True)`` so callers
    can distinguish "missing" from "malformed".
    """
    try:
        return int(value), False
    except (TypeError, ValueError):
        return None, value is not None


def absolute_orbit_from_datatake_id(dtid: Any) -> int | None:
    """Recover the absolute orbit from EOPF data-take / datastrip id, or ``None``."""
    if not dtid:
        return None
    m = DATATAKE_RE.search(str(dtid))
    return int(m["orbit"]) if m else None

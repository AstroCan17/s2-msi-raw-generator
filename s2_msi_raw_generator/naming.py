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

"""EOPF product file naming — the PSFD §3 product identification convention.

Implements the EOPF *Product Structure and Format Definition* (PSFD) §3 "Product Types and File
Naming Rules" scheme::

    MMMSSSCCC_YYYYMMDDTHHMMSS_UUUU_PRRR_XVVV[_Z*]

for the products this generator emits (L0 RAW, plus the L1A / L1B / ISP / SAD context types).
ECSS-M-ST-40C requires a project-wide unique product identification coding system; this module *is*
that system for the reverse E2ES (the interface is recorded in ``docs/icd.md``).

The grammar, field by field:

* ``MMMSSSCCC`` — the 9-character type code (mission ``S02`` + sensor + processing level); see
  :data:`TYPE_CODES`. A code ending in the pad character ``_`` yields the doubled underscore seen
  in real names, e.g. ``S02MSIL0__...``.
* ``YYYYMMDDTHHMMSS`` — acquisition start (UTC).
* ``UUUU`` — acquisition duration in whole seconds (4 digits, ``0001``–``9999``).
* ``PRRR`` — platform unit letter ``P`` + relative orbit ``RRR`` (``001``–``143``).
* ``XVVV`` — consolidation flag ``X`` + a 3 hex-digit discriminator ``VVV``.
* ``_Z*`` — an optional free token (segment / tile / role).

Examples (from the PSFD): ``S02MSIL0__20230216T182840_0001_A123_T000`` and
``S02MSIL1C_20230629T063559_0000_A064_T3A5``.
"""

from __future__ import annotations

import math
import re
import string
import zlib
from datetime import datetime, timezone

#: The 9-character product type codes emitted by this generator (PSFD §3), mapped to a short label.
#: The trailing ``_`` is the PSFD pad character (used when the level mnemonic is shorter than the
#: 3-character ``CCC`` field), so e.g. ``S02MSIL0_`` plus the ``_`` field separator reads
#: ``S02MSIL0__``.
TYPE_CODES: dict[str, str] = {
    "S02MSIL0_": "MSI Level-0 RAW",
    "S02MSIL1A": "MSI Level-1A",
    "S02MSIL1B": "MSI Level-1B",
    "S02MSIL1C": "MSI Level-1C",
    "S02MSIL2A": "MSI Level-2A",
    "S02MSIISP": "MSI CCSDS instrument source packets",
    "S02SADISP": "Satellite ancillary data packets",
}

#: Valid consolidation flags (the ``X`` field): ``T`` test / ``_`` nominal / ``S`` special.
CONSOLIDATION_FLAGS = frozenset({"T", "_", "S"})

#: Permitted product file extensions.
EXTENSIONS = frozenset({".zarr", ".zarr.zip", ""})

#: Fallback acquisition context used by :func:`from_l1a_context` when L1A metadata is missing
#: (the datation reference epoch, relative orbit 45, unit ``A``).
DEFAULT_START = datetime(2024, 4, 3, 10, 24, 15, tzinfo=timezone.utc)
DEFAULT_RELATIVE_ORBIT = 45
DEFAULT_UNIT = "A"

_START_FMT = "%Y%m%dT%H%M%S"

# One compiled grammar, built from the field definitions above, drives :func:`parse_psfd_name`.
_NAME_RE = re.compile(
    r"^(?P<product_type>[A-Z0-9_]{9})"
    r"_(?P<start>\d{8}T\d{6})"
    r"_(?P<duration>\d{4})"
    r"_(?P<unit>[A-Z])(?P<relative_orbit>\d{3})"
    r"_(?P<consolidation>[T_S])(?P<discriminator>[0-9A-F]{3})"
    r"(?:_(?P<z_suffix>[A-Za-z0-9_]+))?"
    r"(?P<ext>\.zarr\.zip|\.zarr)?$"
)


def _round_half_up(value: float) -> int:
    """Round ``value`` to the nearest whole number, with halves going up."""
    return math.floor(value + 0.5)


def _fmt_start(start_utc: datetime) -> str:
    """Format an acquisition start as ``YYYYMMDDTHHMMSS`` (aware datetimes are converted to UTC)."""
    if start_utc.tzinfo is not None:
        start_utc = start_utc.astimezone(timezone.utc)
    return start_utc.strftime(_START_FMT)


def psfd_name(
    product_type: str,
    start_utc: datetime,
    duration_s: float,
    *,
    unit: str = "A",
    relative_orbit: int,
    consolidation: str = "T",
    discriminator: str | None = None,
    z_suffix: str | None = None,
    ext: str = ".zarr",
) -> str:
    """Build a PSFD §3 product file name.

    Parameters
    ----------
    product_type : str
        The 9-character type code; must be one of :data:`TYPE_CODES`.
    start_utc : datetime.datetime
        Acquisition start time. Timezone-aware values are converted to UTC; naive values are
        formatted as given.
    duration_s : float
        Acquisition duration in seconds, rounded half-up to a whole second and clamped to a minimum
        of 1. A value rounding above 9999 is rejected.
    unit : str, optional
        Platform unit — a single upper-case letter (the ``P`` field). Default ``"A"``.
    relative_orbit : int
        Relative orbit number in 1..143 (the Sentinel-2 repeat cycle).
    consolidation : str, optional
        Consolidation flag (the ``X`` field); one of :data:`CONSOLIDATION_FLAGS`. Default ``"T"``.
    discriminator : str or None, optional
        Three upper-case hex characters (the ``VVV`` field). When ``None`` (default) a deterministic
        value is derived from the other fields via ``zlib.crc32``.
    z_suffix : str or None, optional
        Optional free token appended as ``_<z_suffix>`` (letters, digits and underscores only).
    ext : str, optional
        File extension; one of :data:`EXTENSIONS`. Default ``".zarr"``.

    Returns
    -------
    str
        The composed product file name.

    Raises
    ------
    ValueError
        If any field is invalid (unknown type code, out-of-range orbit or duration, or a malformed
        unit, consolidation, discriminator, ``z_suffix`` or extension).

    Examples
    --------
    >>> from datetime import datetime
    >>> psfd_name("S02MSIL0_", datetime(2024, 4, 3, 10, 24, 15), 33.0,
    ...           relative_orbit=45, discriminator="1A2")
    'S02MSIL0__20240403T102415_0033_A045_T1A2.zarr'
    """
    if len(product_type) != 9:
        raise ValueError(f"product_type must be exactly 9 characters, got {product_type!r}")
    if product_type not in TYPE_CODES:
        raise ValueError(
            f"unknown product type code {product_type!r}; expected one of {sorted(TYPE_CODES)}")
    if not (len(unit) == 1 and unit in string.ascii_uppercase):
        raise ValueError(f"unit must be a single upper-case letter A-Z, got {unit!r}")
    if not 1 <= relative_orbit <= 143:
        raise ValueError(f"relative_orbit must be in 1..143, got {relative_orbit}")
    if consolidation not in CONSOLIDATION_FLAGS:
        raise ValueError(
            f"consolidation must be one of {sorted(CONSOLIDATION_FLAGS)}, got {consolidation!r}")
    if ext not in EXTENSIONS:
        raise ValueError(f"ext must be one of {sorted(EXTENSIONS)}, got {ext!r}")

    duration = _round_half_up(duration_s)
    if duration > 9999:
        raise ValueError(f"duration {duration_s} s exceeds the 4-digit field maximum (9999 s)")
    duration = max(duration, 1)

    start_str = _fmt_start(start_utc)
    if discriminator is None:
        seed = f"{product_type}{start_str}{duration}{unit}{relative_orbit}"
        discriminator = f"{zlib.crc32(seed.encode('utf-8')):03X}"[-3:]
    elif not re.fullmatch(r"[0-9A-F]{3}", discriminator):
        raise ValueError(
            f"discriminator must be three upper-case hex characters, got {discriminator!r}")

    name = (f"{product_type}_{start_str}_{duration:04d}"
            f"_{unit}{relative_orbit:03d}_{consolidation}{discriminator}")
    if z_suffix is not None:
        if not re.fullmatch(r"[A-Za-z0-9_]+", z_suffix):
            raise ValueError(
                f"z_suffix must be letters, digits or underscores, got {z_suffix!r}")
        name += f"_{z_suffix}"
    return name + ext


def parse_psfd_name(name: str) -> dict:
    """Parse a PSFD §3 product file name into its fields — the inverse of :func:`psfd_name`.

    Parameters
    ----------
    name : str
        A product file name, with or without an extension and with or without the optional
        ``_<z_suffix>`` token.

    Returns
    -------
    dict
        Keys ``product_type``, ``start_utc`` (a naive :class:`datetime.datetime` on UTC),
        ``duration_s`` (:class:`int`), ``unit``, ``relative_orbit`` (:class:`int`),
        ``consolidation``, ``discriminator``, ``z_suffix`` (``str`` or ``None``) and ``ext``.

    Raises
    ------
    ValueError
        If ``name`` does not match the grammar or carries an unknown type code.
    """
    m = _NAME_RE.match(name)
    if m is None:
        raise ValueError(f"not a valid PSFD product name: {name!r}")
    product_type = m["product_type"]
    if product_type not in TYPE_CODES:
        raise ValueError(f"unknown product type code {product_type!r} in {name!r}")
    return {
        "product_type": product_type,
        "start_utc": datetime.strptime(m["start"], _START_FMT),
        "duration_s": int(m["duration"]),
        "unit": m["unit"],
        "relative_orbit": int(m["relative_orbit"]),
        "consolidation": m["consolidation"],
        "discriminator": m["discriminator"],
        "z_suffix": m["z_suffix"],
        "ext": m["ext"] or "",
    }


def _unit_from_platform(platform: str) -> str | None:
    """Derive the single-letter platform unit from a STAC ``platform`` string.

    ``"sentinel-2a"`` maps to ``"A"``. Returns ``None`` when no A–Z unit can be read.
    """
    token = platform.strip().upper()[-1:] if platform else ""
    return token if len(token) == 1 and token in string.ascii_uppercase else None


def from_l1a_context(
    attrs: dict,
    *,
    n_lines: int,
    line_period_s: float,
    product_type: str,
    ext: str = ".zarr",
) -> tuple[str, dict]:
    """Derive a product name from an L1A / L1B product's root attributes.

    Reads the acquisition start, relative orbit and platform unit from the STAC discovery metadata
    (``attrs["stac_discovery"]["properties"]``) and computes the duration as
    ``n_lines * line_period_s``. Any field that is absent falls back to a module default
    (:data:`DEFAULT_START`, :data:`DEFAULT_RELATIVE_ORBIT`, :data:`DEFAULT_UNIT`) and is recorded in
    the returned info dict under ``"derived_from_defaults"``.

    Parameters
    ----------
    attrs : dict
        The source product's root attributes (STAC discovery under ``"stac_discovery"``).
    n_lines : int
        Number of acquired lines (sets the duration together with ``line_period_s``).
    line_period_s : float
        Line period in seconds.
    product_type : str
        The 9-character type code for the derived product (see :data:`TYPE_CODES`).
    ext : str, optional
        File extension. Default ``".zarr"``.

    Returns
    -------
    tuple of (str, dict)
        The product name and an info dict ``{"derived_from_defaults": [field, ...]}`` naming each
        STAC field that fell back to a default.
    """
    props: dict = {}
    if isinstance(attrs, dict):
        sd = attrs.get("stac_discovery")
        if isinstance(sd, dict) and isinstance(sd.get("properties"), dict):
            props = sd["properties"]
    fallbacks: list[str] = []

    iso = props.get("datetime") or props.get("start_datetime")
    if iso:
        start_utc = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    else:
        start_utc = DEFAULT_START
        fallbacks.append("datetime")

    relative_orbit = props.get("sat:relative_orbit")
    if relative_orbit is None:
        relative_orbit = DEFAULT_RELATIVE_ORBIT
        fallbacks.append("sat:relative_orbit")

    unit = _unit_from_platform(props.get("platform", ""))
    if unit is None:
        unit = DEFAULT_UNIT
        fallbacks.append("platform")

    name = psfd_name(
        product_type,
        start_utc,
        n_lines * line_period_s,
        unit=unit,
        relative_orbit=int(relative_orbit),
        ext=ext,
    )
    return name, {"derived_from_defaults": fallbacks}

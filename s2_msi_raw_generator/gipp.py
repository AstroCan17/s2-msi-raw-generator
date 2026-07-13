"""Reader for Sentinel-2 operational GIPP calibration data.

Production layout: band-organised JSON under ``S2_GIPP_DIR`` (``aux/gipp-json/{Bxx}/S2B_ADF_*.json``),
each file wrapping the documented ``GS2_*`` schema (XML-to-JSON conversion). Unit tests may still
use flat XML fixtures (``*GIP_*.xml``).

The parser turns GIPP into per-band / per-detector / per-pixel numpy arrays the reverse chain needs:

* **R2EQOG** — the on-ground equalization file: per-pixel **dark signal** ``D`` and the
  **relative-response (PRNU) gains** — VNIR cubic ``(A, B, C)`` (``Y = A·Z³+B·Z²+C·Z``) or SWIR
  bilinear ``(A1, A2, Zs)`` (``Y = A1·Z`` for ``Z≤Zs`` else ``A2·Z+(A1−A2)·Zs``). Per the public
  Sentinel-2 L1 ATBD §4.1.1, ``C`` (VNIR) / ``A1`` (SWIR) is the dominant per-pixel relative gain.
* **R2DEPI** — defective (saturated + blind) pixel columns per band/detector.
* **BLINDP** — blind-pixel column lists per band/detector/side.
* **R2PARA** — per-band equalization/offset flags + radiometric offsets (−100 L1B / −1000 L1C).
* **R2CRCO** / **R2BINN** — crosstalk matrix (≈0 for S2A) / 60 m binning kernel.

Band order follows ``sensor.BANDS`` (``band_id`` 0…12 → B01…B08, B8A, B09…B12).
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np

from . import sensor

# JSON ADF type → (schema root key, per-band file?)
_JSON_ADF: dict[str, tuple[str, bool]] = {
    "REQOG": ("GS2_RADIOS2_EQUALIZATION_ONGROUND", True),
    "RDEPI": ("GS2_RADIOS2_DEFECTIVE_PIXELS", False),
    "BLIND": ("GS2_BLIND_PIXELS", False),
    "RPARA": ("GS2_RADIOS2_PARAMETERS", False),
    "RCRCO": ("GS2_RADIOS2_CROSSTALK_CORRECTION", False),
}
# XML GIPP type names for flat-xml fixtures
_XML_GTYPE = {"REQOG": "R2EQOG", "RDEPI": "R2DEPI", "BLIND": "BLINDP", "RPARA": "R2PARA", "RCRCO": "R2CRCO"}

# GIPP band_id (0..12) → canonical band name. Matches sensor.BANDS exactly (B8A at index 8).
_BAND_BY_ID: tuple[str, ...] = sensor.BANDS


def _band_name(band_id: int) -> str:
    return _BAND_BY_ID[band_id]


def _floats(text: str | None) -> np.ndarray:
    """Parse a whitespace-separated list of floats robustly (ignores stray tokens)."""
    if not text:
        return np.empty(0, dtype=np.float64)
    out = []
    for tok in text.split():
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return np.asarray(out, dtype=np.float64)


def _find_one(gipp_dir: str, gtype: str) -> str:
    """Path of the single ``*GIP_<gtype>_*.xml`` file in ``gipp_dir``."""
    hits = sorted(glob.glob(os.path.join(gipp_dir, f"*GIP_{gtype}_*.xml")))
    if not hits:
        raise FileNotFoundError(f"no {gtype} GIPP under {gipp_dir!r}")
    return hits[0]


def _find_band(gipp_dir: str, gtype: str, band: str) -> str:
    """Path of the per-band ``*GIP_<gtype>_*_<band>.xml`` (e.g. R2EQOG B03)."""
    suffix = band  # files end in …_B03.xml / …_B8A.xml
    hits = sorted(glob.glob(os.path.join(gipp_dir, f"*GIP_{gtype}_*_{suffix}.xml")))
    if not hits:
        raise FileNotFoundError(f"no {gtype} GIPP for band {band} under {gipp_dir!r}")
    return hits[0]


def _gipp_layout(gipp_dir: str) -> Literal["json-bands", "xml-flat"]:
    """Detect ``gipp-json`` band folders vs flat ``gipp-xml`` fixture layout."""
    if any(Path(gipp_dir, d).is_dir() and list(Path(gipp_dir, d).glob("*_ADF_*.json"))
           for d in os.listdir(gipp_dir) if d.startswith("B")):
        return "json-bands"
    if glob.glob(os.path.join(gipp_dir, "*GIP_*.xml")):
        return "xml-flat"
    raise FileNotFoundError(f"no recognised GIPP layout under {gipp_dir!r}")


def _find_json_adf(gipp_dir: str, adf_type: str, band: str | None = None) -> str:
    """Locate ``S*_ADF_<adf_type>_*.json`` in a band folder (or ``B00`` for global ADFs)."""
    folder = band if band else "B00"
    hits = sorted(glob.glob(os.path.join(gipp_dir, folder, f"*_ADF_{adf_type}_*.json")))
    if not hits:
        raise FileNotFoundError(
            f"no ADF_{adf_type} JSON for band {band or 'global'} under {gipp_dir!r}"
        )
    return hits[0]


def _load_json_gipp(path: str) -> tuple[str, dict]:
    """Load a GIPP JSON file → ``(schema_root_key, DATA dict)``."""
    with open(path, encoding="utf-8") as fh:
        root = json.load(fh)
    if not root:
        raise ValueError(f"empty GIPP JSON: {path}")
    schema_key = next(iter(root))
    data = root[schema_key].get("DATA")
    if data is None:
        raise KeyError(f"no DATA in {path!r} ({schema_key})")
    return schema_key, data


def _jattr(node: dict, name: str, default: str | None = None) -> str | None:
    if not isinstance(node, dict):
        return default
    return node.get(f"@{name}") or node.get(name) or default


def _jtext(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("#text") or val.get("_text")
    return None


def _jlist(node) -> list:
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def _parse_coeff_d_json(coeff_d_node: dict) -> np.ndarray:
    """JSON COEFF_D → per-pixel dark (mean over along-track sub-lines)."""
    band_el = coeff_d_node
    for k, v in coeff_d_node.items():
        if isinstance(k, str) and k.startswith("A_") and k.endswith("_BAND"):
            band_el = v
            break
    if not isinstance(band_el, dict):
        return _floats(_jtext(band_el))
    line_keys = sorted((k for k in band_el if str(k).upper().startswith("LINE")), key=str)
    if line_keys:
        rows = [_floats(_jtext(band_el[k])) for k in line_keys]
        return np.mean(np.stack(rows), axis=0)
    return _floats(_jtext(band_el))


def _parse_r2eqog_data(data: dict, band: str) -> BandEq:
    clist = data["COEFFICIENTS_LIST"]
    tdi_raw = _jattr(clist, "tdi_config") or clist.get("tdi_config") or "NO_TDI"
    tdi = str(tdi_raw).upper() == "APPLIED"
    detectors: dict[int, DetectorEq] = {}
    for coeff in _jlist(clist.get("COEFFICIENTS")):
        det = int(_jattr(coeff, "detector_id"))
        ge = coeff["GROUND_EQUALIZATION"]
        cubic = ge.get("CUBIC")
        bilinear = ge.get("BI-LINEAR") or ge.get("BI_LINEAR")
        if cubic is not None:
            cf = {k: _floats(_jtext(cubic.get(f"COEFF_{k}"))) for k in ("A", "B", "C")}
            dark = _parse_coeff_d_json(cubic["COEFF_D"])
            detectors[det] = DetectorEq("CUBIC", dark, cf)
        else:
            cf = {
                "A1": _floats(_jtext(bilinear["COEFF_A1"])),
                "A2": _floats(_jtext(bilinear["COEFF_A2"])),
                "Zs": _floats(_jtext(bilinear["COEFF_Zs"])),
            }
            dark = _parse_coeff_d_json(bilinear["COEFF_D"])
            detectors[det] = DetectorEq("BILINEAR", dark, cf)
    return BandEq(band=band, tdi=tdi, detectors=detectors, source="GIPP JSON REQOG")


def read_r2eqog_json(gipp_dir: str, band: str) -> BandEq:
    """Parse per-band ``ADF_REQOG`` JSON → :class:`BandEq`."""
    path = _find_json_adf(gipp_dir, "REQOG", band)
    _, data = _load_json_gipp(path)
    return _parse_r2eqog_data(data, band)


def _parse_r2depi_data(data: dict) -> dict[str, dict[int, np.ndarray]]:
    out: dict[str, dict[int, np.ndarray]] = {}
    for band_el in _jlist(data.get("BAND")):
        band = _band_name(int(_jattr(band_el, "band_id")))
        per_det: dict[int, set] = {d: set() for d in range(1, 13)}
        slist = band_el.get("SINGULARITY_LIST") or band_el
        for sing in _jlist(slist.get("SINGULARITY") if isinstance(slist, dict) else None):
            for pos in _jlist(sing.get("POSITION")):
                det = int(_jattr(pos, "detector_id"))
                cols = pos.get("COLUMNS")
                text = _jtext(cols)
                if text:
                    per_det[det].update(int(x) for x in text.split())
        out[band] = {d: np.array(sorted(c), dtype=int) for d, c in per_det.items()}
    return out


def read_r2depi_json(gipp_dir: str) -> dict[str, dict[int, np.ndarray]]:
    path = _find_json_adf(gipp_dir, "RDEPI")
    _, data = _load_json_gipp(path)
    return _parse_r2depi_data(data)


def _parse_blindp_data(data: dict) -> dict[str, dict[int, np.ndarray]]:
    out: dict[str, dict[int, np.ndarray]] = {}
    for band_el in _jlist(data.get("BAND")):
        band = _band_name(int(_jattr(band_el, "band_id")))
        per_det: dict[int, np.ndarray] = {}
        for det_el in _jlist(band_el.get("DETECTOR")):
            det = int(_jattr(det_el, "detector_id"))
            cols: set = set()
            for side in _jlist(det_el.get("SIDE")):
                for tag in ("VALID_BLIND_PIXELS", "NON_VALID_BLIND_PIXELS"):
                    text = _jtext(side.get(tag))
                    if text:
                        cols.update(int(x) for x in text.split())
            per_det[det] = np.array(sorted(cols), dtype=int)
        out[band] = per_det
    return out


def read_blindp_json(gipp_dir: str) -> dict[str, dict[int, np.ndarray]]:
    path = _find_json_adf(gipp_dir, "BLIND")
    _, data = _load_json_gipp(path)
    return _parse_blindp_data(data)


def _parse_r2para_data(data: dict) -> RadioParams:
    def _offsets_from_node(node) -> dict[str, int]:
        res: dict[str, int] = {}
        for el in _jlist(node):
            if isinstance(el, dict) and "RADIO_ADD_OFFSET" in str(el):
                pass
        for el in _jlist(node.get("RADIO_ADD_OFFSET") if isinstance(node, dict) else node):
            bid = int(_jattr(el, "band_id"))
            res[_band_name(bid)] = int(float(_jtext(el)))
        return res

    shift = data.get("RADIOMETRIC_SHIFT") or next(
        (v for k, v in data.items() if "RADIOMETRIC_SHIFT" in str(k)), {}
    )
    l1b_node = shift.get("RADIANCE_OFFSET_L1B") if isinstance(shift, dict) else {}
    l1c_node = shift.get("REFLECTANCE_OFFSET_L1C") if isinstance(shift, dict) else {}
    l1b = _offsets_from_node(l1b_node)
    l1c = _offsets_from_node(l1c_node)
    eq, off, dsnu = {}, {}, {}
    nom = data.get("NOMINAL_SCENARIO") or data
    eq_block = nom.get("EQUALIZATION") if isinstance(nom, dict) else {}
    for be in _jlist(eq_block.get("BAND_EQUALIZATION") if isinstance(eq_block, dict) else None):
        bid = be.get("BAND_ID") or _jattr(be, "band_id")
        b = _band_name(int(bid) if bid is not None else int(_jattr(be, "band_id")))
        eq[b] = (_jtext(be.get("EQUALIZATION_FLAG")) or "true").lower() == "true"
        off[b] = (_jtext(be.get("OFFSET")) or "true").lower() == "true"
        dsnu[b] = (_jtext(be.get("DARK_SIGNAL_NON_UNIFORMITY")) or "true").lower() == "true"
    return RadioParams(l1b, l1c, eq, off, dsnu)


def read_r2para_json(gipp_dir: str) -> RadioParams:
    path = _find_json_adf(gipp_dir, "RPARA")
    _, data = _load_json_gipp(path)
    return _parse_r2para_data(data)


def _parse_r2crco_data(data: dict) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    clist = data.get("CROSSTALK_COEFF_LIST") or data
    for cc in _jlist(clist.get("CROSSTALK_COEFF") if isinstance(clist, dict) else None):
        band = _band_name(int(_jattr(cc, "band_id_k")))
        opt = _floats(_jtext(cc.get("OPTICAL")))
        ele = _floats(_jtext(cc.get("ELECTRICAL")))
        out[band] = opt + ele
    return out


def read_r2crco_json(gipp_dir: str) -> dict[str, np.ndarray]:
    path = _find_json_adf(gipp_dir, "RCRCO")
    _, data = _load_json_gipp(path)
    return _parse_r2crco_data(data)


# --- R2EQOG (equalization on-ground: dark + relative-response gains) ----------------------

@dataclass(frozen=True)
class DetectorEq:
    """Per-detector R2EQOG coefficients (each array is per across-track pixel, length NB_OF_PIXELS)."""

    model: str                      # "CUBIC" (VNIR) | "BILINEAR" (SWIR)
    dark: np.ndarray                # (act,) per-pixel dark signal D (mean over the COEFF_D sub-lines)
    coeffs: dict[str, np.ndarray]   # CUBIC: {A, B, C}; BILINEAR: {A1, A2, Zs}

    @property
    def rel_gain(self) -> np.ndarray:
        """Dominant per-pixel relative-response (PRNU) gain: C for VNIR, A1 for SWIR."""
        return self.coeffs["C"] if self.model == "CUBIC" else self.coeffs["A1"]


@dataclass(frozen=True)
class BandEq:
    band: str
    tdi: bool
    detectors: dict[int, DetectorEq]  # detector 1..12
    source: str = "GIPP R2EQOG"       # provenance: "GIPP R2EQOG" (XML) | "ESA EOPF ADF_REQOG"

    @property
    def npix(self) -> int:
        return int(self.detectors[1].dark.size)


def _parse_coeff_d(coeff_d_el: ET.Element) -> np.ndarray:
    """COEFF_D → per-pixel dark, collapsing the along-track sub-lines (6/3/1) to their mean (act,)."""
    band_el = list(coeff_d_el)[0]  # <A_10M_BAND> / <A_20M_BAND> / <A_60M_BAND>
    line_els = [c for c in band_el if c.tag.upper().startswith("LINE")]
    if line_els:
        rows = [_floats(c.text) for c in sorted(line_els, key=lambda e: e.tag)]
        return np.mean(np.stack(rows), axis=0)
    return _floats(band_el.text)


def read_r2eqog_band(gipp_dir: str, band: str) -> BandEq:
    """Parse per-band equalization (JSON ``gipp-json`` or XML fixture layout)."""
    if _gipp_layout(gipp_dir) == "json-bands":
        return read_r2eqog_json(gipp_dir, band)
    root = ET.parse(_find_band(gipp_dir, "R2EQOG", band)).getroot()
    data = root.find("DATA")
    clist = data.find("COEFFICIENTS_LIST")
    tdi = (clist.get("tdi_config") or "NO_TDI").upper() == "APPLIED"
    detectors: dict[int, DetectorEq] = {}
    for coeff in clist.findall("COEFFICIENTS"):
        det = int(coeff.get("detector_id"))
        ge = coeff.find("GROUND_EQUALIZATION")
        cubic, bilinear = ge.find("CUBIC"), ge.find("BI-LINEAR")
        if cubic is not None:
            cf = {k: _floats(cubic.find(f"COEFF_{k}").text) for k in ("A", "B", "C")}
            dark = _parse_coeff_d(cubic.find("COEFF_D"))
            detectors[det] = DetectorEq("CUBIC", dark, cf)
        else:
            cf = {"A1": _floats(bilinear.find("COEFF_A1").text),
                  "A2": _floats(bilinear.find("COEFF_A2").text),
                  "Zs": _floats(bilinear.find("COEFF_Zs").text)}
            dark = _parse_coeff_d(bilinear.find("COEFF_D"))
            detectors[det] = DetectorEq("BILINEAR", dark, cf)
    return BandEq(band=band, tdi=tdi, detectors=detectors)


# --- R2EQOG from EOPF ADF (.json) -----------------------------------------------------

@lru_cache(maxsize=4)
def _load_eopf_adf(adf_json_path: str) -> dict:
    """Parse EOPF ADF json once (cached — the R2EQOG ADF is ~60 MB per satellite)."""
    with open(adf_json_path, encoding="utf-8") as fh:
        return json.load(fh)


def read_r2eqog_eopf(adf_json_path: str, band: str) -> BandEq:
    """Parse EOPF ``ADF_REQOG`` (``S2[AB]_ADF_REQOG_…json``) → the same :class:`BandEq` as the
    XML :func:`read_r2eqog_band`.

    The EOPF ADF stores, per band ``<b>`` (lower-case; ``b8a`` for B8A) over 12 detectors: VNIR cubic
    ``<b>/coeff_{a,b,c}`` (→ ``A,B,C``) or SWIR bilinear ``<b>/coeff_{a1,a2,zs}`` (→ ``A1,A2,Zs``),
    plus ``<b>/coeff_d`` = dark signal. ``coeff_d`` may carry along-track sub-lines
    (``(det, n_line, act)``); these are collapsed to their mean, matching the XML ``COEFF_D``
    convention in :func:`_parse_coeff_d`.
    """
    dv = _load_eopf_adf(adf_json_path)["data_vars"]
    bkey = band.lower()

    def _arr(name: str) -> np.ndarray | None:
        node = dv.get(f"{bkey}/{name}")
        return None if node is None else np.asarray(node["data"], dtype=np.float64)

    coeff_d = _arr("coeff_d")
    if coeff_d is None:
        raise KeyError(f"EOPF R2EQOG ADF has no band {band!r} ({adf_json_path!r})")
    a1 = _arr("coeff_a1")
    swir = a1 is not None
    if swir:
        a2, zs = _arr("coeff_a2"), _arr("coeff_zs")
    else:
        a, b, c = _arr("coeff_a"), _arr("coeff_b"), _arr("coeff_c")

    detectors: dict[int, DetectorEq] = {}
    for i in range(coeff_d.shape[0]):            # detector index 0..11 → detector_id 1..12
        dk = coeff_d[i]
        dark = dk.mean(axis=0) if dk.ndim == 2 else dk    # collapse sub-lines → (act,)
        if swir:
            detectors[i + 1] = DetectorEq("BILINEAR", dark, {"A1": a1[i], "A2": a2[i], "Zs": zs[i]})
        else:
            detectors[i + 1] = DetectorEq("CUBIC", dark, {"A": a[i], "B": b[i], "C": c[i]})
    return BandEq(band=band, tdi=False, detectors=detectors, source="ESA EOPF ADF_REQOG")


# --- ADF temporal validity ---------------------------------------------------------------

_EOPF_ADF_RE = re.compile(
    r"(?P<platform>S0?2[ABC])_ADF_(?P<type>[A-Z0-9]+)_"
    r"(?P<start>\d{8}T\d{6})_(?P<stop>\d{8}T\d{6})_(?P<creation>\d{8}T\d{6})"
)


def _iso(stamp: str) -> str:
    """``YYYYMMDDThhmmss`` → ``YYYY-MM-DDThh:mm:ssZ``."""
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def _parse_utc(s: str) -> dt.datetime:
    """Tolerant UTC parse (ISO or compact ``YYYYMMDDThhmmss``) → tz-naive datetime."""
    s = s.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        m = re.search(r"(\d{8})T?(\d{6})?", s)
        if not m:
            raise
        d, t = m.group(1), m.group(2) or "000000"
        return dt.datetime(int(d[:4]), int(d[4:6]), int(d[6:8]),
                           int(t[:2]), int(t[2:4]), int(t[4:6]))


def parse_eqog_adf_epoch(adf_path: str) -> dict:
    """Parse EOPF ADF filename (``S2A_ADF_REQOG_<start>_<stop>_<creation>.json``, or the PSFD
    platform spelling ``S02B_ADF_…``) → its applicability-start / validity-stop / creation epochs
    (UTC ISO). Empty dict if it doesn't match. ``platform`` is normalized to ``S2x``.
    """
    m = _EOPF_ADF_RE.search(os.path.basename(adf_path))
    if not m:
        return {}
    return {
        "platform": m["platform"].replace("S02", "S2"),
        "type": m["type"],
        "applicability_start": _iso(m["start"]),
        "valid_stop": _iso(m["stop"]),
        "creation": _iso(m["creation"]),
    }


def temporal_validity(adf_epoch: dict, acquisition_utc: str, warn_years: float = 1.0) -> dict:
    """Check an ADF's temporal applicability to an acquisition.

    ``within_validity`` uses the ADF's declared ``[applicability_start, valid_stop]`` window — but
    note the ``2100`` stop is an open-ended placeholder, **not** proof of applicability. So the operational
    signal is ``gap_years`` = ``|acquisition − applicability_start|``: the satellite's radiometric
    state drifts (monthly-refreshed R2EQOG/R2ABCA), and a stale ADF is flagged (``warn``) when the
    gap exceeds ``warn_years`` or the acquisition falls outside the declared window.
    """
    acq = _parse_utc(acquisition_utc)
    start = _parse_utc(adf_epoch["applicability_start"])
    stop = _parse_utc(adf_epoch["valid_stop"])
    within = start <= acq <= stop
    gap_days = abs((acq - start).days)
    gap_years = round(gap_days / 365.25, 2)
    warn = (gap_years > warn_years) or not within
    msg = (f"ADF {adf_epoch.get('type', '?')} applicability {adf_epoch['applicability_start'][:10]} "
           f"vs acquisition {acquisition_utc[:10]}: gap {gap_years} yr"
           + ("" if within else " — OUTSIDE declared validity window")
           + (f" — TEMPORAL MISMATCH (>{warn_years:g} yr)" if gap_years > warn_years else ""))
    return {
        "within_validity": within,
        "gap_days": gap_days,
        "gap_years": gap_years,
        "warn": warn,
        "message": msg,
        "adf_epoch": adf_epoch,
        "acquisition_utc": acquisition_utc,
    }


# --- RSWIR (SWIR staggered-readout shift map) from EOPF ADF ----------------------------

# RSWIR `swir_band_list/swir_band/detector` band axis order (confirmed from the ADF coords).
_RSWIR_BANDS: tuple[str, ...] = ("B10", "B11", "B12")


def read_rswir_eopf(adf_json_path: str, band: str, detector: int) -> tuple[np.ndarray, np.ndarray, str]:
    """EOPF ``ADF_RSWIR`` → the SWIR staggered-readout shift map for one ``band``/``detector``.

    Returns ``(shifts, kernel, method)``:

    * ``shifts`` — per across-track column integer flag in ``{−1, 0, +1}`` (``swir_band_list/
      swir_band/detector`` at ``[band, detector, :]``). The **sign** marks which columns move and
      the direction; the **magnitude** is set by ``method`` (whole line vs sub-pixel).
    * ``kernel`` — the ``interpolation_filter/coefs`` 3-tap sub-pixel filter (only used for B10).
    * ``method`` — ``"shift"`` (B11/B12: ±1 whole-line roll) or ``"interp"`` (B10: ±1/3 line via
      ``kernel`` convolution).

    Only B10/B11/B12 have an entry; ``band`` must be one of those (else :class:`KeyError`).
    """
    if band.upper() not in _RSWIR_BANDS:
        raise KeyError(f"RSWIR only covers {_RSWIR_BANDS}, not {band!r}")
    dv = _load_eopf_adf(adf_json_path)["data_vars"]
    bi = _RSWIR_BANDS.index(band.upper())
    sm = np.asarray(dv["swir_band_list/swir_band/detector"]["data"])   # (3, 12, act)
    shifts = np.rint(sm[bi, detector - 1]).astype(int)
    kernel = np.asarray(dv["interpolation_filter/coefs"]["data"], dtype=np.float64)
    method = "interp" if band.upper() == "B10" else "shift"
    return shifts, kernel, method


# --- REOB2 (on-board equalization, 2-table) from EOPF ADF ------------------------------

def read_reob2_eopf(adf_json_path: str, band: str, detector: int,
                    table: str = "new_table") -> dict[str, np.ndarray]:
    """EOPF ``ADF_REOB2`` → per-pixel on-board-equalization coefficients for one ``band``/``detector``.

    The forward L1B step 1 (``inverse_equalization``) undoes the on-board bilinear equalization::

        Z = where(Y ≤ a1·zs, Y/a1, (Y − (a1−a2)·zs)/a2);   X = Z + d

    so the E2ES **re-application** (raw X → downlink Y) is ``Y = where(Z ≤ zs, a1·Z, a2·Z +
    (a1−a2)·zs)`` with ``Z = X − d`` (see :func:`~s2_msi_raw_generator.forward_radiometric_atbd.
    reapply_onboard_eq`). Returns ``{a1, a2, zs, d}`` each ``(act,)`` from ``<band>/<table>/coeff_*``
    (default the operational ``new_table``). For S2B ``a1≈1.005, a2≈0.995`` (near-unity slope) and
    ``d≈455`` (the raw-detector dark, i.e. the R2EQOG COEFF_D domain).
    """
    dv = _load_eopf_adf(adf_json_path)["data_vars"]
    bk = band.lower()

    def _a(name: str) -> np.ndarray:
        return np.asarray(dv[f"{bk}/{table}/coeff_{name}"]["data"], dtype=np.float64)[detector - 1]

    return {"a1": _a("a1"), "a2": _a("a2"), "zs": _a("zs"), "d": _a("d")}


# --- RCRCO (inter-band crosstalk) from EOPF ADF ---------------------------------------

def read_rcrco_eopf(adf_json_path: str) -> np.ndarray:
    """EOPF ``ADF_RCRCO`` → the combined crosstalk matrix ``dtalk[k, l]`` (optical + electrical).

    ``13×13`` over ``band_k`` (impacted) × ``band_l`` (impacting), in ``sensor.BANDS`` order. The
    forward correction is ``X_corr_k = X_k − Σ_l dtalk[k,l]·X_l``; the E2ES re-application adds it
    back. For S2A/B optical is exactly 0 and electrical peaks at ≈0.004 — a near-no-op kept for
    completeness.
    """
    dv = _load_eopf_adf(adf_json_path)["data_vars"]
    opt = np.asarray(dv["optical"]["data"], dtype=np.float64)
    ele = np.asarray(dv["electrical"]["data"], dtype=np.float64)
    return opt + ele


# --- R2DEPI (defective pixels) + BLINDP (blind pixels) -----------------------------------

def read_r2depi(gipp_dir: str) -> dict[str, dict[int, np.ndarray]]:
    """Defective (saturated ∪ blind) 0-based across-track column indices, per band → detector."""
    if _gipp_layout(gipp_dir) == "json-bands":
        return read_r2depi_json(gipp_dir)
    root = ET.parse(_find_one(gipp_dir, "R2DEPI")).getroot()
    out: dict[str, dict[int, np.ndarray]] = {}
    for band_el in root.iter("BAND"):
        band = _band_name(int(band_el.get("band_id")))
        per_det: dict[int, set] = {d: set() for d in range(1, 13)}
        for sing in band_el.iter("SINGULARITY"):
            for pos in sing.findall("POSITION"):
                det = int(pos.get("detector_id"))
                cols = pos.find("COLUMNS")
                if cols is not None and cols.text:
                    per_det[det].update(int(x) for x in cols.text.split())
        out[band] = {d: np.array(sorted(c), dtype=int) for d, c in per_det.items()}
    return out


def read_blindp(gipp_dir: str) -> dict[str, dict[int, np.ndarray]]:
    """Blind-pixel 0-based column indices (valid ∪ non-valid, both sides), per band → detector."""
    if _gipp_layout(gipp_dir) == "json-bands":
        return read_blindp_json(gipp_dir)
    root = ET.parse(_find_one(gipp_dir, "BLINDP")).getroot()
    out: dict[str, dict[int, np.ndarray]] = {}
    for band_el in root.iter("BAND"):
        band = _band_name(int(band_el.get("band_id")))
        per_det: dict[int, np.ndarray] = {}
        for det_el in band_el.findall("DETECTOR"):
            det = int(det_el.get("detector_id"))
            cols: set = set()
            for side in det_el.findall("SIDE"):
                for tag in ("VALID_BLIND_PIXELS", "NON_VALID_BLIND_PIXELS"):
                    el = side.find(tag)
                    if el is not None and el.text:
                        cols.update(int(x) for x in el.text.split())
            per_det[det] = np.array(sorted(cols), dtype=int)
        out[band] = per_det
    return out


# --- R2PARA (offsets + flags) + R2CRCO + R2BINN ------------------------------------------

@dataclass(frozen=True)
class RadioParams:
    radiance_offset_l1b: dict[str, int]      # per band, −100
    reflectance_offset_l1c: dict[str, int]   # per band, −1000
    equalization_flag: dict[str, bool]
    offset_flag: dict[str, bool]
    dsnu_flag: dict[str, bool]


def read_r2para(gipp_dir: str) -> RadioParams:
    if _gipp_layout(gipp_dir) == "json-bands":
        return read_r2para_json(gipp_dir)
    root = ET.parse(_find_one(gipp_dir, "R2PARA")).getroot()
    data = root.find("DATA")

    def _offsets(parent_tag: str) -> dict[str, int]:
        node = data.iter(parent_tag).__next__()
        res: dict[str, int] = {}
        for el in node.findall("RADIO_ADD_OFFSET"):
            res[_band_name(int(el.get("band_id")))] = int(float(el.text))
        return res

    shift = next(data.iter("RADIOMETRIC_SHIFT"))
    l1b = {_band_name(int(e.get("band_id"))): int(float(e.text))
           for e in next(shift.iter("RADIANCE_OFFSET_L1B")).findall("RADIO_ADD_OFFSET")}
    l1c = {_band_name(int(e.get("band_id"))): int(float(e.text))
           for e in next(shift.iter("REFLECTANCE_OFFSET_L1C")).findall("RADIO_ADD_OFFSET")}
    eq, off, dsnu = {}, {}, {}
    for be in data.iter("BAND_EQUALIZATION"):
        b = _band_name(int(be.get("band_id") or be.findtext("BAND_ID")))
        eq[b] = (be.findtext("EQUALIZATION_FLAG") or "true").lower() == "true"
        off[b] = (be.findtext("OFFSET") or "true").lower() == "true"
        dsnu[b] = (be.findtext("DARK_SIGNAL_NON_UNIFORMITY") or "true").lower() == "true"
    return RadioParams(l1b, l1c, eq, off, dsnu)


def read_r2crco(gipp_dir: str) -> dict[str, np.ndarray]:
    """Per-band crosstalk row (OPTICAL+ELECTRICAL summed). ≈0 for S2A."""
    if _gipp_layout(gipp_dir) == "json-bands":
        return read_r2crco_json(gipp_dir)
    root = ET.parse(_find_one(gipp_dir, "R2CRCO")).getroot()
    out: dict[str, np.ndarray] = {}
    for cc in root.iter("CROSSTALK_COEFF"):
        band = _band_name(int(cc.get("band_id_k")))
        opt = _floats(cc.findtext("OPTICAL"))
        ele = _floats(cc.findtext("ELECTRICAL"))
        out[band] = opt + ele
    return out


# --- bundle ------------------------------------------------------------------------------

@dataclass
class GippSet:
    """All GIPP calibration data needed by the reverse chain, parsed from ``gipp_dir``.

    The full-reverse extras (``rswir_adf`` = SWIR shift map, ``reob2_adf`` = on-board equalization)
    are EOPF ADF json paths read **lazily** through :meth:`swir_shift` / :meth:`onboard_eq` — those
    ADFs are large (REOB2 ≈ 125 MB) and only a handful of (band, detector) pairs are ever needed.
    """

    gipp_dir: str
    equalization: dict[str, BandEq] = field(default_factory=dict)   # band → R2EQOG
    defective: dict[str, dict[int, np.ndarray]] = field(default_factory=dict)
    blind: dict[str, dict[int, np.ndarray]] = field(default_factory=dict)
    params: RadioParams | None = None
    crosstalk: dict[str, np.ndarray] = field(default_factory=dict)
    crosstalk_matrix: np.ndarray | None = None    # EOPF RCRCO dtalk[k,l], sensor.BANDS order
    rswir_adf: str | None = None
    reob2_adf: str | None = None

    def band(self, name: str) -> BandEq:
        return self.equalization[name]

    def swir_shift(self, band: str, detector: int) -> tuple[np.ndarray, np.ndarray, str] | None:
        """SWIR staggered-readout shift map for a (band, detector), or ``None`` if unavailable."""
        if self.rswir_adf is None or band.upper() not in _RSWIR_BANDS:
            return None
        return read_rswir_eopf(self.rswir_adf, band, detector)

    def onboard_eq(self, band: str, detector: int) -> dict[str, np.ndarray] | None:
        """On-board-equalization coefficients (REOB2) for a (band, detector), or ``None``."""
        if self.reob2_adf is None:
            return None
        return read_reob2_eopf(self.reob2_adf, band, detector)


def load_gipp_set(gipp_dir: str, bands: tuple[str, ...] = sensor.BANDS,
                  eqog_adf: str | None = None, rswir_adf: str | None = None,
                  reob2_adf: str | None = None, rcrco_adf: str | None = None) -> GippSet:
    """Load the full GIPP set from ``gipp_dir`` (JSON ``gipp-json`` or XML test fixtures).

    Equalization comes from ``gipp_dir`` (``ADF_REQOG`` per band). Optional ``eqog_adf`` forces
    EOPF ``data_vars`` REQOG (V&V only — not used by the production pipeline). ``rswir_adf`` /
    ``reob2_adf`` / ``rcrco_adf`` enable the full reverse chain (S8/S9/S12) from ``adf-eopf``.
    """
    gs = GippSet(gipp_dir=gipp_dir, rswir_adf=rswir_adf, reob2_adf=reob2_adf)
    for b in bands:
        if eqog_adf:
            gs.equalization[b] = read_r2eqog_eopf(eqog_adf, b)
        else:
            gs.equalization[b] = read_r2eqog_band(gipp_dir, b)
    gs.defective = read_r2depi(gipp_dir)
    gs.blind = read_blindp(gipp_dir)
    gs.params = read_r2para(gipp_dir)
    gs.crosstalk = read_r2crco(gipp_dir)
    if rcrco_adf:
        gs.crosstalk_matrix = read_rcrco_eopf(rcrco_adf)
    return gs

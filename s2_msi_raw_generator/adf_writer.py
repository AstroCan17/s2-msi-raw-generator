"""Serialize derived calibration coefficients to EOPF-CPM Auxiliary Data Files (the "cal-DB").

Option Y of the generator ⇄ ``msi-processor`` coupling: the Synthetic Raw Data Generator *derives*
realistic radiometric calibration coefficients and writes them as versioned EOPF zarr ADFs that the
downstream processor (the L1PP blocks inside ``msi-processor``) consumes **directly** as its
``nuc`` / ``dark`` / ``radiometric`` Auxiliary Data Files. Nothing here re-implements the processor;
it only produces the ADF set the processor already expects (single shared sensor-model ADF — the
``e2es-coupling-decision`` ADR).

ADF schema — matches ``msi_processor``'s ``AuxiliaryDataFile.data_ptr`` mappings (zarr **v2**):

    nuc.zarr          /gain/<band>, /offset/<band>    float32 (detector,)  PRNU correction g_d, o_d
    dark.zarr         /dark_offset/<band>             float32 scalar       per-band dark k
    radiometric.zarr  /gain/<band>, /offset/<band>    float32 scalar       DN→radiance G, O
    spectral.zarr     /esun/<band>                    float32 scalar       ESUN (toa reflectance)
    noise.zarr        /alpha/<band>, /beta/<band>     float32 scalar       σ=√(α²+β·DN)  (E2ES-side)

**Convention.** The NUC ``gain``/``offset`` follow the processor's own two-point form
(``msi_processor.computing.radiometric.core.estimate_nuc``): from a synthetic dark frame ``D`` and a
diffuser flat ``F`` (both ``(line, detector)``), ``g_d = (μ_F−μ_D)/(F̄_d−D̄_d)``,
``o_d = μ_F − g_d·F̄_d``, plus the per-band dark ``k = μ_D`` that ``apply_nuc`` subtracts. The absolute
``radiometric.gain`` is **derived from the diffuser** (``l_diff/(μ_F−μ_D)`` ≈ ``1/cal_gain``,
``offset = 0``) and is self-consistent with the NUC, so the processor's ``apply_nuc`` then
``dn_to_radiance`` recover ``A·L`` then ``L``. The coefficients are **derived** (not the truth ADF) —
the round-trip is therefore non-tautological (inverse-crime cure).

Scalars are stored as 0-d arrays (``float(...)``-able, as the processor reads them). The cal-DB is
per-band (one across-track ``(detector,)`` vector per band), matching the processor's per-band ADF.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import __version__, sensor

try:
    import zarr
except ImportError:  # pragma: no cover
    zarr = None

# The ADF file names + their operational S2 type codes (SentiWiki ADF reference). ESUN has no distinct
# operational ADF — it ships within ADF_RABCA / the L1C SOLAR_IRRADIANCE metadata — but msi-processor
# consumes it as a separate `spectral` ADF, so we emit `spectral.zarr` under an own `ADF_SPECT` label.
ADF_TYPES = {
    "nuc": "ADF_REQOG",
    "dark": "ADF_REOB2",
    "radiometric": "ADF_RABCA",
    "spectral": "ADF_SPECT",
    "noise": "ADF_RNOMO",
}


@dataclass(frozen=True)
class BandCal:
    """Per-band calibration coefficients in the ``msi-processor`` ADF convention."""

    band: str  # canonical S2 band id, e.g. "B03" / "B8A"
    nuc_gain: np.ndarray  # (n_det,) NUC correction gain g_d
    nuc_offset: np.ndarray  # (n_det,) NUC offset o_d
    dark_offset: float  # per-band dark k = μ_D
    radio_gain: float  # absolute DN→radiance gain = 1 / cal_gain
    radio_offset: float = 0.0  # absolute DN→radiance offset
    esun: float = (
        0.0  # ESUN solar irradiance (W·m⁻²·µm⁻¹), for the toa reflectance step
    )
    noise_alpha: float = 0.0  # σ = √(α² + β·DN)
    noise_beta: float = 0.0


def nuc_two_point(
    dark_frame: np.ndarray, flat_frame: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Per-detector NUC ``(gain, offset, dark_offset)`` in the processor's two-point convention.

    Reproduces ``msi_processor.computing.radiometric.core.estimate_nuc`` exactly (dark + flat →
    ``g_d = (μ_F−μ_D)/(F̄_d−D̄_d)``, ``o_d = μ_F − g_d·F̄_d``) plus the per-band dark ``k = μ_D`` that
    ``apply_nuc`` subtracts. ``dark_frame`` / ``flat_frame`` are ``(line, detector)``. Degenerate
    detectors (``F̄_d = D̄_d``) yield a non-finite gain — left as-is; the processor flags them via
    ``detect_bad_pixels``.
    """
    dark = np.asarray(dark_frame, dtype=np.float64)
    flat = np.asarray(flat_frame, dtype=np.float64)
    dark_mean = dark.mean(axis=0)  # per-detector column mean, (detector,)
    flat_mean = flat.mean(axis=0)
    mu_dark = float(dark_mean.mean())
    mu_flat = float(flat_mean.mean())
    with np.errstate(divide="ignore", invalid="ignore"):
        gain = (mu_flat - mu_dark) / (flat_mean - dark_mean)
    offset = mu_flat - gain * flat_mean
    return gain.astype(np.float32), offset.astype(np.float32), mu_dark


def _write_vector(group, name: str, values: np.ndarray) -> None:
    """Write a 1-D ``(detector,)`` float32 array under ``group/name`` (zarr v2/v3 compatible)."""
    from . import _zarrio

    _zarrio.put_array(group, name, values, dtype="float32")


def _write_scalar(group, name: str, value: float) -> None:
    """Write a 0-d float32 scalar under ``group/name`` (``float(...)``-able by the processor)."""
    from . import _zarrio

    _zarrio.put_array(group, name, np.float32(value), dtype="float32")


def _provenance(unit: str, adf_key: str, content: str, source: str) -> dict:
    """Machine-readable ADF provenance (mirrors ``l0product`` ``adf_provenance`` shape)."""
    return {
        "processor": "s2_msi_raw_generator",
        "processor_version": __version__,
        "unit": unit,
        "adf_type": ADF_TYPES[adf_key],
        "content": content,
        "source": source,
        "convention": "processor two-point NUC (estimate_nuc); radiometric gain diffuser-derived (~1/cal_gain)",
    }


def write_calibration_db(
    out_dir,
    cals: Iterable[BandCal],
    *,
    unit: str = sensor.DEFAULT_UNIT,
    source: str = "derived (CSM diffuser + dark calibration)",
    include_spectral: bool = True,
    include_noise: bool = True,
) -> list[Path]:
    """Write the EOPF zarr ADF set (``nuc`` / ``dark`` / ``radiometric`` [+ ``spectral`` + ``noise``]).

    The raw calibration *acquisitions* behind these coefficients are not ADF side-files:
    the pipeline's calibration mode packages them as downlink Synthetic L0 products
    (``S02MSIDCA`` dark, ``S02MSISCA`` sun-diffuser) — see the ICD.

    Returns the list of written ``.zarr`` paths. A ``PROVENANCE.md`` is written beside them.
    """
    if zarr is None:
        raise ImportError(
            "zarr is required to write the calibration database: `uv pip install zarr`"
        )
    from . import _zarrio

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cals = list(cals)
    written: list[Path] = []

    # nuc.zarr — per-detector NUC correction (default-mode mandatory ADF).
    nuc_path = out / "nuc.zarr"
    root = _zarrio.open_group_w(nuc_path)
    root.attrs.update(
        _provenance(unit, "nuc", "per-detector NUC gain g_d and offset o_d", source)
    )
    g_grp, o_grp = root.create_group("gain"), root.create_group("offset")
    for c in cals:
        _write_vector(g_grp, c.band, c.nuc_gain)
        _write_vector(o_grp, c.band, c.nuc_offset)
    written.append(nuc_path)

    # dark.zarr — per-band dark offset k (mandatory ADF).
    dark_path = out / "dark.zarr"
    root = _zarrio.open_group_w(dark_path)
    root.attrs.update(
        _provenance(unit, "dark", "per-band dark offset k = mean dark", source)
    )
    do_grp = root.create_group("dark_offset")
    for c in cals:
        _write_scalar(do_grp, c.band, c.dark_offset)
    written.append(dark_path)

    # radiometric.zarr — absolute DN→radiance gain/offset (TOA-unit mandatory ADF).
    rad_path = out / "radiometric.zarr"
    root = _zarrio.open_group_w(rad_path)
    root.attrs.update(
        _provenance(
            unit,
            "radiometric",
            "absolute DN->radiance gain (1/cal_gain), offset",
            source,
        )
    )
    g_grp, o_grp = root.create_group("gain"), root.create_group("offset")
    for c in cals:
        _write_scalar(g_grp, c.band, c.radio_gain)
        _write_scalar(o_grp, c.band, c.radio_offset)
    written.append(rad_path)

    # spectral.zarr — per-band ESUN (toa-unit reflectance ADF; mandatory when emit_reflectance).
    if include_spectral:
        spec_path = out / "spectral.zarr"
        root = _zarrio.open_group_w(spec_path)
        root.attrs.update(
            _provenance(
                unit,
                "spectral",
                "per-band ESUN (solar irradiance, W m-2 um-1); operationally within ADF_RABCA / L1C SOLAR_IRRADIANCE",
                "Thuillier 2003 (ATBD Annex A.3)",
            )
        )
        e_grp = root.create_group("esun")
        for c in cals:
            _write_scalar(e_grp, c.band, c.esun)
        written.append(spec_path)

    # noise.zarr — E2ES-side noise model (RNOMO); msi-processor does not read it.
    if include_noise:
        noise_path = out / "noise.zarr"
        root = _zarrio.open_group_w(noise_path)
        root.attrs.update(
            _provenance(
                unit,
                "noise",
                "noise model sigma=sqrt(alpha^2 + beta*DN); E2ES-side",
                source,
            )
        )
        a_grp, b_grp = root.create_group("alpha"), root.create_group("beta")
        for c in cals:
            _write_scalar(a_grp, c.band, c.noise_alpha)
            _write_scalar(b_grp, c.band, c.noise_beta)
        written.append(noise_path)

    _write_provenance_md(
        out / "PROVENANCE.md", unit, source, cals, include_spectral, include_noise
    )
    return written


def _write_provenance_md(
    path: Path,
    unit: str,
    source: str,
    cals: list[BandCal],
    include_spectral: bool,
    include_noise: bool,
) -> None:
    """Write a human-readable manifest beside the artifacts (like ``data/psf/PROVENANCE.md``)."""
    bands = ", ".join(c.band for c in cals)
    rows = [
        "| `nuc.zarr` | `/gain/<band>`, `/offset/<band>` | float32 (detector,) | msi-processor radiometric unit (default) |",
        "| `dark.zarr` | `/dark_offset/<band>` | float32 scalar | msi-processor radiometric unit |",
        "| `radiometric.zarr` | `/gain/<band>`, `/offset/<band>` | float32 scalar | msi-processor toa unit |",
    ]
    if include_spectral:
        rows.append(
            "| `spectral.zarr` | `/esun/<band>` | float32 scalar | msi-processor toa unit (reflectance) |"
        )
    if include_noise:
        rows.append(
            "| `noise.zarr` | `/alpha/<band>`, `/beta/<band>` | float32 scalar | E2ES-side (RNOMO); not read by msi-processor |"
        )
    text = "\n".join(
        [
            "# Calibration database (EOPF ADF set) — PROVENANCE",
            "",
            f"Generated by `s2_msi_raw_generator` v{__version__} (Sentinel-2 MSI Synthetic Raw Data Generator).",
            f"Unit: **{unit}**.  Bands: {bands}.",
            f"Source: {source}.",
            "",
            "## Artifacts (zarr v2, EOPF `AuxiliaryDataFile` convention)",
            "",
            "| file | groups | shape | consumer |",
            "|---|---|---|---|",
            *rows,
            "",
            "## Convention",
            "",
            "NUC `gain`/`offset` follow the processor's two-point form (`estimate_nuc`): from a synthetic",
            "dark frame D and diffuser flat F, `g_d = (muF-muD)/(Fbar_d-Dbar_d)`, `o_d = muF - g_d*Fbar_d`,",
            "and the per-band dark `k = muD`. Absolute `radiometric.gain` is diffuser-derived",
            "(`l_diff/(muF-muD)` ~ `1/cal_gain`, `offset = 0`) so the processor's `apply_nuc` then",
            "`dn_to_radiance` recover `A*L` then `L`. Coefficients are **derived** (not the truth ADF)",
            "— the round-trip is non-tautological (inverse-crime cure).",
            "",
        ]
    )
    path.write_text(text)

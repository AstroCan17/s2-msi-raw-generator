"""Assemble a synthetic L0 RAW EOProduct (Increment 2, ICD-IF-L0).

Writes the EOPF L0 Zarr structure (ATBD Annex A.9 / REQ-FUNC-030–036):

    measurements/d{DD}/b{BB}/band{BB}   uint16  (line, column)   — 12 det × 13 bands = 156 arrays
    quality/d{DD}/b{BB}/mask            uint8                    — 156 masks
    root attrs: stac_discovery (geometry/bbox/orbit/datetime) + other_metadata (sensor-config, datation)

Uses ``zarr`` (v2 format for EOPF/msi-processor interoperability), not the full ``eopf`` CPM. Line
timing / STAC datetime come from a real :class:`~s2_msi_raw_generator.datation.Datation`; when
``with_isp`` is set the CCSDS ISP headers + ``conditions/anc_data/...`` SAD telemetry (S15) are written.
"""

from __future__ import annotations

import numpy as np

from . import __version__, isp, sensor
from .adf import BandADF, synthesize
from .datation import Datation
from .reverse import reverse_mvp

try:
    import zarr
except ImportError:  # pragma: no cover
    zarr = None

# Frame key = (detector index 1–12, band name e.g. "B03").
FrameKey = tuple[int, str]

# Default synthetic S2A acquisition footprint + orbit (metadata realism; overridable per call).
# Modelled on a real S2A tile (T32TQQ, relative orbit R122) so the STAC geometry is plausible.
DEFAULT_FOOTPRINT: dict = {
    "bbox": [8.999, 44.637, 10.291, 45.637],
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [8.999, 44.637], [10.291, 44.637], [10.291, 45.637], [8.999, 45.637], [8.999, 44.637],
        ]],
    },
}
DEFAULT_ORBIT: dict = {"relative_orbit": 122, "absolute_orbit": 34803, "orbit_state": "descending"}


def _datastrip_id(platform: str, epoch, orbit: dict) -> str:
    """Compose an ``eopf:datastrip_id`` from the platform, acquisition epoch and absolute orbit."""
    sat = "S2A" if "2A" in platform else ("S2B" if "2B" in platform else "S2C")
    return f"{sat}_OPER_MSI_L0__DS_{epoch:%Y%m%dT%H%M%S}_A{orbit['absolute_orbit']:06d}"


def reverse_to_l0_frames(
    l1b_frames: dict[FrameKey, np.ndarray],
    *,
    seed: int = 0,
    adfs: dict[str, BandADF] | None = None,
    unit: str = sensor.DEFAULT_UNIT,
) -> dict[FrameKey, np.ndarray]:
    """Run the MVP reverse chain on each (detector, band) radiance frame → uint16 L0 DN."""
    out: dict[FrameKey, np.ndarray] = {}
    adfs = adfs or {}
    for (det, bname), radiance in l1b_frames.items():
        n_det = radiance.shape[1]
        adf = adfs.get(bname) or synthesize(sensor.band(bname, unit), n_det=n_det, seed=seed)
        rng = np.random.default_rng(seed + det * 100 + hash(bname) % 97)
        out[(det, bname)] = reverse_mvp(radiance, adf, rng)
    return out


def build_root_metadata(
    *,
    platform: str = "Sentinel-2A",
    datation: Datation | None = None,
    n_lines: int = 1,
    active_detectors: list[int],
    footprint: dict | None = None,
    orbit: dict | None = None,
) -> dict:
    """Root STAC + sensor-configuration metadata (values; REQ-FUNC-033/034/035/038)."""
    datation = datation or Datation()
    fp = footprint or DEFAULT_FOOTPRINT
    orb = {**DEFAULT_ORBIT, **(orbit or {})}
    tdi = {sensor.band_number(b): "APPLIED" for b in sensor.BANDS if b in sensor.TDI_BANDS}
    det_str = ",".join(f"{d:02d}" for d in sorted(active_detectors))
    unit = sensor.unit_from_platform(platform)
    start_iso, end_iso = datation.span_utc(n_lines)
    return {
        "stac_discovery": {
            "type": "Feature",
            "bbox": fp["bbox"],
            "geometry": fp["geometry"],
            "properties": {
                "platform": platform,
                "constellation": "sentinel-2",
                "instrument": "Multi Spectral Imager MSI",
                "eopf:type": "S2MSIL0_",
                "eopf:datastrip_id": _datastrip_id(platform, datation.epoch, orb),
                "product:type": "S2MSIL0_",
                "processing:level": "L0",
                "processing:software": {"s2_msi_raw_generator": __version__},
                "sat:relative_orbit": orb["relative_orbit"],
                "sat:absolute_orbit": orb["absolute_orbit"],
                "sat:orbit_state": orb["orbit_state"],
                "datetime": start_iso,
                "start_datetime": start_iso,
                "end_datetime": end_iso,
            },
        },
        "other_metadata": {
            "NUC_table_ID": sensor.NUC_TABLE_ID,
            "onboard_compression_flag": True,
            "onboard_equalization_flag": True,
            "sensor_configuration": {
                "acquisition_configuration": {
                    "active_detectors_list": det_str,
                    "compress_mode": True,
                    "equalization_mode": True,
                    "nuc_table_id": sensor.NUC_TABLE_ID,
                    "spectral_band_info": sensor.spectral_band_info(unit),
                    "tdi_configuration_list": tdi,
                },
                "time_stamp": {
                    "line_period": sensor.LINE_PERIOD_MS,
                    "acquisition_epoch_utc": datation.epoch_utc,
                    "acquisition_epoch_gps_s": datation.gps_epoch_s,
                    "band_time_stamp": datation.band_time_stamp(),
                },
            },
        },
        "processing_history": {
            "processor": "s2_msi_raw_generator",
            "processor_version": __version__,
            # REQ-FUNC-045 — provenance of each ADF component.
            "adf_provenance": {
                "physical_gains": "product metadata (metadata/round-trip bridge)",
                "cal_gain": "derived (noise α,β + SNR@Lref); reproduces SNR@Lref",
                "psf": "ESA SentiWiki S2{A,B,C}_PSF",
                "spectral": "SRF doc COPE-GSEG-EOPG-TN-15-0007",
                "noise": "verbatim (L1A product noise_model α,β; S2-RUT)",
                "dark": "per-pixel (operational S2A GIPP R2EQOG COEFF_D) — or DQR 440-520 LSB fallback",
                "equalization": "per-pixel relative-response (GIPP R2EQOG); stability Clerc 2026 Table 3",
                "prnu": "per-pixel (GIPP R2EQOG, BandADF.from_gipp) — or L1B-derived / seeded fallback",
                "defects": "GIPP R2DEPI saturated+blind columns",
            },
        },
    }


def write_l0_product(
    out_path: str,
    frames: dict[FrameKey, np.ndarray],
    *,
    platform: str = "Sentinel-2A",
    datation: Datation | None = None,
    datetime_iso: str | None = None,
    masks: dict[FrameKey, np.ndarray] | None = None,
    footprint: dict | None = None,
    orbit: dict | None = None,
    with_isp: bool = False,
) -> str:
    """Write the L0 RAW EOProduct Zarr to ``out_path`` and return it.

    Each frame must be uint16 in ``[0, DN_MAX]``. A quality mask is written per frame (saturated
    pixels flagged where DN ≥ DN_MAX if no explicit mask is given). The datation (``Datation``) sets
    the real GPS/OBT line timing and the STAC datetime span; ``footprint``/``orbit`` set the STAC
    geometry/orbit (S2A defaults). When ``with_isp`` is set (S15), per-band ``isp_header`` arrays and
    ``conditions/anc_data/s{APID}/isp`` SAD telemetry are written, timestamped from the datation.
    ``datetime_iso`` is a deprecated shortcut for ``Datation(epoch_utc=...)``.
    """
    if zarr is None:
        raise ImportError("zarr is required to write L0 products: `uv pip install zarr`")

    if datation is None:
        datation = Datation(epoch_utc=datetime_iso) if datetime_iso else Datation()
    detectors = sorted({det for det, _ in frames})
    n_lines = max((dn.shape[0] for dn in frames.values()), default=1)
    root = zarr.open_group(out_path, mode="w", zarr_format=2)
    root.attrs.update(build_root_metadata(
        platform=platform, datation=datation, n_lines=n_lines,
        active_detectors=detectors, footprint=footprint, orbit=orbit))

    m = root.create_group("measurements")
    q = root.create_group("quality")
    cond = root.create_group("conditions").create_group("anc_data") if with_isp else None
    line_period_s = datation.line_period_s

    for (det, bname), dn in sorted(frames.items()):
        if dn.dtype != np.uint16:
            raise TypeError(f"frame ({det},{bname}) must be uint16, got {dn.dtype}")
        bkey = sensor.zarr_band_key(bname)
        bnum = sensor.band_number(bname)
        mg = m.require_group(f"d{det:02d}").require_group(bkey)
        a = mg.create_array(f"band{bnum}", shape=dn.shape, dtype="uint16", chunks=dn.shape)
        a[:] = dn
        a.attrs["short_name"] = f"band{bnum}"

        if masks is not None and (det, bname) in masks:
            mk = masks[(det, bname)].astype(np.uint8)
        else:
            mk = (dn >= sensor.DN_MAX).astype(np.uint8)  # bit 0 = saturated
        qg = q.require_group(f"d{det:02d}").require_group(bkey)
        qa = qg.create_array("mask", shape=mk.shape, dtype="uint8", chunks=mk.shape)
        qa[:] = mk

        if with_isp:
            apid = isp.apid_for(det, sensor.BANDS.index(bname))
            t0 = datation.line_time_gps(0, bname)  # real GPS/OBT epoch of this band's first line
            hdr, plen = isp.frame_isp_headers(dn, apid, t0_seconds=t0, line_period_s=line_period_s)
            ih = mg.create_array("isp_header", shape=hdr.shape, dtype="uint8", chunks=hdr.shape)
            ih[:] = hdr
            mg.attrs["apid"] = apid
            # SAD/housekeeping telemetry for this APID stream
            sad, sad_len = isp.build_sad_packets(apid, max(dn.shape[0] // 8, 1),
                                                 t0_seconds=datation.gps_epoch_s,
                                                 period_s=line_period_s * 8)
            sg = cond.require_group(f"s{apid}")
            si = sg.create_array("isp", shape=sad.shape, dtype="uint8", chunks=sad.shape)
            si[:] = sad
            sl = sg.create_array("packet_data_length", shape=sad_len.shape, dtype="uint16",
                                 chunks=sad_len.shape)
            sl[:] = sad_len

    return out_path

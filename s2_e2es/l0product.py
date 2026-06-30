"""Assemble a synthetic L0 RAW EOProduct (Increment 2, ICD-IF-L0).

Writes the EOPF L0 Zarr structure (ATBD Annex A.9 / REQ-FUNC-030–036):

    measurements/d{DD}/b{BB}/band{BB}   uint16  (line, column)   — 12 det × 13 bands = 156 arrays
    quality/d{DD}/b{BB}/mask            uint8                    — 156 masks
    root attrs: stac_discovery + other_metadata.sensor_configuration (values)

Uses ``zarr`` (v2 format for EOPF/msi-processor interoperability), not the full ``eopf`` CPM. ISP
telemetry (`conditions/anc_data/...`, step S15) is Increment 4 and omitted here.
"""

from __future__ import annotations

import numpy as np

from . import __version__, isp, sensor
from .adf import BandADF, synthesize
from .reverse import reverse_mvp

try:
    import zarr
except ImportError:  # pragma: no cover
    zarr = None

# Frame key = (detector index 1–12, band name e.g. "B03").
FrameKey = tuple[int, str]


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
    datetime_iso: str = "2024-04-03T00:00:00Z",
    active_detectors: list[int],
) -> dict:
    """Root STAC + sensor-configuration metadata (values; REQ-FUNC-033/034/054)."""
    tdi = {sensor.band_number(b): "APPLIED" for b in sensor.BANDS if b in sensor.TDI_BANDS}
    det_str = ",".join(f"{d:02d}" for d in sorted(active_detectors))
    unit = sensor.unit_from_platform(platform)
    return {
        "stac_discovery": {
            "type": "Feature",
            "properties": {
                "platform": platform,
                "instrument": "Multi Spectral Imager MSI",
                "eopf:type": "S2MSIL0_",
                "datetime": datetime_iso,
                "start_datetime": datetime_iso,
                "end_datetime": datetime_iso,
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
                "time_stamp": {"line_period": sensor.LINE_PERIOD_MS},
            },
        },
        "processing_history": {
            "processor": "s2_e2es",
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
    datetime_iso: str = "2024-04-03T00:00:00Z",
    masks: dict[FrameKey, np.ndarray] | None = None,
    with_isp: bool = False,
) -> str:
    """Write the L0 RAW EOProduct Zarr to ``out_path`` and return it.

    Each frame must be uint16 in ``[0, DN_MAX]``. A quality mask is written per frame (saturated
    pixels flagged where DN ≥ DN_MAX if no explicit mask is given). When ``with_isp`` is set
    (Increment 4 / S15), per-band ``isp_header`` arrays and ``conditions/anc_data/s{APID}/isp``
    SAD telemetry are written too.
    """
    if zarr is None:
        raise ImportError("zarr is required to write L0 products: `uv pip install zarr`")

    detectors = sorted({det for det, _ in frames})
    root = zarr.open_group(out_path, mode="w", zarr_format=2)
    root.attrs.update(build_root_metadata(
        platform=platform, datetime_iso=datetime_iso, active_detectors=detectors))

    m = root.create_group("measurements")
    q = root.create_group("quality")
    cond = root.create_group("conditions").create_group("anc_data") if with_isp else None
    line_period_s = sensor.LINE_PERIOD_MS / 1000.0

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
            hdr, plen = isp.frame_isp_headers(dn, apid, line_period_s=line_period_s)
            ih = mg.create_array("isp_header", shape=hdr.shape, dtype="uint8", chunks=hdr.shape)
            ih[:] = hdr
            mg.attrs["apid"] = apid
            # SAD/housekeeping telemetry for this APID stream
            sad, sad_len = isp.build_sad_packets(apid, max(dn.shape[0] // 8, 1),
                                                 period_s=line_period_s * 8)
            sg = cond.require_group(f"s{apid}")
            si = sg.create_array("isp", shape=sad.shape, dtype="uint8", chunks=sad.shape)
            si[:] = sad
            sl = sg.create_array("packet_data_length", shape=sad_len.shape, dtype="uint16",
                                 chunks=sad_len.shape)
            sl[:] = sad_len

    return out_path

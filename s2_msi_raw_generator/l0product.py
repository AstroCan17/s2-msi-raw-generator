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

import zlib
from pathlib import Path

import numpy as np

from . import __version__, ccsds122, isp, quality, quality_report, sad, sensor
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
        # crc32, not hash(): the latter is salted per process (PYTHONHASHSEED) — irreproducible.
        rng = np.random.default_rng(seed + det * 100 + zlib.crc32(bname.encode()) % 97)
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
    eph_start, eph_stop = sad.orbit_ephemeris(datation, n_lines)
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
            "orbit_ephemeris_start": eph_start,
            "orbit_ephemeris_stop": eph_stop,
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
    emit_qc: bool = True,
    with_isp: bool = False,
    isp_max_payload: int = isp.DEFAULT_MAX_PAYLOAD,
    store_decoded: bool = True,
) -> str:
    """Write the L0 RAW EOProduct Zarr to ``out_path`` and return it.

    Each frame must be uint16 in ``[0, DN_MAX]``. A quality mask is written per frame (saturated
    pixels flagged where DN ≥ DN_MAX if no explicit mask is given). The datation (``Datation``) sets
    the real GPS/OBT line timing and the STAC datetime span; ``footprint``/``orbit`` set the STAC
    geometry/orbit (S2A defaults). ``datetime_iso`` is a deprecated shortcut for
    ``Datation(epoch_utc=...)``.

    When ``with_isp`` is set (S15) the band's image data is **CCSDS-122 lossless compressed**
    (:mod:`~s2_msi_raw_generator.ccsds122`) and carried as real CCSDS space packets
    (:func:`~s2_msi_raw_generator.isp.packetize_stream`; codec segments = 8 image lines →
    line-accurate CUC datation; ``SEQ_FIRST/CONT/LAST`` grouping) under
    ``measurements/d{DD}/b{BB}/{isp, isp_offsets, packet_data_length}``; SAD telemetry goes to
    ``conditions/anc_data/s{APID}/isp``. Achieved per-band compression ratios replace the
    static ``compression_rate`` metadata. With ``store_decoded=False`` the decoded ``band{BB}``
    arrays are omitted — the product then stores ISPs only, mirroring the real S2 L0
    (SentiWiki: L0 = compressed ISPs; ground L1A decompresses via :func:`read_l0_isp_dn`).
    """
    if zarr is None:
        raise ImportError("zarr is required to write L0 products: `uv pip install zarr`")
    from . import _zarrio

    if not store_decoded and not with_isp:
        raise ValueError("store_decoded=False requires with_isp=True (nothing would be stored)")
    if datation is None:
        datation = Datation(epoch_utc=datetime_iso) if datetime_iso else Datation()
    detectors = sorted({det for det, _ in frames})
    n_lines = max((dn.shape[0] for dn in frames.values()), default=1)
    root = _zarrio.open_group_w(out_path)
    meta = build_root_metadata(
        platform=platform, datation=datation, n_lines=n_lines,
        active_detectors=detectors, footprint=footprint, orbit=orbit)

    m = root.create_group("measurements")
    q = root.create_group("quality")
    cond = root.create_group("conditions").create_group("anc_data") if with_isp else None
    line_period_s = datation.line_period_s
    achieved_ratio: dict[str, float] = {}

    for (det, bname), dn in sorted(frames.items()):
        if dn.dtype != np.uint16:
            raise TypeError(f"frame ({det},{bname}) must be uint16, got {dn.dtype}")
        bkey = sensor.zarr_band_key(bname)
        bnum = sensor.band_number(bname)
        mg = m.require_group(f"d{det:02d}").require_group(bkey)
        if store_decoded:
            a = _zarrio.put_array(mg, f"band{bnum}", dn, dtype="uint16")
            a.attrs["short_name"] = f"band{bnum}"

        # Canonical L0 mask = S2 MSK_QUALIT (8 bit-planes), seeded from DN (saturation/no-data/lost)
        # OR'd with any injected-defect qa (reverse.s10 bit0=dead/bit1=hot → DEFECTIVE/SATURATED).
        qflags = quality.l0_flags(dn)
        if masks is not None and (det, bname) in masks:
            qflags = qflags | quality.from_s10_qa(masks[(det, bname)])
        mk = quality.to_msk_qualit(qflags)
        qg = q.require_group(f"d{det:02d}").require_group(bkey)
        _zarrio.put_array(qg, "mask", mk, dtype="uint8")

        if with_isp:
            apid = isp.apid_for(det, sensor.BANDS.index(bname))
            t0 = datation.line_time_gps(0, bname)  # real GPS/OBT epoch of this band's first line
            depth = 16 if int(dn.max(initial=0)) > sensor.DN_MAX else 12
            payload, stats = ccsds122.compress_frame(dn, pixel_bit_depth=depth)
            bounds = ccsds122.segment_byte_bounds(payload)
            # one codec segment = one 8-image-line block row → its CUC time is that row's first line
            seg_times = t0 + np.arange(len(bounds)) * (8 * line_period_s)
            stream, offsets, plens = isp.packetize_stream(
                payload, apid, segment_bounds=bounds, segment_times_gps=seg_times,
                max_payload=isp_max_payload)
            _zarrio.put_array(mg, "isp", stream, dtype="uint8")
            _zarrio.put_array(mg, "isp_offsets", offsets, dtype="uint64")
            _zarrio.put_array(mg, "packet_data_length", plens, dtype="uint32")
            mg.attrs["apid"] = apid
            mg.attrs["n_packets"] = int(offsets.size)
            mg.attrs["n_segments"] = int(stats.n_segments)
            mg.attrs["max_payload_octets"] = int(isp_max_payload)
            mg.attrs["compression"] = {
                "scheme": "CCSDS 122.0-B lossless subset (ICD-IF-C122)",
                "pixel_bit_depth": stats.pixel_bit_depth,
                "raw_bytes": stats.raw_bytes,
                "compressed_bytes": stats.compressed_bytes,
                "ratio": round(stats.ratio, 4),
            }
            achieved_ratio[bname] = max(achieved_ratio.get(bname, 0.0), round(stats.ratio, 4))
            # SAD telemetry for this APID: real AOCS quaternion + orbit ephemeris + thermal (not zeros)
            n_sad = max(dn.shape[0] // 8, 1)
            sad_times = datation.gps_epoch_s + np.arange(n_sad) * (line_period_s * 8)
            sad_arr, sad_len = sad.pack_sad_isp(sad.synth_orbit_attitude(sad_times), apid)
            sg = cond.require_group(f"s{apid}")
            _zarrio.put_array(sg, "isp", sad_arr, dtype="uint8")
            _zarrio.put_array(sg, "packet_data_length", sad_len, dtype="uint16")

    # Achieved (real) compression ratios replace the static datasheet rates (REQ-FUNC-092).
    if achieved_ratio:
        info = meta["other_metadata"]["sensor_configuration"]["acquisition_configuration"]
        info["compression_scheme"] = "CCSDS 122.0-B lossless subset"
        sbi = info["spectral_band_info"]           # keyed by band number ("03", "8A", …)
        for bname, ratio in achieved_ratio.items():
            sbi[sensor.band_number(bname)]["compression_rate"] = ratio
    root.attrs.update(meta)

    # EOPF EOQC-style per-product quality report, embedded in the quality group (REQ-FUNC-041).
    if emit_qc:
        q.attrs["qc"] = quality_report.build_qc_report(
            meta, product_name=Path(out_path).name, has_measurements=bool(frames))

    return out_path


def read_l0_isp_dn(path: str, det: int, bname: str) -> np.ndarray:
    """Ground decompression: canonical L0 ISP stream → the exact uint16 DN frame.

    The real-chain L1A-side operation (SentiWiki: decompression happens at L1A): read
    ``measurements/d{DD}/b{BB}/isp``, reassemble the packet groups
    (:func:`~s2_msi_raw_generator.isp.reassemble_segments` — seq_flags + continuity enforced),
    join them back into the CCSDS-122 stream and decode it bit-exactly.
    """
    if zarr is None:
        raise ImportError("zarr is required to read L0 products: `uv pip install zarr`")
    g = zarr.open_group(str(path), mode="r")
    mg = g[f"measurements/d{det:02d}/{sensor.zarr_band_key(bname)}"]
    stream = np.asarray(mg["isp"])
    payload = b"".join(isp.reassemble_segments(stream))
    return ccsds122.decompress_frame(payload)


def frames_to_strip(frames: dict[FrameKey, np.ndarray]) -> dict[str, np.ndarray]:
    """Reduce the 156-array ``{(det, band): frame}`` to one representative ``(line, detector)`` per band."""
    by_band: dict[str, np.ndarray] = {}
    for (_det, bname), arr in sorted(frames.items()):
        by_band.setdefault(bname, np.asarray(arr))   # first (lowest-index) detector per band
    return by_band


def write_l0_opencontainer(
    out_path: str,
    band_frames: dict[str, np.ndarray],
    *,
    masks: dict[str, np.ndarray] | None = None,
    datation: Datation | None = None,
    platform: str = "Sentinel-2A",
    footprint: dict | None = None,
    orbit: dict | None = None,
    emit_qc: bool = True,
) -> str:
    """Write the **open-container** L0 that ``msi-processor``'s ``l0_decode`` ingests (REQ-FUNC-042).

    Layout (the *decoded* form the processor reads directly, distinct from the canonical 156-array
    product): ``measurements/detector/<BAND>`` uint16 ``(line, detector)``, ``quality/l0_flags/<BAND>``
    uint16 (``QAFlag`` seed), ``conditions/{time,orbit,attitude}`` per-line telemetry, + shared root
    metadata. The hard invariant for the downstream ``nuc`` ADF: ``nuc.gain[band]`` length must equal
    ``measurements/detector/<band>``'s detector-axis width — so build the cal-DB at the same ``n_det``.
    """
    if zarr is None:
        raise ImportError("zarr is required to write L0 products: `uv pip install zarr`")
    from . import _zarrio
    if datation is None:
        datation = Datation()
    n_lines = max((np.asarray(f).shape[0] for f in band_frames.values()), default=1)
    root = _zarrio.open_group_w(out_path)
    meta = build_root_metadata(platform=platform, datation=datation, n_lines=n_lines,
                               active_detectors=[1], footprint=footprint, orbit=orbit)
    root.attrs.update(meta)

    det = root.create_group("measurements").create_group("detector")
    lf = root.create_group("quality").create_group("l0_flags")
    for bname, frame in sorted(band_frames.items()):
        dn = np.asarray(frame, dtype=np.uint16)
        _zarrio.put_array(det, bname, dn, dtype="uint16")
        qflags = quality.l0_flags(dn)
        if masks and bname in masks:
            qflags = qflags | quality.from_s10_qa(masks[bname])
        _zarrio.put_array(lf, bname, qflags, dtype="uint16")

    # per-line conditions (SAD-derived): line_time + orbit position/velocity + attitude quaternion
    line_times = datation.gps_epoch_s + np.arange(n_lines) * datation.line_period_s
    conds = sad.aocs_to_conditions(sad.synth_orbit_attitude(line_times))
    cg = root.create_group("conditions")
    for path, arr in conds.items():
        grp_name, _, arr_name = path.partition("/")
        _zarrio.put_array(cg.require_group(grp_name), arr_name, arr, dtype="float64")

    if emit_qc:
        root["quality"].attrs["qc"] = quality_report.build_qc_report(
            meta, product_name=Path(out_path).name, has_measurements=bool(band_frames))
    return out_path

# Changelog

All notable changes to the Sentinel-2 MSI reverse E2ES (`s2_msi_raw_generator`).

## [Unreleased]

### Added
- **Quality-flag taxonomy** (`s2_msi_raw_generator/quality.py`) — L0 quality expressed as msi-processor
  `QAFlag`-compatible seeds (NO_DATA/LOST_PACKET/SATURATED/DEFECTIVE, same bit values for monotone-OR
  interop); the canonical L0 mask is now the Sentinel-2 `MSK_QUALIT` 8-bit-plane layout
  (`l0_flags`/`to_msk_qualit`/`from_s10_qa`). (REQ-FUNC-040)
- **EOQC quality report** (`s2_msi_raw_generator/quality_report.py`) — EOPF EOQC-style per-product report
  (overall OK/KO + per-check list: STAC content/geometry, Sensing_Time, ISO_Time, Datation_Sync,
  Time_Correlation, orbit bounds, structure), embedded in the L0 `quality` group and writable as standalone
  JSON. ECSS-Q-ST-20C. (REQ-FUNC-041)
- **Real line datation** (`s2_msi_raw_generator/datation.py`) — `Datation` (ADF_DATAT model) stamps each ISP
  line with a real GPS/OBT time from an acquisition epoch (was `t0=0`); `isp.parse_cuc_time`; per-band
  `band_time_stamp` + acquisition epoch in the L0 metadata. (REQ-FUNC-035)
- **L0 STAC geometry & orbit metadata** — `build_root_metadata` now writes the footprint (`bbox` + closed
  `geometry`), `sat:relative_orbit`/`sat:absolute_orbit`/`sat:orbit_state`, `constellation`, `product:type`,
  `processing:*`, `eopf:datastrip_id`, and a **real datetime span** (start/end from datation) with S2A
  footprint/orbit defaults (overridable via `footprint`/`orbit`). Fixes the dangling REQ-FUNC-054 ref. (REQ-FUNC-038)
- **ESUN spectral ADF** (`spectral.zarr`) — the cal-DB writer now emits per-band ESUN (extraterrestrial solar
  irradiance, Thuillier 2003; S2A/S2B — ATBD §A.3) as `/esun/<band>` float32 scalars, the exact schema the
  `msi-processor` `toa` unit consumes for TOA reflectance. `sensor.ESUN` / `sensor.esun()`,
  `adf_writer.write_calibration_db(..., include_spectral=True)`, `scripts/build_cal_db.py`. (REQ-FUNC-039)
- **Calibration sub-set** (`s2_msi_raw_generator/calibration.py`) — the S2 two-reference radiometric calibration:
  synthetic CSM sun-diffuser + dark acquisitions → derive dark `D`, relative response `g`, absolute
  coefficient `A` (public L1 ATBD §4.1.1.2.2). A processor uses the *derived* coefficients, not the
  truth — the inverse-crime cure. Verified on the GIPP (dark <0.05 DN, `g` corr >0.99, `A≈cal_gain`).
- **Real operational GIPP reader** (`s2_msi_raw_generator/gipp.py`) — original `xml.etree` parser of the S2A
  GIPP: R2EQOG (per-pixel dark `COEFF_D` + cubic/bilinear relative-response gains), R2DEPI, BLINDP,
  R2PARA, R2CRCO. `BandADF.from_gipp()` builds per-pixel dark + PRNU ADFs.
- **Original ATBD forward + round-trip V&V** (`s2_msi_raw_generator/forward_radiometric_atbd.py`) — forward
  radiometric correction and its exact inverse from the public L1 ATBD; `scripts/roundtrip_real_l1a.py`
  validates forward∘reverse to ~1e-14 RMSE on a **L1A** with the GIPP.
- L1A raw reader (`io.read_l1a_raw`), image export (`scripts/save_images.py`), demos
  (`demo_calibration.py`), `LICENSE` (Apache-2.0), this changelog.

### Changed
- Radiometric model adopts the official L1 ATBD raw equation `X = A·G·L + D` in true 12-bit DN.
- Per-band noise model uses the product `noise_model` (α, β; S2-RUT `σ=√(α²+β·DN)`).
- Dark/PRNU now per-pixel from the GIPP (was DQR-summary / seeded).
- L1C-entry + geometry-reverse module **cancelled** (not applicable to an L1A/L1B entry).

## [0.3.0] — Increments 0–4

- Full S1–S15 reverse chain (radiance→DN, PSF re-blur, PRNU, SWIR re-arrangement (reverse), defects, dark, onboard
  equalization, noise, 12-bit quantize, CCSDS ISP packets).
- L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config).
- S2 PSF matrices (SentiWiki) + SRF spectral characterisation.
- Sensor model with per-band gains/TDI/line-period from EOPF products.
- GitLab CI (unit tests), ATBD + Annex A datasheet.

# Changelog

All notable changes to the Sentinel-2 MSI reverse E2ES (`s2_e2es`).

## [Unreleased]

### Added
- **Calibration sub-set** (`s2_e2es/calibration.py`) — the S2 two-reference radiometric calibration:
  synthetic CSM sun-diffuser + dark acquisitions → derive dark `D`, relative response `g`, absolute
  coefficient `A` (public L1 ATBD §4.1.1.2.2). A processor uses the *derived* coefficients, not the
  truth — the inverse-crime cure. Verified on the GIPP (dark <0.05 DN, `g` corr >0.99, `A≈cal_gain`).
- **Real operational GIPP reader** (`s2_e2es/gipp.py`) — original `xml.etree` parser of the S2A
  GIPP: R2EQOG (per-pixel dark `COEFF_D` + cubic/bilinear relative-response gains), R2DEPI, BLINDP,
  R2PARA, R2CRCO. `BandADF.from_gipp()` builds per-pixel dark + PRNU ADFs.
- **Original ATBD forward + round-trip V&V** (`s2_e2es/forward_radiometric_atbd.py`) — forward
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

- Full S1–S15 reverse chain (radiance→DN, PSF re-blur, PRNU, SWIR re-stagger, defects, dark, onboard
  equalization, noise, 12-bit quantize, CCSDS ISP packets).
- L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config).
- S2 PSF matrices (SentiWiki) + SRF spectral characterisation.
- Sensor model with per-band gains/TDI/line-period from EOPF products.
- GitLab CI (unit tests), ATBD + Annex A datasheet.

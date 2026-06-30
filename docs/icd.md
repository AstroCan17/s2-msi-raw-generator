<!--
  Copyright 2026 Can Deniz Kaya

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

# Interface control document

**Project:** Sentinel-2 MSI Reverse E2ES (`s2_e2es`) · **DRD:** ECSS-E-ST-40C Rev.1, Annex E (ICD).
Companion to the SRS (`docs/srs.md`, interface requirements REQ-IF-001/002/003) and the ATBD
(`docs/atbd/atbd.md`).

## Introduction

This document specifies the external and internal interfaces of the reverse E2ES: the products it
consumes (Sentinel-2 L1A/L1B EOPF Zarr), the auxiliary calibration data it reads (the operational
GIPP), and the synthetic **L0 RAW** product it produces (the normative interface **ICD-IF-L0**). All
data interfaces are file-based (Zarr / XML); there is no network, hardware, or database interface.

## Software overview

`s2_e2es` is a pure-Python library (runtime deps `numpy`, plus `zarr` for product I/O). It reads a real
L1A/L1B granule, runs the radiometric reverse chain (ATBD §5, S1–S15), and assembles a 156-array L0 RAW
EOProduct. Auxiliary inputs (PSF matrices, SRF, operational GIPP) areS2 data.

## Interface design

### Internal interfaces (module contracts)

| Module | Key entry points | Contract |
|---|---|---|
| `sensor` | `band(name, unit)`, `all_bands()`, `spectral_band_info(unit)`, `unit_from_platform()`, constants | Pure data/model; leaf module — per-band gains/TDI/SRF/noise constants. |
| `gipp` | `load_gipp_set(dir)` → `GippSet`; `read_r2eqog_band`, `read_r2depi`, `read_blindp`, `read_r2para`, `read_r2crco` | Parses  S2A GIPP XML → per-pixel arrays (`DetectorEq`, `BandEq`, `RadioParams`). |
| `adf` | `BandADF` (`from_gipp`, `from_product`, `synthesize`), `real_psf_kernel`, `noise_coeffs` | Builds the per-band ADF set (PSF, noise α,β, per-pixel dark/PRNU). |
| `reverse` | `s1..s14` step functions, `reverse_mvp`, `reverse_full`, `reverse_radiometric`/`forward_radiometric` | NumPy reverse chain on `(lines, detector_columns)` arrays. |
| `forward_radiometric_atbd` | `forward_correct`, `reverse_impress`, `forward_equalize`/`inverse_equalize`, `column_fpn` | Public-ATBD forward model + exact inverse (round-trip bridge). |
| `calibration` | `calibrate`, `estimated_adf`, `synth_dark_acquisition`, `synth_diffuser_acquisition` | Two-reference calibration sub-set → derived coefficients. |
| `io` | `read_l1b_band`, `read_l1a_raw`, `read_platform` | Lightweight Zarr reader (no full EOPF CPM). |
| `isp` | `frame_isp_headers`, `build_sad_packets`, `build_primary_header`, `apid_for` | CCSDS ISP / SAD telemetry (S15). |
| `l0product` | `reverse_to_l0_frames`, `build_root_metadata`, `write_l0_product` | Top integrator → writes the ICD-IF-L0 product. |

Dependency direction: `sensor` (leaf) → `adf`/`gipp` → `reverse`/`forward_radiometric_atbd`/`calibration`
→ `l0product` (integrator). `io`, `isp` are leaves.

### External interfaces

- **IF-IN-L1B** — Sentinel-2 **L1B** radiance, EOPF Zarr (`.zarr` dir or `.zarr.zip`). Path
  `measurements/d{DD}/b{xx}/img`, `float32` radiance, dims `(alt, act)`. Read by `io.read_l1b_band`.
- **IF-IN-L1A** — Sentinel-2 **L1A** raw counts, EOPF Zarr. Path `measurements/DD{nn}/B{xx}/l1a_raw_image`,
  `float64` DN (offset $\approx 48$, saturation sentinel 32768). Read by `io.read_l1a_raw`.
- **IF-IN-GIPP** — operational S2A GIPP, directory of `S2A_OPER_GIP_<TYPE>_*.xml`
  (R2EQOG ×13, R2DEPI, BLINDP, R2PARA, R2CRCO). Read by `gipp.load_gipp_set`.
- **IF-IN-ADF** — packaged PSF matrices (`s2_e2es/data/psf/{S2A,S2B,S2C}/*.csv`, 33×33 oversampled).
- **IF-OUT-L0** — synthetic **L0 RAW** EOProduct (Zarr v2) — see ICD-IF-L0 below.
- **IF-MMI** — man-machine: command-line scripts (`scripts/*.py`); stdout reports.

## Interface requirements

| ECSS category | Provision |
|---|---|
| SW-to-SW | EOPF Zarr in (L1A/L1B) and out (L0 RAW), zarr v2 for processor interoperability; GIPP XML in. Realizes **REQ-IF-001**, **REQ-IF-002**, **REQ-IF-003**. |
| SW-to-HW | Not applicable — pure software, no hardware interface. |
| Man-machine | CLI scripts (`roundtrip_real_l1a.py`, `demo_calibration.py`, `save_images.py`, `demo_*`); plain-text stdout. |
| Database | Not applicable — file-based products only. |
| Error behaviour | Unknown band/unit → `KeyError`; frame not `uint16`/out-of-range → `TypeError`; missing GIPP file → `FileNotFoundError`. |

### ICD-IF-L0 — L0 RAW output data items (normative)

Produced by `l0product.write_l0_product` (Zarr **v2**; `zarr_format=2` for EOPF/processor interoperability).
Band-key map `B03→b03`, `B8A→b8a`; band-number `B03→"03"`, `B8A→"8A"`; detectors `01`–`12`.

| Path | Type | Dimension | Range / value | Source |
|---|---|---|---|---|
| `measurements/d{DD}/b{BB}/band{N}` | uint16 | (line, column); chunks = full | `[0, 4095]`; attr `short_name="band{N}"` | reverse chain (REQ-FUNC-031) |
| `measurements/d{DD}/b{BB}/isp_header` *(with_isp)* | uint8 | (n_lines, 12) | CCSDS primary+CUC; group attr `apid` | `isp.frame_isp_headers` (S15) |
| `quality/d{DD}/b{BB}/mask` | uint8 | = band shape | bit0 saturated ($\mathrm{DN}\ge 4095$), bit1 hot, dead cols | reverse / defects (REQ-FUNC-032) |
| `conditions/anc_data/s{APID}/isp` *(with_isp)* | uint8 | (n_packets, hdr+payload) | CCSDS SAD/housekeeping | `isp.build_sad_packets` |
| `conditions/anc_data/s{APID}/packet_data_length` *(with_isp)* | uint16 | (n_packets,) | octet count | `isp.build_sad_packets` |

A full product = **12 detectors × 13 bands = 156** `band{N}` arrays + 156 `mask` arrays.

**Root attributes** (`build_root_metadata`):

| Key | Content | Req |
|---|---|---|
| `stac_discovery` | `type="Feature"`, `properties{platform, instrument="Multi Spectral Imager MSI", eopf:type="S2MSIL0_", datetime, start_datetime, end_datetime}` | REQ-FUNC-033 |
| `other_metadata.NUC_table_ID` / `onboard_compression_flag` / `onboard_equalization_flag` | `3` / `true` / `true` | REQ-FUNC-034 |
| `other_metadata.sensor_configuration.acquisition_configuration` | `active_detectors_list` (zero-padded sorted), `compress_mode`, `equalization_mode`, `nuc_table_id`, `spectral_band_info` (per band: `compression_rate`, `integration_time{unit:ms,value}`, `physical_gains`, `central_wavelength{nm}`, `bandwidth{nm}`, `equivalent_wavelength{nm}` — per-unit SRF), `tdi_configuration_list={"03":"APPLIED","04":"APPLIED","11":"APPLIED","12":"APPLIED"}` | REQ-FUNC-034 |
| `other_metadata.sensor_configuration.time_stamp.line_period` | `1.5658736` (ms) | REQ-FUNC-034 |
| `processing_history` | `processor="s2_e2es"`, `processor_version`, `adf_provenance{physical_gains, cal_gain, psf, spectral, noise, dark, equalization, prnu, defects}` | REQ-FUNC-045 |

`unit` (S2A/S2B/S2C) is derived from `platform` via `sensor.unit_from_platform`; APIDs from
`isp.apid_for(detector, band_index)` (11-bit, base 1024).

## Validation requirements
The output structure is verified by `tests/test_l0product.py` (156-array contract, dtypes, root metadata,
`eopf:type`, `tdi_configuration_list`, `physical_gains`, `line_period`, `adf_provenance`) and
`tests/test_integration.py` (end-to-end product incl. ISP + quality masks). Inputs are exercised on real
ESA L1A/L1B and the GIPP.

## Traceability
REQ-IF-001 → IF-IN-L1A/L1B; REQ-IF-002 → ICD-IF-L0; REQ-IF-003 → IF-IN-GIPP. Full matrix in
`docs/sdd/traceability.md`.

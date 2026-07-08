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

# Software Requirements Specification (SRS)

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1 (SRS).
System-level context: [SSS](sss.md); the interface requirements below are single-sourced here and
collected in the [IRD](ird.md). Verification methods: **T** test · **A** analysis · **I**
inspection · **R** review.

## 1. Introduction

### 1.1 Purpose
Specify the requirements for the **reverse radiometric ladder** of the Sentinel-2 MSI. The software takes a
real Sentinel-2B **L1B** product and runs it backwards through the **exact inverse of the operational
L0→L1B radiometric chain** (invert offset, relative-response/PRNU, dark, un-bin, SWIR re-stage, defective,
crosstalk, on-board equalization) to reconstruct its **L1A → L0plus → L0**. MTF-deconvolution is **OFF**,
so PSF and noise are **not** re-applied. The objective is reconstructing the real **L0** (focal-plane DN,
12 detectors × 13 bands), validated against the real ESA L0 `img` (10/20 m bands ≤ ~4 DN).

### 1.2 Scope
Radiometric-only reverse chain (ATBD §5), **L1B** entry in per-detector sensor geometry, inverting the
operational L0→L1B radiometric corrections to reconstruct L0. Geometry inversion (de-orthorectification /
L1C entry) is **cancelled** — not applicable to an L1A/L1B entry (Issue #17). All instrument data is
S2-sourced (real operational GIPP, SRF); nothing is fitted or synthetic in the realized path. Because
MTF-deconvolution is off, the S6 PSF re-blur and S13 noise-addition steps are **dropped** — PSF and noise
are not re-applied.

### 1.3 Applicable & reference documents
| | |
|---|---|
| AD 1 | ECSS-E-ST-40C Rev.1 — Space engineering · Software |
| AD 2 | ECSS-Q-ST-80C — Software product assurance |
| RD 1 | `docs/atbd/atbd.md` — Algorithm Theoretical Basis Document (issued v1.0) |
| RD 2 | Sentinel-2 L1 ATBD (S2-PDGS-MPC-ATBD-L1) — forward radiometric model §4.1.1 |
| RD 3 | Sentinel-2 SRF doc COPE-GSEG-EOPG-TN-15-0007 v4.0 |
| RD 4 | Sentinel-2 operational GIPP (R2EQOG/R2DEPI/BLINDP/R2PARA/R2CRCO) |

### 1.4 Requirement convention
IDs are stable: **REQ-FUNC-NNN** (functional), **REQ-PERF-NNN** (performance), **REQ-IF-NNN** (interface),
**REQ-QUAL-NNN** (quality / non-functional). IDs already anchored in code/tests are preserved. Status:
**realized** (implemented + tested) or **deferred** (specified, not yet implemented).

## 2. Mission context
The forward `msi-processor` applies the operational radiometric corrections that turn L0 focal-plane DN
into an L1B product. This software runs that chain **backwards**: it inverts those same corrections on a
real Sentinel-2B L1B to reconstruct the real **L0** (via L1A → L0plus). Success is measured by agreement
of the reconstructed L0 with the real ESA L0 `img` (10/20 m bands ≤ ~4 DN) — a direct, deterministic
comparison against the operational archive product.

## 3. Functional requirements (REQ-FUNC)

### 3.1 Input handling
- **REQ-FUNC-001 — Accept L1A/L1B inputs.** *The software shall accept Sentinel-2 L1A and L1B products in
  EOPF Zarr format.* Rationale: the entry levels (RD 1 §1.1). **V: T** (`io.read_l1b_band`/`read_l1a_raw`). realized
- **REQ-FUNC-003 — Per-unit platform support.** *The software shall select per-unit (S2A/S2B/S2C)
  parameters from the product platform.* **V: T** (`sensor.unit_from_platform`, `test_real_data`). realized
- **REQ-FUNC-005 — Reject unsupported inputs.** *The software shall raise a descriptive error for unknown
  bands/units.* **V: T** (`sensor.band` KeyError). realized

### 3.2 Radiometric reverse chain (invert each operational L0→L1B correction)
Each requirement below **inverts** one step of the operational L0→L1B radiometric chain to reconstruct L0
focal-plane DN. With MTF-deconvolution off, the S6 PSF re-blur (REQ-FUNC-014) and S13 noise-addition
(REQ-FUNC-021) steps are retired — PSF and noise are not re-applied (see stubs below).
- **REQ-FUNC-010 — Invert absolute-calibration gain/offset (S1).** *The software shall invert the L1 ATBD
  raw radiometric model $X = A \cdot G \cdot L + D$ in the DN domain — recovering equalized signal DN from
  L1B counts via the per-band gain/offset inversion ($A$ = `Band.cal_gain`).* **V: T**
  (`reverse.s1_radiance_to_dn`, `test_real_data`). realized
- **REQ-FUNC-014 — PSF re-blur (S6).** **Cancelled** (MTF-deconvolution is off in the reverse ladder, so
  optical blur is not re-applied). *Retired step — no forward PSF convolution in the reconstruction path.*
- **REQ-FUNC-015 — Invert relative response / PRNU (S7).** *The software shall invert the per-pixel
  relative response using the operational GIPP R2EQOG (cubic VNIR / bilinear SWIR).* **V: T**
  (`forward_radiometric_atbd.inverse_equalize`, `adf.from_gipp`, `test_roundtrip_atbd`). realized
- **REQ-FUNC-019 — Invert dark signal (S11).** *The software shall restore the per-pixel dark signal
  (GIPP R2EQOG COEFF_D; DQR fallback) removed by the forward chain.* **V: T** (`reverse.s11_reapply_dark`,
  `test_gipp`). realized
- **REQ-FUNC-020 — Reverse onboard equalization (S12).** *The software shall reverse the onboard
  equalization gain/offset.* **V: T** (`reverse.s12_reapply_onboard_eq`). realized
- **REQ-FUNC-021 — Add sensor noise (S13).** **Cancelled** (MTF-deconvolution is off in the reverse
  ladder, so noise is not re-applied — the real L1B noise is preserved). *Retired step — no noise model
  applied in the reconstruction path.*
- **REQ-FUNC-022 — Quantize to 12-bit (S14).** *The software shall clip/round to `uint16` in `[0, 4095]`.*
  **V: T** (`reverse.s14_quantize`, inline `np.clip`/`np.rint`→`uint16`). realized
- **REQ-FUNC-013 — Reverse 60 m binning (S5).** *…un-bin B01/B09/B10 to detector resolution.* **V: T**
  (`reverse.s5_unbin`). realized
- **REQ-FUNC-016 — Restore SWIR arrangement (S8).** *…reverse the SWIR re-arrangement of the B10/B11/B12 readout.* **V: T**
  (`reverse.s8_restage_swir`). realized
- **REQ-FUNC-017 — Re-apply crosstalk (S9).** *…apply inter-band crosstalk (GIPP `R2CRCO` $\approx 0$ for S2A).*
  **V: T** (`reverse.s9_apply_crosstalk`). realized
- **REQ-FUNC-018 — Re-insert blind/defective pixels (S10).** *…from GIPP R2DEPI/BLINDP.* **V: T**
  (`reverse.s10_inject_defects`, `test_inc3_steps`). realized
- **REQ-FUNC-012 — Remove radiometric offset (S4).** *…subtract the −100 L1B offset (GIPP R2PARA).*
  **V: T** (`reverse.s4_undo_radiometric_offset`). realized
- **REQ-FUNC-011 — Reverse scene framing (S3).** *…undo framing/round-clamp.* **V: T**
  (`reverse.s3_undo_framing`). realized

### 3.3 Output product
- **REQ-FUNC-030 — L0 RAW EOProduct (Zarr).** *The software shall write a L0 RAW product in the EOPF L0
  Zarr structure.* **V: T** (`l0product.write_l0_product`, `test_l0product`). realized
- **REQ-FUNC-031 — 156 measurement arrays.** *…`measurements/d{DD}/b{BB}/band{N}` uint16 in `[0,4095]`,
  12 det × 13 bands.* **V: T** (`test_l0product::test_full_156_array_contract`). realized
- **REQ-FUNC-032 — 156 quality masks.** *…`quality/d{DD}/b{BB}/mask` uint8.* **V: T** (`test_l0product`). realized
- **REQ-FUNC-040 — Quality-flag taxonomy.** *The software shall express L0 quality as msi-processor
  `QAFlag`-compatible seeds (NO_DATA/LOST_PACKET/SATURATED/DEFECTIVE) and write the canonical L0 mask in the
  Sentinel-2 `MSK_QUALIT` 8-bit-plane layout.* **V: T** (`quality`, `test_quality`, `test_integration`). realized
- **REQ-FUNC-041 — EOQC quality report.** *The software shall emit an EOPF EOQC-style per-product quality
  report (overall OK/KO + per-check list; ECSS-Q-ST-20C) embedded in the L0 `quality` group and available as
  standalone JSON.* **V: T** (`quality_report`, `test_quality_report`). realized
- **REQ-FUNC-033 — STAC discovery metadata.** *…platform, instrument, eopf:type, datetime.* **V: T**
  (`l0product.build_root_metadata`). realized
- **REQ-FUNC-034 — Sensor-configuration metadata.** *…spectral_band_info, tdi_configuration_list,
  line_period, per-unit SRF values.* **V: T** (`test_l0product`, `test_integration`). realized
- **REQ-FUNC-035 — Real line datation.** *The software shall stamp each ISP line with a real GPS/OBT time
  from an acquisition epoch (`datation.Datation`, ADF_DATAT model), and record per-band `band_time_stamp`
  + the acquisition epoch in the L0 metadata.* **V: T** (`datation`, `test_datation`, `test_isp`). realized
- **REQ-FUNC-038 — STAC geometry & orbit metadata.** *The software shall write the STAC footprint
  (`bbox` + closed `geometry` polygon), `sat:relative_orbit`/`sat:absolute_orbit`/`sat:orbit_state`,
  `eopf:datastrip_id`, and a real acquisition datetime span (start/end).* **V: T**
  (`l0product.build_root_metadata`, `test_l0product`). realized
- **REQ-FUNC-036 — Orbit/attitude ephemeris metadata.** *The software shall record `orbit_ephemeris_start/stop`
  (TAI/UTC/UT1 + ECEF position/velocity) in the L0 metadata from a synthesised Sentinel-2 orbit.* **V: T**
  (`sad.orbit_ephemeris`, `test_sad`). realized
- **REQ-FUNC-037 — SAD content.** *The software shall decode/synthesise the Satellite Ancillary Data — AOCS
  attitude quaternion, orbit ephemeris and detector thermal — and pack it as real CCSDS ISP into
  `conditions/anc_data/s{APID}/isp` (replacing the placeholder zero payload).* **V: T** (`sad`, `test_sad`). realized
- **REQ-FUNC-042 — Open-container L0 handoff.** *The software shall additionally emit an
  open-container L0 (`measurements/detector/<band>` + `quality/l0_flags/<band>` + `conditions/*`) that the
  `msi-processor` `l0_decode` unit ingests (produced by the nominal chain's ground-decode phase),
  with `nuc.gain[band]` length matching the detector-axis width.* **V: T** (`test_l0_handoff`),
  **V: I** (consumer pipeline runs on the shared data-store). realized
- **REQ-FUNC-045 — ADF provenance.** *The software shall record per-component ADF provenance in the output
  metadata.* **V: I** (`l0product` `adf_provenance`). realized

### 3.4 ADF / calibration data
- **REQ-FUNC-046 — Real operational GIPP ingest.** *The software shall parse the S2A GIPP
  (R2EQOG/R2DEPI/BLINDP/R2PARA/R2CRCO) into per-pixel ADF arrays.* **V: T** (`gipp.load_gipp_set`,
  `test_gipp`). realized
- **REQ-FUNC-044 — Synthetic fallback.** *The software shall provide physically-plausible fallback ADFs
  when no GIPP is supplied.* **V: T** (`adf.synthesize`). realized
- **REQ-FUNC-047 — Calibration sub-set derivation.** *The software shall derive the dark, relative
  response and absolute coefficient from synthetic CSM sun-diffuser + dark acquisitions, and supply the
  derived (not truth) coefficients to the processor.* **V: T** (`calibration.calibrate`/`estimated_adf`,
  `test_calibration`). realized
- **REQ-FUNC-039 — ESUN spectral ADF.** *The software shall emit a `spectral.zarr` calibration-database ADF
  holding the per-band ESUN (extraterrestrial solar irradiance, Thuillier 2003; S2A/S2B) as `/esun/<band>`
  float32 scalars, in the schema the processor's `toa` unit consumes for TOA reflectance.* **V: T**
  (`sensor.esun`, `adf_writer.write_calibration_db`, `test_adf_writer`). realized
- **REQ-FUNC-015 ADF source** SRF (RD 3), per-pixel dark/PRNU from the operational GIPP.
  **V: I/T**. realized

### 3.4b Real-data E2E requirements
- **REQ-FUNC-091 — PSFD product naming.** *Every emitted product file name shall follow the EOPF
  PSFD §3 rule (ICD-IF-NAME) and round-trip through `naming.parse_psfd_name`; fields not
  derivable from source metadata shall fall back to documented defaults and be flagged.*
  **V: T** (`test_naming`, driver fixture test). realized
- **REQ-FUNC-092 — Onboard-representative ISP payloads.** *The canonical L0 shall carry each
  band as CCSDS-122-lossless-compressed data in real CCSDS space packets (ICD-IF-C122 +
  ICD-IF-ISP layout), and a ground-decode operation shall restore the exact DN.* **V: T**
  (`test_ccsds122`, `test_isp_packetize`, `test_isp`, `test_integration`). realized
- **REQ-FUNC-093 — Real-L1B reconstruction & validation driver.** *The software shall provide a driver
  that reconstructs **L1A → L0plus → L0** from a real Sentinel-2B L1B and (i) validates the reconstructed
  L0 against the real ESA L0 `img` (10/20 m bands ≤ ~4 DN) — the primary criterion; (ii) verifies the
  L0plus codec round-trip `decode(L0plus) == L1A` bit-exact; (iii) reports line-loss accounting and
  CCSDS-122 compression ratios; (iv) performs a structural comparison against a real PSD L0 product.*
  **V: T** (driver fixture tests), **V: I** (SDE full-frame run, `scripts/run_pipeline.py`). realized

- **REQ-FUNC-048 — Calibration-campaign L0 products.** *The software shall synthesize the
  calibration-campaign acquisitions — dark (CSM closed / deep space) and Lambertian
  sun-diffuser — and package each as a real downlink L0 product: CCSDS-122-compressed ISPs,
  PSFD §3 calibration type codes (`S02MSIDCA` / `S02MSISCA`) and operation-mode metadata
  (`DASC` / `ABSR`, ICD-IF-L0-CAL), with the Option-Y cal-DB derived from the same frames.*
  **V: T** (`test_cal_mode`). realized

### 3.5 Deferred functional requirements (specified, not yet realized)
- **REQ-FUNC-043 — Credentialed ADF API.** Load ADFs via the EOPF ADF service. deferred
- **REQ-FUNC-053 — Configurable PU orchestration**, **REQ-FUNC-062 — Dask distribution**. deferred
- **REQ-FUNC-090 — L1C entry + geometry reverse.** **Cancelled** (not applicable to an L1A/L1B entry).

## 4. Performance requirements (REQ-PERF)
- **REQ-PERF-001 — Noise model accuracy.** **Cancelled** (noise is not re-applied in the reverse ladder —
  MTF-deconvolution off; nothing to bound). *Retired requirement.*
- **REQ-PERF-002 — SNR@Lref fidelity.** **Cancelled** (the ladder preserves the real L1B noise rather than
  reproducing a spec SNR; MTF-deconvolution off). *Retired requirement.*
- **REQ-PERF-003 — Radiometric round-trip exactness.** **Cancelled** (the L1A forward∘reverse round-trip is
  no longer a headline capability; the ladder is validated against the real ESA L0, not by a synthetic
  round-trip). *Retired requirement.*
- **REQ-PERF-004 — Calibration recovery.** *Derived dark shall recover truth ($\le 0.5$ DN bound; ~0.05 DN
  typical); relative-response correlation $\ge 0.9$ (>0.99 typical); $A \approx$ `cal_gain` (±5 %).* **V: T**
  (`test_calibration`). realized
- **REQ-PERF-005 — Reconstructed L0 vs real ESA L0.** *The reconstructed L0 DN shall agree with the real
  ESA L0 `img` within ≤ ~4 DN on the 10 m and 20 m bands.* **V: T/A** (`test_real_data`, SDE full-frame
  run). realized

## 5. Interface requirements (REQ-IF)
The REQ-IF set is single-sourced here; the standalone [IRD](ird.md) collects and contextualises it
(interface inventory + design-control anchors) without duplicating the normative text.
- **REQ-IF-001 — Input interface.** EOPF L1A/L1B Zarr (`measurements/d{DD}/b{xx}/img`;
  `…/DD{nn}/B{xx}/l1a_raw_image`). **V: I/T** (ICD §Interfaces). realized
- **REQ-IF-002 — L0 output interface (ICD-IF-L0).** EOPF L0 Zarr v2 (156 arrays + masks + ISP +
  STAC/sensor-config/provenance). **V: I/T** (ICD). realized
- **REQ-IF-003 — GIPP interface.** Real S2A GIPP XML (`S2A_OPER_GIP_*`). **V: I** (ICD). realized

## 6. Quality / non-functional requirements (REQ-QUAL)
- **REQ-QUAL-001 — Minimal dependencies.** Runtime deps = `numpy` (+ `zarr` for I/O); no EOPF CPM required.
  **V: I** (`pyproject.toml`). realized
- **REQ-QUAL-002 — Test coverage & CI.** Automated test suite, green in CI. **V: T** (201 tests at v0.3.0, GitLab CI). realized
- **REQ-QUAL-003 — Originality.** No external-processor source code; the source repos' names do not appear
  in the deliverable. **V: I/R** (grep). realized
- **REQ-QUAL-004 — Reproducibility.** Deterministic outputs — the reconstruction path is a fixed inversion
  (no seeded-noise stage); crc32 checks confirm bit-stable products across runs. **V: T**. realized

## 7. Verification & traceability
Each requirement carries a method (T/A/I/R) and the implementing module/test above. The full
REQ → Design → Code → Test → Method → Status matrix is maintained in **`docs/sdd/traceability.md`** and the
**V&V report** (`docs/vv/report.md`).

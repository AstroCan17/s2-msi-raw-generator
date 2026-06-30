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

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_e2es`) · **DRD:** ECSS-E-ST-40C Rev.1 (SRS; SSS + IRD
folded in, tailored for a single-CSC E2ES). Verification methods: **T** test · **A** analysis · **I**
inspection · **R** review.

## 1. Introduction

### 1.1 Purpose
Specify the requirements for the **reverse End-to-End performance Simulator** of the Sentinel-2 MSI — the
forward-instrument conjugate of the `msi-processor`. The software degrades a Sentinel-2 **L1A/L1B**
product back to a synthetic **L0 RAW** product (focal-plane DN, 12 detectors × 13 bands), impressing the
true instrument effects the forward processor removes.

### 1.2 Scope
Radiometric-only reverse chain (14 algorithm steps S1–S15, ATBD §5), entry at **L1A/L1B** in per-detector
sensor geometry. Geometry inversion (de-orthorectification / L1C entry) is **cancelled** — not applicable
to an L1A/L1B entry (Issue #17). All instrument data isS2-sourced (official PSF, SRF, product noise
model, operational GIPP); nothing is fitted or synthetic in the realized path.

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
The forward `msi-processor` inverts instrument effects (calibration, PSF, equalization, …). The E2ES does
the conjugate: it **impresses** the effects to reconstruct a focal-plane L0 RAW, enabling (a) realistic
L0 generation when true S2 L0 is unavailable, and (b) a radiometric **round-trip V&V** (raw → forward
correct → reverse impress → raw′, residual $\approx 0$) on S2 data with the GIPP.

## 3. Functional requirements (REQ-FUNC)

### 3.1 Input handling
- **REQ-FUNC-001 — Accept L1A/L1B inputs.** *The software shall accept Sentinel-2 L1A and L1B products in
  EOPF Zarr format.* Rationale: the entry levels (RD 1 §1.1). **V: T** (`io.read_l1b_band`/`read_l1a_raw`). realized
- **REQ-FUNC-003 — Per-unit platform support.** *The software shall select per-unit (S2A/S2B/S2C)
  parameters from the product platform.* **V: T** (`sensor.unit_from_platform`, `test_real_data`). realized
- **REQ-FUNC-005 — Reject unsupported inputs.** *The software shall raise a descriptive error for unknown
  bands/units.* **V: T** (`sensor.band` KeyError). realized

### 3.2 Radiometric reverse chain (one requirement per ATBD §5 step)
- **REQ-FUNC-010 — Inverse absolute calibration (S1).** *The software shall convert at-sensor radiance to
  equalized signal DN per the L1 ATBD raw model $X = A \cdot G \cdot L + D$, with $A$ (= `Band.cal_gain`).* **V: T**
  (`reverse.s1_radiance_to_dn`, `test_real_data`). realized
- **REQ-FUNC-014 — PSF re-blur (S6).** *The software shall re-introduce the optical blur by convolving with
  the  per-band, per-unit ESA PSF matrices (B10 → identity).* **V: T** (`adf.real_psf_kernel`,
  `reverse.s6_psf_reblur`, `test_reverse`/`test_real_data`). realized
- **REQ-FUNC-015 — Impress relative response / PRNU (S7).** *The software shall impress the per-pixel
  relative response from the operational GIPP R2EQOG (cubic VNIR / bilinear SWIR).* **V: T**
  (`forward_radiometric_atbd.inverse_equalize`, `adf.from_gipp`, `test_roundtrip_atbd`). realized
- **REQ-FUNC-019 — Re-apply dark signal (S11).** *The software shall add the per-pixel dark signal
  (GIPP R2EQOG COEFF_D; DQR fallback).* **V: T** (`reverse.s11_reapply_dark`, `test_gipp`). realized
- **REQ-FUNC-020 — Reverse onboard equalization (S12).** *The software shall reverse the onboard
  equalization gain/offset.* **V: T** (`reverse.s12_reapply_onboard_eq`). realized
- **REQ-FUNC-021 — Add sensor noise (S13).** *The software shall add signal-dependent noise $\sigma = \sqrt{\alpha^2 + \beta \cdot \mathrm{DN}}$
  with the per-band $\alpha,\beta$ from the L1A product noise model, applied on the signal DN.* **V: T**
  (`reverse.s13_add_noise`, `test_reverse::test_noise_sigma_matches_model_within_5pct`). realized
- **REQ-FUNC-022 — Quantize to 12-bit (S14).** *The software shall clip/round to `uint16` in `[0, 4095]`.*
  **V: T** (`reverse.s14_quantize`). realized
- **REQ-FUNC-013 — Reverse 60 m binning (S5).** *…un-bin B01/B09/B10 to detector resolution.* **V: T**
  (`reverse.s5_unbin`). realized
- **REQ-FUNC-016 — Restore SWIR arrangement (S8).** *…re-stagger B10/B11/B12 readout.* **V: T**
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
- **REQ-FUNC-033 — STAC discovery metadata.** *…platform, instrument, eopf:type, datetime.* **V: T**
  (`l0product.build_root_metadata`). realized
- **REQ-FUNC-034 — Sensor-configuration metadata.** *…spectral_band_info, tdi_configuration_list,
  line_period, per-unit SRF values.* **V: T** (`test_l0product`, `test_integration`). realized
- **REQ-FUNC-045 — ADF provenance.** *The software shall record per-component ADF provenance in the output
  metadata.* **V: I** (`l0product` `adf_provenance`). realized

### 3.4 ADF / calibration data
- **REQ-FUNC-046 — Real operational GIPP ingest.** *The software shall parse the S2A GIPP
  (R2EQOG/R2DEPI/BLINDP/R2PARA/R2CRCO) into per-pixel ADF arrays.* **V: T** (`gipp.load_gipp_set`,
  `test_gipp`). realized
- **REQ-FUNC-044 — Synthetic fallback.** *The software shall provide physically-plausible fallback ADFs
  when no GIPP is supplied.* **V: T** (`adf.synthesize`). realized
- **REQ-FUNC-047 — Calibration sub-set (inverse-crime cure).** *The software shall derive the dark, relative
  response and absolute coefficient from synthetic CSM sun-diffuser + dark acquisitions, and supply the
  derived (not truth) coefficients to the processor.* **V: T** (`calibration.calibrate`/`estimated_adf`,
  `test_calibration`). realized
- **REQ-FUNC-015 ADF source** PSF (SentiWiki), SRF (RD 3), noise model (product), per-pixel
  dark/PRNU (GIPP). **V: I/T**. realized

### 3.5 Deferred functional requirements (specified, not yet realized)
- **REQ-FUNC-043 — Credentialed ADF API.** Load ADFs via the EOPF ADF service. deferred
- **REQ-FUNC-053 — Configurable PU orchestration**, **REQ-FUNC-062 — Dask distribution**. deferred
- **REQ-FUNC-090 — L1C entry + geometry reverse.** **Cancelled** (not applicable to an L1A/L1B entry).

## 4. Performance requirements (REQ-PERF)
- **REQ-PERF-001 — Noise model accuracy.** *Impressed $\sigma$ shall be within ±5 % of $\sqrt{\alpha^2 + \beta \cdot \mathrm{DN}}$ over $\ge 10{,}000$
  pixels.* **V: T** (`test_reverse`). realized
- **REQ-PERF-002 — SNR@Lref fidelity.** *The chain shall reproduce the spec SNR@Lref per band.* **V: T/A**
  (`test_real_data`, <1 % typical / ±5 % bound). realized
- **REQ-PERF-003 — Radiometric round-trip exactness.** *forward∘reverse on L1A DN shall be an exact
  inverse ($\mathrm{RMSE} \to 0$; ~1e-14 observed, bound <1e-6 / <1e-9 synthetic).* **V: T**
  (`test_roundtrip_atbd`, `roundtrip_real_l1a.py`). realized
- **REQ-PERF-004 — Calibration recovery.** *Derived dark shall recover truth ($\le 0.5$ DN bound; ~0.05 DN
  typical); relative-response correlation $\ge 0.9$ (>0.99 typical); $A \approx$ `cal_gain` (±5 %).* **V: T**
  (`test_calibration`). realized

## 5. Interface requirements (REQ-IF)
- **REQ-IF-001 — Input interface.** EOPF L1A/L1B Zarr (`measurements/d{DD}/b{xx}/img`;
  `…/DD{nn}/B{xx}/l1a_raw_image`). **V: I/T** (ICD §Interfaces). realized
- **REQ-IF-002 — L0 output interface (ICD-IF-L0).** EOPF L0 Zarr v2 (156 arrays + masks + ISP +
  STAC/sensor-config/provenance). **V: I/T** (ICD). realized
- **REQ-IF-003 — GIPP interface.** Real S2A GIPP XML (`S2A_OPER_GIP_*`). **V: I** (ICD). realized

## 6. Quality / non-functional requirements (REQ-QUAL)
- **REQ-QUAL-001 — Minimal dependencies.** Runtime deps = `numpy` (+ `zarr` for I/O); no EOPF CPM required.
  **V: I** (`pyproject.toml`). realized
- **REQ-QUAL-002 — Test coverage & CI.** Automated test suite, green in CI. **V: T** (104 tests, GitLab CI). realized
- **REQ-QUAL-003 — Originality.** No external-processor source code; the source repos' names do not appear
  in the deliverable. **V: I/R** (grep). realized
- **REQ-QUAL-004 — Reproducibility.** Seeded RNG; deterministic outputs for fixed seed. **V: T**. realized

## 7. Verification & traceability
Each requirement carries a method (T/A/I/R) and the implementing module/test above. The full
REQ → Design → Code → Test → Method → Status matrix is maintained in **`docs/sdd/traceability.md`** and the
**V&V report** (`docs/vv/report.md`).

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

# Requirements to design traceability

`s2_msi_raw_generator` reconstructs **L1A -> L0plus -> Synthetic L0** by running a S2B L1B backwards
through the exact inverse of the operational Synthetic L0->L1B radiometric chain; success is the Synthetic L0
matching the reference ESA L0 `img` (10/20 m bands <=~4 DN). Each requirement from the SRS (`docs/srs.md`) is
traced to its design component, code, test, verification method (T/A/I/R) and status. Verification details
and quantitative results are in the V&V report (`docs/vv/report.md`).

## Functional requirements

The rows below trace the reverse radiometric reverse chain: descending a S2 L1B through the exact inverse of the
operational Synthetic L0->L1B chain (invert gain/offset, relative response / PRNU, dark, un-bin, SWIR re-stage,
defective, crosstalk, on-board equalization) to reconstruct L1A -> L0plus (CCSDS-122 ISP) -> Synthetic L0.
MTF-deconvolution is OFF, so PSF and noise are intentionally **not** re-applied (REQ-FUNC-014 and
REQ-FUNC-021 retired below).

| REQ ID | Requirement | Design (module) | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-FUNC-001 | Accept L1A/L1B inputs | io | `io.read_l1b_band`, `read_l1a_raw` | `test_roundtrip_atbd`, `test_esa_adf_data` | T | realized |
| REQ-FUNC-003 | Per-unit (S2A/B/C) support | sensor | `sensor.unit_from_platform` | `test_esa_adf_data` | T | realized |
| REQ-FUNC-005 | Reject unsupported inputs | sensor | `sensor.band` (KeyError) | `test_esa_adf_data` | T | realized |
| REQ-FUNC-010 | Invert absolute calibration (DN-domain gain/offset) — radiometric entry of the reverse chain | reverse, sensor | `reverse.s1_radiance_to_dn`, `Band.cal_gain` | `test_reverse`, `test_esa_adf_data` | T | realized |
| REQ-FUNC-011 | Reverse scene framing (S3) | reverse | `reverse.s3_undo_framing` | `test_inc3_steps` | T | realized |
| REQ-FUNC-012 | Remove radiometric offset (S4) | reverse, gipp | `reverse.s4_undo_radiometric_offset` | `test_inc3_steps` | T | realized |
| REQ-FUNC-013 | Reverse 60 m binning (S5) | reverse | `reverse.s5_unbin` | `test_inc3_steps` | T | realized |
| REQ-FUNC-014 | PSF re-blur — **retired** (reverse chain runs with MTF-deconvolution OFF; PSF is not re-applied) | — | — | — | — | retired |
| REQ-FUNC-015 | Re-apply relative response / PRNU when descending L1B->Synthetic L0 | reverse, adf, gipp | `reverse.s7_impress_relative_response`, `adf.from_gipp`, `gipp` | `test_gipp`, `test_esa_adf_data` | T | realized |
| REQ-FUNC-016 | Restore SWIR arrangement (S8) | reverse | `reverse.s8_restage_swir` | `test_inc3_steps`, `test_integration` | T | realized |
| REQ-FUNC-017 | Re-apply crosstalk (S9) | reverse, gipp | `reverse.s9_apply_crosstalk`, `gipp.read_r2crco` | `test_inc3_steps`, `test_gipp` | T | realized |
| REQ-FUNC-018 | Re-insert blind/defective (S10) | reverse, gipp | `reverse.s10_inject_defects`, `gipp.read_r2depi`/`read_blindp` | `test_inc3_steps`, `test_integration` | T | realized |
| REQ-FUNC-019 | Re-apply dark signal (S11) | reverse, gipp | `reverse.s11_reapply_dark`, GIPP `COEFF_D` | `test_gipp`, `test_calibration` | T | realized |
| REQ-FUNC-020 | Reverse onboard equalization (S12) | reverse | `reverse.s12_reapply_onboard_eq` | `test_reverse` | T | realized |
| REQ-FUNC-021 | Add sensor noise — **retired** (noise is not re-introduced in the reverse chain) | — | — | — | — | retired |
| REQ-FUNC-022 | Cast Synthetic L0 to 12-bit DN (final integer cast, part of L0 assembly) | reverse | `reverse.s14_quantize` | `test_reverse` | T | realized |
| REQ-FUNC-030 | Synthetic L0 RAW EOProduct (Zarr) | l0product | `l0product.write_l0_product` | `test_l0product` | T | realized |
| REQ-FUNC-031 | 156 measurement arrays | l0product | `write_l0_product` | `test_l0product::test_full_156_array_contract` | T | realized |
| REQ-FUNC-032 | 156 quality masks | l0product | `write_l0_product` | `test_l0product` | T | realized |
| REQ-FUNC-033 | STAC discovery metadata | l0product | `build_root_metadata` | `test_l0product`, `test_integration` | T | realized |
| REQ-FUNC-034 | Sensor-configuration metadata | l0product, sensor | `build_root_metadata`, `sensor.spectral_band_info` | `test_l0product`, `test_integration` | T | realized |
| REQ-FUNC-044 | Synthetic fallback ADFs | adf | `adf.synthesize` | `test_reverse`, `test_esa_adf_data` | T | realized |
| REQ-FUNC-045 | ADF provenance | l0product | `build_root_metadata` (`adf_provenance`) | `test_l0product`, `test_integration` | I | realized |
| REQ-FUNC-046 | Operational GIPP ingest | gipp, adf | `gipp.load_gipp_set`, `adf.from_gipp` | `test_gipp` | T | realized |
| REQ-FUNC-047 | Calibration sub-set | calibration | `calibration.calibrate`, `estimated_adf` | `test_calibration` | T | realized |
| REQ-FUNC-039 | ESUN spectral ADF | sensor, adf_writer | `sensor.esun`, `adf_writer.write_calibration_db` (spectral.zarr) | `test_adf_writer` | T | realized |
| REQ-FUNC-035 | GPS/OBT line datation | datation, isp, l0product | `datation.Datation`, `isp.parse_cuc_time`, `build_root_metadata` (band_time_stamp) | `test_datation`, `test_isp` | T | realized |
| REQ-FUNC-038 | STAC geometry & orbit | l0product | `build_root_metadata` (bbox/geometry/sat:orbit/datastrip) | `test_l0product` | T | realized |
| REQ-FUNC-040 | Quality-flag taxonomy | quality, l0product | `quality.l0_flags`, `to_msk_qualit`, `from_s10_qa` | `test_quality`, `test_integration` | T | realized |
| REQ-FUNC-041 | EOQC quality report | quality_report, l0product | `quality_report.build_qc_report`, `write_qc_report` | `test_quality_report` | T | realized |
| REQ-FUNC-036 | Orbit/attitude ephemeris | sad, l0product | `sad.orbit_ephemeris`, `synth_orbit_attitude` | `test_sad` | T | realized |
| REQ-FUNC-037 | SAD content (ISP) | sad, l0product | `sad.synth_orbit_attitude`, `pack_sad_isp`, `scan_ccsds_packets` | `test_sad` | T | realized |
| REQ-FUNC-042 | Open-container L0 handoff | l0product, scripts | `l0product.write_l0_opencontainer`, nominal `ground-decode` phase | `test_l0_handoff` | T/I | realized |
| REQ-FUNC-048 | Calibration-campaign Synthetic L0 products (DASC/ABSR) | calibration, caldb, l0product, scripts | `phase_cal_acquire`/`phase_cal_package`/`caldb.derive_from_acquisitions`; PSFD `S02MSIDCA`/`S02MSISCA` | `test_cal_mode` | T | realized |
| REQ-FUNC-091 | PSFD §3 product naming (ICD-IF-NAME) | `naming.py` | `test_naming`, `test_s2_l1b_e2e_driver` | realized |
| REQ-FUNC-092 | CCSDS-122 compressed ISP payloads + ground decode | `ccsds122.py`, `isp.py`, `l0product.py` | `test_ccsds122`, `test_isp_packetize`, `test_isp`, `test_integration` | realized |
| REQ-FUNC-093 | S2 L1B reverse-chain E2E: reconstruct L1A->L0plus->Synthetic L0 from S2B L1B and validate against the reference ESA L0 `img` (10/20 m bands <=~4 DN); L0plus codec round-trip (`decode(L0plus)==L1A`) kept as an internal check | `scripts/run_pipeline.py`, `s3fetch.py` | `test_s2_l1b_e2e_driver`; SDE run (`docs/vv/s2_l1b_e2e.md`) | realized |
| REQ-FUNC-043 | Credentialed ADF API | — | — | — | — | deferred |
| REQ-FUNC-053 | Configurable PU orchestration | — | — | — | — | deferred |
| REQ-FUNC-062 | Dask distribution | — | — | — | — | deferred |
| REQ-FUNC-090 | L1C entry + geometry reverse | — | — | — | — | cancelled |

## Performance requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-PERF-001 | Noise $\sigma$ within ±5 % — **retired** (no noise model is impressed in the reverse chain) | — | — | — | — | retired |
| REQ-PERF-002 | SNR@Lref fidelity — **retired** (measured against the injected noise model; noise not re-applied) | — | — | — | — | retired |
| REQ-PERF-003 | Round-trip exactness (RMSE $\to 0$) — **retired** (L1A forward exact-inverse round-trip; superseded by reverse-chain Synthetic L0 validation, REQ-PERF-005) | — | — | — | — | retired |
| REQ-PERF-004 | Calibration recovery accuracy | calibration | `calibrate` | `test_calibration` | T | realized |
| REQ-PERF-005 | Synthetic L0 DN agrees with the reference ESA L0 `img` within <=~4 DN on the 10/20 m bands | reverse, l0product | reverse chain + `write_l0_product` | `test_s2_l1b_e2e_driver`; `docs/vv/s2_l1b_e2e.md` | T,A | realized |

## Interface requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-IF-001 | EOPF L1A/L1B input interface | io | `read_l1b_band`, `read_l1a_raw` | `test_roundtrip_atbd` | I,T | realized |
| REQ-IF-002 | L0 output interface (ICD-IF-Synthetic L0) | l0product | `write_l0_product` | `test_l0product`, `test_integration` | I,T | realized |
| REQ-IF-003 | GIPP JSON interface | gipp | `gipp.read_*` | `test_gipp` | I | realized |

## Quality requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-QUAL-001 | Minimal dependencies | (packaging) | `pyproject.toml` | — | I | realized |
| REQ-QUAL-002 | Test coverage & CI | (all) | `tests/`, `.gitlab-ci.yml` | 201 tests (v0.3.0) | T | realized |
| REQ-QUAL-003 | Originality (no external-processor source) | (all) | repo | grep | I,R | realized |
| REQ-QUAL-004 | Reproducibility (deterministic output; crc32 checks) | reverse, calibration | crc32 determinism checks | `test_*` | T | realized |

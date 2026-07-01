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

Each requirement from the SRS (`docs/srs.md`) is traced to its design component, code, test, verification
method (T/A/I/R) and status. Verification details and quantitative results are in the V&V report
(`docs/vv/report.md`).

## Functional requirements

| REQ ID | Requirement | Design (module) | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-FUNC-001 | Accept L1A/L1B inputs | io | `io.read_l1b_band`, `read_l1a_raw` | `test_roundtrip_atbd`, `test_real_data` | T | realized |
| REQ-FUNC-003 | Per-unit (S2A/B/C) support | sensor | `sensor.unit_from_platform` | `test_real_data` | T | realized |
| REQ-FUNC-005 | Reject unsupported inputs | sensor | `sensor.band` (KeyError) | `test_real_data` | T | realized |
| REQ-FUNC-010 | Inverse absolute calibration (S1) | reverse, sensor | `reverse.s1_radiance_to_dn`, `Band.cal_gain` | `test_reverse`, `test_real_data` | T | realized |
| REQ-FUNC-011 | Reverse scene framing (S3) | reverse | `reverse.s3_undo_framing` | `test_inc3_steps` | T | realized |
| REQ-FUNC-012 | Remove radiometric offset (S4) | reverse, gipp | `reverse.s4_undo_radiometric_offset` | `test_inc3_steps` | T | realized |
| REQ-FUNC-013 | Reverse 60 m binning (S5) | reverse | `reverse.s5_unbin` | `test_inc3_steps` | T | realized |
| REQ-FUNC-014 | PSF re-blur (S6) | adf, reverse | `adf.real_psf_kernel`, `reverse.s6_psf_reblur` | `test_reverse`, `test_real_data` | T | realized |
| REQ-FUNC-015 | Impress relative response / PRNU (S7) | forward_radiometric_atbd, adf, gipp | `inverse_equalize`, `adf.from_gipp`, `reverse.s7_impress_relative_response` | `test_roundtrip_atbd`, `test_gipp` | T | realized |
| REQ-FUNC-016 | Restore SWIR arrangement (S8) | reverse | `reverse.s8_restage_swir` | `test_inc3_steps`, `test_integration` | T | realized |
| REQ-FUNC-017 | Re-apply crosstalk (S9) | reverse, gipp | `reverse.s9_apply_crosstalk`, `gipp.read_r2crco` | `test_inc3_steps`, `test_gipp` | T | realized |
| REQ-FUNC-018 | Re-insert blind/defective (S10) | reverse, gipp | `reverse.s10_inject_defects`, `gipp.read_r2depi`/`read_blindp` | `test_inc3_steps`, `test_integration` | T | realized |
| REQ-FUNC-019 | Re-apply dark signal (S11) | reverse, gipp | `reverse.s11_reapply_dark`, GIPP `COEFF_D` | `test_gipp`, `test_calibration` | T | realized |
| REQ-FUNC-020 | Reverse onboard equalization (S12) | reverse | `reverse.s12_reapply_onboard_eq` | `test_reverse` | T | realized |
| REQ-FUNC-021 | Add sensor noise (S13) | reverse, sensor | `reverse.s13_add_noise`, `sensor.NOISE_ALPHA/BETA` | `test_reverse::test_noise_sigma_matches_model_within_5pct` | T | realized |
| REQ-FUNC-022 | Quantize to 12-bit (S14) | reverse | `reverse.s14_quantize` | `test_reverse` | T | realized |
| REQ-FUNC-030 | L0 RAW EOProduct (Zarr) | l0product | `l0product.write_l0_product` | `test_l0product` | T | realized |
| REQ-FUNC-031 | 156 measurement arrays | l0product | `write_l0_product` | `test_l0product::test_full_156_array_contract` | T | realized |
| REQ-FUNC-032 | 156 quality masks | l0product | `write_l0_product` | `test_l0product` | T | realized |
| REQ-FUNC-033 | STAC discovery metadata | l0product | `build_root_metadata` | `test_l0product`, `test_integration` | T | realized |
| REQ-FUNC-034 | Sensor-configuration metadata | l0product, sensor | `build_root_metadata`, `sensor.spectral_band_info` | `test_l0product`, `test_integration` | T | realized |
| REQ-FUNC-044 | Synthetic fallback ADFs | adf | `adf.synthesize` | `test_reverse`, `test_real_data` | T | realized |
| REQ-FUNC-045 | ADF provenance | l0product | `build_root_metadata` (`adf_provenance`) | `test_l0product`, `test_integration` | I | realized |
| REQ-FUNC-046 | Operational GIPP ingest | gipp, adf | `gipp.load_gipp_set`, `adf.from_gipp` | `test_gipp` | T | realized |
| REQ-FUNC-047 | Calibration sub-set | calibration | `calibration.calibrate`, `estimated_adf` | `test_calibration` | T | realized |
| REQ-FUNC-039 | ESUN spectral ADF | sensor, adf_writer | `sensor.esun`, `adf_writer.write_calibration_db` (spectral.zarr) | `test_adf_writer` | T | realized |
| REQ-FUNC-035 | Real line datation | datation, isp, l0product | `datation.Datation`, `isp.parse_cuc_time`, `build_root_metadata` (band_time_stamp) | `test_datation`, `test_isp` | T | realized |
| REQ-FUNC-038 | STAC geometry & orbit | l0product | `build_root_metadata` (bbox/geometry/sat:orbit/datastrip) | `test_l0product` | T | realized |
| REQ-FUNC-040 | Quality-flag taxonomy | quality, l0product | `quality.l0_flags`, `to_msk_qualit`, `from_s10_qa` | `test_quality`, `test_integration` | T | realized |
| REQ-FUNC-041 | EOQC quality report | quality_report, l0product | `quality_report.build_qc_report`, `write_qc_report` | `test_quality_report` | T | realized |
| REQ-FUNC-036 | Orbit/attitude ephemeris | sad, l0product | `sad.orbit_ephemeris`, `synth_orbit_attitude` | `test_sad` | T | realized |
| REQ-FUNC-037 | SAD content (real ISP) | sad, l0product | `sad.synth_orbit_attitude`, `pack_sad_isp`, `scan_ccsds_packets` | `test_sad` | T | realized |
| REQ-FUNC-042 | Open-container L0 + L0→L1B E2E | l0product, scripts | `l0product.write_l0_opencontainer`, `scripts/run_e2e_l0_to_l1b.py` | `test_e2e_l1b` | T/I | realized |
| REQ-FUNC-043 | Credentialed ADF API | — | — | — | — | deferred |
| REQ-FUNC-053 | Configurable PU orchestration | — | — | — | — | deferred |
| REQ-FUNC-062 | Dask distribution | — | — | — | — | deferred |
| REQ-FUNC-090 | L1C entry + geometry reverse | — | — | — | — | cancelled |

## Performance requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-PERF-001 | Noise $\sigma$ within ±5 % over $\ge 10^4$ px | reverse | `s13_add_noise` | `test_reverse::test_noise_sigma_matches_model_within_5pct` | T | realized |
| REQ-PERF-002 | SNR@Lref fidelity | sensor, reverse | `Band.cal_gain`, `s13_add_noise` | `test_real_data` | T,A | realized |
| REQ-PERF-003 | Round-trip exactness ($\mathrm{RMSE} \to 0$) | forward_radiometric_atbd | `forward_correct`/`reverse_impress` | `test_roundtrip_atbd`, `scripts/roundtrip_real_l1a.py` | T | realized |
| REQ-PERF-004 | Calibration recovery accuracy | calibration | `calibrate` | `test_calibration` | T | realized |

## Interface requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-IF-001 | EOPF L1A/L1B input interface | io | `read_l1b_band`, `read_l1a_raw` | `test_roundtrip_atbd` | I,T | realized |
| REQ-IF-002 | L0 output interface (ICD-IF-L0) | l0product | `write_l0_product` | `test_l0product`, `test_integration` | I,T | realized |
| REQ-IF-003 | GIPP XML interface | gipp | `gipp.read_*` | `test_gipp` | I | realized |

## Quality requirements

| REQ ID | Requirement | Design | Code | Test | Method | Status |
|---|---|---|---|---|---|---|
| REQ-QUAL-001 | Minimal dependencies | (packaging) | `pyproject.toml` | — | I | realized |
| REQ-QUAL-002 | Test coverage & CI | (all) | `tests/`, `.gitlab-ci.yml` | 104 tests | T | realized |
| REQ-QUAL-003 | Originality (no external-processor source) | (all) | repo | grep | I,R | realized |
| REQ-QUAL-004 | Reproducibility (seeded RNG) | reverse, calibration | `np.random.default_rng(seed)` | `test_*` | T | realized |

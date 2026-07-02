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

# Software verification & validation plan

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1 (Software verification
plan + Software validation plan, SVerP + SValP, combined for a single-CSC E2ES). Companion: the SVR
(`report.md`). Requirements baseline: `../srs.md`.

## 1. Approach

Verification is predominantly by **automated test** against the real-data-anchored algorithms; the four
ECSS methods are used as follows:

| Method | Code | Use in this project |
|---|---|---|
| **Test** | T | Automated `pytest` suite exercising each chain step, the round-trip, the calibration sub-set, the L0 product contract, and the ISP/CCSDS encoding. Primary method. |
| **Analysis** | A | Closed-form / numerical reasoning where a test only bounds the result — e.g. SNR@Lref reproduction from the $\alpha,\beta$ and `cal_gain`. |
| **Inspection** | I | Static check of artefacts — output metadata/provenance, `pyproject` dependencies, GIPP/PSF/SRF provenance. |
| **Review** | R | Manual review — originality (no external-processor source/names), ATBD consistency. |

Each requirement in `../srs.md` carries its method and the implementing test; the closed matrix is in
`../sdd/traceability.md` and the results in `report.md`.

## 2. Verification matrix (by requirement class)

| Requirement class | IDs | Method | Where verified |
|---|---|---|---|
| Input handling | REQ-FUNC-001/003/005 | T | `test_real_data` (`unit_from_platform`), `test_reverse` (band model), I/O readers |
| Reverse chain S1–S14 | REQ-FUNC-010–022 | T | `test_reverse`, `test_inc3_steps`, `test_real_data`, `test_roundtrip_atbd` |
| L0 output product | REQ-FUNC-030–034, 045 | T/I | `test_l0product`, `test_integration` |
| ADF / calibration | REQ-FUNC-044/046/047 | T | `test_gipp`, `test_calibration`, `test_real_data` |
| Performance | REQ-PERF-001…004 | T/A | `test_reverse`, `test_real_data`, `test_roundtrip_atbd`, `test_calibration` |
| Interfaces | REQ-IF-001/002/003 | I/T | `test_l0product`, `test_gipp`, ICD inspection |
| Quality | REQ-QUAL-001…004 | I/R/T | `pyproject` inspection, CI, originality review, seeded determinism |
| L0 completion (ESUN/datation/SAD/EOQC/open container) | REQ-FUNC-035–042 | T/I | `test_adf_writer`, `test_datation`, `test_sad`, `test_quality`, `test_quality_report`, `test_e2e_l1b` |
| Real-data E2E (naming / compressed ISP / round-trip) | REQ-FUNC-091/092/093 | T/I | `test_naming`, `test_ccsds122` + `test_isp_packetize`, `test_real_e2e_driver`; SDE run → `real_e2e` |

## 3. Test environment

- **Runtime:** Python ≥ 3.11; runtime dependencies `numpy` + `zarr` only (no EOPF CPM, no external
  processor). Image export (`save_images.py`) optionally uses `pillow`/`imageio`/`matplotlib`.
- **Continuous integration:** GitLab CI, single `test` stage, image `python:3.12-slim`,
  `pip install numpy pytest zarr` then `pytest tests/ -q --junitxml=report.xml`.
- **Synthetic-fixture tests** run with no external data (tiny inline GIPP fixtures; packaged PSF CSVs under
  `s2_msi_raw_generator/data/psf/`).
- **Real-data tests** are environment-gated and skip unless `S2_E2ES_GIPP_DIR` (operational GIPP folder)
  and `S2_E2ES_L1A` (a L1A `.zarr`) are set.

## 4. Acceptance criteria

- All non-gated tests pass in CI (currently **201 passed, 5 skipped** (v0.3.0) — the skips are the real-data
  tests, which pass when the data env vars are set).
- The radiometric round-trip is an exact inverse within the bounds in §Quantitative results of the SVR.
- The calibration sub-set recovers the impressed dark/relative-response within bounds (inverse-crime cure).
- Every requirement in `../srs.md` marked *realized* is traced to a passing verification item.
- Originality review passes: no external-processor source code or repository/module names in the deliverable.

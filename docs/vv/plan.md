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

**Project:** `s2_msi_raw_generator` runs a Sentinel-2B **L1B** product backwards through the exact
inverse of the operational L0→L1B radiometric chain to reconstruct **L1A → L0plus → Synthetic L0**, validated against
the reference ESA L0 `img`. · **DRD:** ECSS-E-ST-40C Rev.1 (Software verification
plan + Software validation plan, SVerP + SValP, combined for a single-CSC E2ES). Companion: the SVR
(`report.md`). Requirements baseline: `../srs.md`.

## 1. Approach

Verification is predominantly by **automated test** against the S2 L1B-anchored algorithms; the four
ECSS methods are used as follows:

| Method | Code | Use in this project |
|---|---|---|
| **Test** | T | Automated `pytest` suite exercising each reverse-chain inversion step, the calibration sub-set, the Synthetic L0 product contract, the ISP/CCSDS encoding, the L0plus↔L1A bit-exact codec round-trip, and the end-to-end agreement of the Synthetic L0 against the reference ESA L0 `img`. Primary method. |
| **Analysis** | A | Closed-form / numerical reasoning where a test only bounds the result — e.g. the offset/dark/relative-response DN-inversion bound and the Synthetic-L0-vs-ESA-Synthetic L0 DN-agreement reasoning. |
| **Inspection** | I | Static check of artefacts — output metadata/provenance, `pyproject` dependencies, GIPP/PSF/SRF provenance. |
| **Review** | R | Manual review — originality (no external-processor source/names), ATBD consistency. |

Each requirement in `../srs.md` carries its method and the implementing test; the closed matrix is in
`../sdd/traceability.md` and the results in `report.md`.

## 2. Verification matrix (by requirement class)

| Requirement class | IDs | Method | Where verified |
|---|---|---|---|
| Input handling | REQ-FUNC-001/003/005 | T | `test_esa_adf_data` (`unit_from_platform`), `test_reverse` (band model), I/O readers |
| Reverse chain (offset/PRNU/dark/un-bin/SWIR-restage/defective/crosstalk/on-board-eq inversions, un-framing, 12-bit quantize) | REQ-FUNC-010/013/015–020/022 (excl. 014 PSF re-blur, 021 add-noise — MTF-deconvolution is OFF, PSF/noise not re-applied) | T | `test_reverse`, `test_inc3_steps`, `test_esa_adf_data` (Synthetic L1A/Synthetic L0 vs reference ESA L0) |
| L0 output product | REQ-FUNC-030–034, 045 | T/I | `test_l0product`, `test_integration` |
| ADF / calibration | REQ-FUNC-044/046/047 | T | `test_gipp`, `test_calibration`, `test_esa_adf_data` |
| Performance | REQ-PERF-004 (calibration recovery), REQ-PERF-005 (Synthetic L0 DN agrees with reference ESA L0 `img` within ≤~4 DN on the 10/20 m bands) | T/A | `test_esa_adf_data`, `test_calibration` |
| Interfaces | REQ-IF-001/002/003 | I/T | `test_l0product`, `test_gipp`, ICD inspection |
| Quality | REQ-QUAL-001…004 | I/R/T | `pyproject` inspection, CI, originality review, crc32 determinism |
| Synthetic L0 completion (ESUN/datation/SAD/EOQC/open container) | REQ-FUNC-035–042 | T/I | `test_adf_writer`, `test_datation`, `test_sad`, `test_quality`, `test_quality_report`, `test_e2e_l1b` |
| S2 L1B E2E shared machinery (PSFD §3 naming / compressed ISP / L0plus codec round-trip) | REQ-FUNC-091/092/093 | T/I | `test_naming` (PSFD §3 naming), `test_ccsds122` + `test_isp_packetize` (CCSDS-122-lossless / ISP downlink), `test_s2_l1b_e2e_driver` (decode(L0plus)==L1A bit-exact + Synthetic-L0 structure vs reference ESA L0) |

## 3. Test environment

- **Runtime:** Python ≥ 3.11; runtime dependencies `numpy` + `zarr` only (no EOPF CPM, no external
  processor). All quicklook/figure PNGs use the stdlib encoder (no image libraries).
- **Continuous integration:** GitLab CI, single `test` stage, image `python:3.12-slim`,
  `pip install numpy pytest zarr` then `pytest tests/ -q --junitxml=report.xml`.
- **Synthetic-fixture tests** run with no external data (tiny inline GIPP fixtures; packaged PSF CSVs under
  `s2_msi_raw_generator/data/psf/`).
- **S2 L1B tests** are environment-gated and skip unless `S2_GIPP_DIR` (operational GIPP folder)
  and the S2B **L1B** input product (plus the reference ESA L0 reference used for validation) are set.

## 4. Acceptance criteria

- All non-gated tests pass in CI (currently **201 passed, 5 skipped** (v0.3.0) — the skips are the S2 L1B
  tests, which pass when the data env vars are set).
- The Synthetic L0 DN agrees with the reference ESA L0 `img` within ≤~4 DN on the 10/20 m bands
  (REQ-PERF-005), within the bounds in §Quantitative results of the SVR. The L0plus codec round-trip
  `decode(L0plus) == L1A` is bit-exact (supporting check).
- The calibration sub-set recovers the dark/relative-response applied along the reverse chain — derived
  (not truth) from the synthetic CSM calibration frames — within bounds (inverse-crime cure retained).
- Every requirement in `../srs.md` marked *realized* is traced to a passing verification item.
- Originality review passes: no external-processor source code or repository/module names in the deliverable.

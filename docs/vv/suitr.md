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

# Software Unit & Integration Test Report (SUITR)

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1
(SUITR). Plan: [SUITP](suitp.md). This report records the executed unit/integration campaign at the
current baseline; validation-level results (real-data E2E) are in the
[V&V report](report.md) and the [Real-L1A E2E validation](real_e2e.md).

## 1. Configuration baseline under test

- Repository `ipf/s2-msi-raw-generator`, branch `main` (v0.3.0 release baseline, 2026-07-02, plus
  documentation-only changes).
- Latest `main` pipeline: **#31052 — success** (2026-07-02); blocking jobs `unit-tests` and `pages`
  both green.

## 2. Test environment executed

- **CI:** `python:3.12-slim`, `pip install numpy pytest zarr`, `pytest tests/ -q --junitxml=report.xml`
  (JUnit artifact retained on the job).
- **Local cross-check:** Python 3.13.13, zarr v3 environment — same results (the zarr v2/v3 shim keeps
  both majors green; see DEC-09 in the [DJF](../djf.md)).

## 3. Results — grand totals

| Metric | Value |
|---|---|
| Test files | 21 |
| Test functions | 131 |
| Collected cases (with parametrisation) | **206** |
| Passed | **201** |
| Failed / errors | **0** |
| Skipped (environment-gated real-data tests) | 5 |

The 5 skips are the `S2_E2ES_GIPP_DIR` / `S2_E2ES_L1A`-gated tests (SUITP §2); they **pass when the data
is supplied** — verified on the SDE with the operational GIPP and the real bucket L1A (evidence:
[Real-L1A E2E validation](real_e2e.md) and the v0.3.0 run artifacts in the registry package
`s2-msi-e2e-real/0.3.0`).

## 4. Results by area

All areas pass with 0 failures; the per-file inventory and item-under-test mapping is SUITP §3.
Highlights of the exact (non-tolerance) assertions that passed:

- **Codec:** `compress_frame ∘ decompress_frame` bit-exact on every fixture matrix and the env-gated
  real-L1A window (`test_ccsds122`).
- **Packet grammar:** `reassemble_segments ∘ packetize_stream = identity`; 14-bit counter continuity;
  offsets exactly tile the stream (`test_isp_packetize`).
- **Naming:** `parse_psfd_name` round-trips every generated name, including flagged-default fields
  (`test_naming`).
- **Product contract:** full 156-array L0 contract (12 det × 13 bands) with masks, STAC, sensor
  configuration and provenance (`test_l0product`, `test_integration`).
- **Radiometry:** chain steps exactly invertible (rtol 1e-9); noise σ within ±5 % over 40 000 px;
  quantitative bounds vs typical values tabulated in the [V&V report](report.md) §3.

## 5. Anomalies

None open at this baseline. Historical anomalies and their dispositions (doc/test bound discrepancy —
closed; DN-scaled fixture L1A — accepted with rationale) are recorded in the
[V&V report](report.md) §5; the salted-`hash()` reseeding defect was fixed in the v0.3.0 cycle
(CHANGELOG *Fixed*, REQ-QUAL-004).

## 6. Verdict

**PASS.** All non-gated unit and integration tests pass at the current baseline; the environment-gated
tests pass on the SDE with real data. Exit criteria of the SUITP (§5) are met; open validation-level
items are carried in the [QR report](../qr.md).

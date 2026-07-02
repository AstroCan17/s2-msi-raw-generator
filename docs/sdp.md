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

# Software development plan

ECSS-E-ST-40C Rev.1 (with ECSS-Q-ST-80C for product assurance). This SDP defines the development process,
the increment history and the ECSS tailoring for the Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`).

## Process

Increment-based, test-first development. Each increment adds one capability of the reverse chain with its
unit/integration tests, is implemented on a feature branch, reviewed via merge request, and gated on
green continuous integration before merge to `main`. Algorithms are implemented from public
specifications (the ATBD and the Sentinel-2 L1 ATBD) and validated againstS2 data where available.

## Increments

| Inc | Content |
|-----|---------|
| 0 | Scaffold, CI, ATBD + Annex A datasheet |
| 1 | MVP radiometric core (S1, S6, S7, S11–S14) + sensor model +S2 PSF / SRF ADFs |
| 2 | L0 RAW EOProduct assembly (156-array Zarr + STAC / sensor configuration) |
| 3 | Remaining chain steps S3/S4/S5/S8/S9/S10 (framing, offset, binning, SWIR re-arrangement (reverse), crosstalk, defects) |
| 4 | S15 CCSDS ISP packet generation + SAD telemetry |
| 5 | Real per-band noise model ($\alpha, \beta$) + official ATBD raw model $X = A\cdot G\cdot L + D$, dark |
| 6 | Real operational GIPP → per-pixel dark + relative response (`gipp.py`, `BandADF.from_gipp`) |
| 7 | Original ATBD forward + round-trip V&V on a L1A (RMSE ~1e-14) |
| 8 | Calibration sub-set — synthetic CSM sun-diffuser + dark → derived coefficients (inverse-crime cure) |
| Docs | ECSS-E-ST-40C documentation set (SRS, SDD, ICD, DPM, V&V, SUM, SRN, CIDL, SCF, SRF, SDP) |

## ECSS tailoring

This is a single-CSC (Computer Software Configuration item) E2ES of low criticality. The full ECSS DRD
set is tailored as follows:

- **Authored fully:** SRS, SDD, ICD, DPM, V&V plan + report, SUM, ATBD.
- **Authored concisely:** SRN, CIDL, SCF, SRF, this SDP.
- **Folded into this SDP with rationale (not separate documents):**
  - *Software Review Plan (SRevP)* — reviews are conducted per increment as merge-request reviews plus the
    automated CI gate (unit + integration tests must pass before merge).
  - *Software Maintenance Plan (SMP)* — maintenance follows the same feature-branch → MR → CI → `main`
    process in the project repository; releases are recorded in the SRN and `CHANGELOG.md`.
  - *Software Product Assurance Plan (SPAP, ECSS-Q-ST-80C)* — product assurance is implemented by the
    automated test suite (201 tests at v0.3.0), the CI quality gate, the originality policy (REQ-QUAL-003), and
    requirement traceability (`docs/sdd/traceability.md`).

## Configuration management

Version control: git, repository `gitlab.eopf` `e2es/s2-msi-raw-generator`. Branching: short-lived feature branches
(`feat/*`, `docs/*`) merged to `main` via merge request after CI passes; `main` is the controlled baseline.
Continuous integration: `.gitlab-ci.yml` runs the test suite on a public Python image (no credentials).
Configuration items and baseline are listed in the CIDL and SCF.

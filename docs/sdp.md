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

## ECSS tailoring — Document Requirements List (DRL)

This is a single-CSC (Computer Software Configuration item) E2ES of low criticality. The full DRL
(ECSS-E-ST-40C Rev.1 Annexes B–T + ECSS-Q-ST-80C + M-ST-40C items) is dispositioned as follows; every
DRD is either a standalone document or is tailored with recorded rationale.

| DRD | Disposition |
|---|---|
| SSS (Annex B) | standalone — [sss.md](sss.md) |
| IRD (Annex C) | standalone — [ird.md](ird.md); the interface *requirements* stay single-sourced in the SRS (REQ-IF), the IRD references them |
| SRS (Annex D) | standalone — [srs.md](srs.md) |
| ICD (Annex E) | standalone — [icd.md](icd.md) |
| SDD (Annex F) | standalone — [sdd/](sdd/index.rst) incl. the traceability matrix |
| DJF | standalone — [djf.md](djf.md) |
| SRelD (Annex G) | standalone — [srn.md](srn.md) + `CHANGELOG.md` |
| SUM (Annex H) | standalone — [sum.md](sum.md) |
| SVerP + SValP (Annexes I, J) | **combined** into the [V&V plan](vv/plan.md) — single-CSC scope makes separate plans redundant |
| SUITP (Annex K) | standalone — [vv/suitp.md](vv/suitp.md) |
| SVS (Annex L) | **folded into** the [V&V plan](vv/plan.md) §2 verification matrix + [SUITP](vv/suitp.md) §5 pass/fail criteria — the validation specifications are the executable tests themselves |
| SVR (Annex M) | standalone — [V&V report](vv/report.md) + [real-data E2E validation](vv/real_e2e.md) |
| SUITR | standalone — [vv/suitr.md](vv/suitr.md) |
| SRF (Annex N) | standalone — [srf.md](srf.md) |
| SDP (Annex O) | this document |
| SRevP (Annex P) | standalone — [srevp.md](srevp.md) |
| SMP (Annex T) | **folded into this SDP** — maintenance follows the same feature-branch → MR → CI → `main` process; releases recorded in the SRN and `CHANGELOG.md` |
| SPAP (ECSS-Q-ST-80C) | standalone — [spa-plan.md](spa-plan.md) |
| Risk register | standalone — [risk-register.md](risk-register.md) |
| CIDL / SCF (M-ST-40C) | standalone — [cidl.md](cidl.md), [scf.md](scf.md) |
| QR report | standalone — [qr.md](qr.md) |
| ATBD / DPM (mission-specific) | standalone — [atbd/atbd.md](atbd/atbd.md) (issued v1.0), [dpm/](dpm/index.rst) |

## Configuration management

Version control: git, repository `gitlab.eopf` `ipf/s2-msi-raw-generator`. Branching: short-lived feature branches
(`feat/*`, `docs/*`) merged to `main` via merge request after CI passes; `main` is the controlled baseline.
Continuous integration: `.gitlab-ci.yml` runs the test suite on a public Python image (no credentials).
Configuration items and baseline are listed in the CIDL and SCF.

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

# Software Review Plan (SRevP)

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1
(SRevP), tailored for a single-CSC E2ES. This plan states how the ECSS review milestones are implemented
in this project and records the reviews actually held.

## 1. Review implementation

The ECSS review gates are implemented as **merge-request reviews plus the automated CI gate**: every
change reaches `main` only through a feature-branch MR whose pipeline (unit tests + strict docs build) is
green; the MR description carries the engineering rationale and the diff is the review object. Milestone
reviews (below) additionally bundle the document set.

| ECSS review | Objective | Implementation here |
|---|---|---|
| SRR | requirements baseline agreed | SRS baselined with the DRD set (MR !6) |
| PDR/CDR | design + interfaces frozen per increment | per-increment design MRs with ICD/SDD updates (e.g. !12, !27, !28) |
| TRR | test readiness | CI suite green is the standing TRR; env-gated real-data tests document their data preconditions |
| QR | qualification of the release | release MR + SRN + V&V evidence; assessed in the [QR report](qr.md) |
| AR | acceptance | delivery = GitLab Release + registry packages + published docs site |

RID handling: review findings are raised as repository issues or MR discussion threads and must be
resolved (or explicitly dispositioned in the MR description) before merge; documentation findings are
swept in dedicated audit MRs.

## 2. Review record

Milestone-relevant reviews held to date (full list: the repository MR history, 36 MRs):

| Review | MR(s) | Object | Outcome |
|---|---|---|---|
| Requirements/document baseline (SRR-equivalent) | !6 | full ECSS DRD set (SRS/SDD/ICD/DPM/V&V/SUM/SRN/CIDL/SCF/SRF/SDP) | merged; baseline on `main` |
| Scope change — geometry reverse | !1 | L1C entry + geometry-reverse cancellation (REQ-FUNC-090) | approved; SRS updated |
| Design reviews per increment (PDR/CDR-equivalent) | !2–!4, !12, !18–!25 | real ADFs, calibration sub-set, cal-DB writer, L0 completion (datation/SAD/EOQC/open container) | merged on green CI |
| Real-data E2E design + codec (CDR-equivalent) | !27, !28, !29 | CCSDS-122 codec, compressed-ISP L0, E2E driver + PSFD naming | merged; ICD-IF-C122/ISP/NAME controlled |
| Verification reviews | !30, !31, !33 | accessible real-L0 references (GET-403 disposition), per-resolution-group decode fix, per-band statistics report | merged; limits recorded in `real_e2e.md` |
| Qualification/release review (QR-equivalent) | !32 | v0.3.0 release: results, publish job, SRN | merged; Release v0.3.0 + registry `s2-msi-e2e-real/0.3.0` |
| Documentation audit | !35, !36 | staleness sweep (29 findings), landing-page consolidation | merged; findings closed |

## 3. Schedule & logistics

Reviews are event-driven (per MR / per release), not calendar-driven — appropriate to a single-developer
continuous-integration project. The review artefacts (MR descriptions, pipelines, discussion threads) are
retained permanently in the GitLab project and constitute the review minutes.

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

# Software Product Assurance Plan (SPAP)

**Project:** Sentinel-2 MSI Reverse L1B→Synthetic L0 Reconstruction (`s2_msi_raw_generator`, package name deliberately
kept) — runs S2B L1B backwards through the exact inverse of the operational L0→L1B
radiometric chain to reconstruct L1A→L0plus→Synthetic L0 · **DRD:** ECSS-Q-ST-80C
(SPAP), tailored for a single-CSC, low-criticality E2ES. Process baseline: [SDP](sdp.md); review
programme: [SRevP](srevp.md); risks: [risk register](risk-register.md).

## 1. Organization & responsibilities

Single-developer project: the developer holds the engineering, PA and configuration-control roles.
Independence of assurance is achieved **by tooling**, not by separate personnel: every claim of quality
is enforced by an automated gate (CI) or an inspectable artefact (traceability matrix, provenance
metadata), never by assertion. This tailoring is recorded in the SDP and accepted as RSK-05 in the
[risk register](risk-register.md).

## 2. Quality objectives

1. **Correctness** — every *realized* SRS requirement verified by the cited method (T/A/I/R); on
   data the Synthetic L0 matches the reference ESA L0 `img` to ≤~4 DN on the 10/20 m bands, and the
   L0plus CCSDS-122 codec round-trip `decode(L0plus) == L1A` is bit-exact.
2. **Reproducibility** — seeded, deterministic outputs across processes (REQ-QUAL-004).
3. **Originality** — no external-processor source code or names in the deliverable (REQ-QUAL-003).
4. **Minimal footprint** — core runtime = `numpy` (+ `zarr`); executable in any public CI without
   credentials (REQ-QUAL-001).

## 3. Assurance implementation

### 3.1 Automated verification gate
The GitLab CI pipeline (`.gitlab-ci.yml`) is the blocking PA gate on every merge request:

| Job | Stage | Gate | Content |
|---|---|---|---|
| `unit-tests` | test | **blocking** | full `pytest` suite (currently 206 collected: 201 pass, 5 env-gated skips) on `python:3.12-slim`, JUnit report artifact |
| `pages` | docs | **blocking** | strict Sphinx build `-W --keep-going` — every docs warning is an error; publishes the site on `main` |
| `e2e-l1b` | test | manual | reverse-chain consistency check: runs the reverse chain-Synthetic L0 forward through the `msi-processor` (eopf env) and confirms it reproduces the original S2 L1B input to the reverse chain |
| `e2e-s2-l1b` | test | manual | reverse-chain E2E driver run: fetch S2 L1B → invert the radiometric reverse chain to L1A → pack L1A into L0plus (CCSDS-122) → decode (bit-exact sub-check) → assemble Synthetic L0 → validate against the reference ESA L0 |
| `publish-e2e-s2-l1b` | docs | manual | uploads the reverse-chain reconstruction products (Synthetic L0/L1A/L0plus for the S2B L1B input) to the generic package registry (CI job token — no personal credentials) |

`main` accepts only merge requests with a green pipeline (SDP §Process).

### 3.2 Documentation assurance
The ECSS document set is part of the deliverable and is built strict (`-W`): dead references, bad math
and malformed tables fail the pipeline. Staleness is controlled by dedicated audit MRs (e.g. MR !35,
29 findings swept across the DRD set).

### 3.3 Metrics
- **Test count / pass rate** per pipeline (JUnit artifact; current baseline in the [SUITR](vv/suitr.md)).
- **Requirements closure** — realized vs deferred/cancelled, tracked in the
  [traceability matrix](sdd/traceability.md) (51 requirements at v0.3.0).
- **Quantitative quality bounds** — Synthetic L0 reconstruction error vs the reference ESA L0 (≤~4 DN on the 10/20 m
  bands), calibration/GIPP recovery accuracy, and the L0plus CCSDS-122 codec ratio + bit-exactness:
  tabulated with verified bound vs typical observed in the [V&V report](vv/report.md) §3.

### 3.4 Nonconformance handling
Anomalies found in verification are recorded in the V&V report §Anomalies with disposition
(e.g. the doc/test bound discrepancy — closed as documented; the fixture-L1A DN scaling — accepted with
rationale). Defects in released behaviour get a CHANGELOG *Fixed* entry naming the affected requirement
(e.g. the `hash()` reseeding fix, REQ-QUAL-004).

### 3.5 Supplier & reuse control
No subcontracted software. Reused third-party components (numpy, zarr, pytest, Sphinx toolchain) are
mainstream open-source, listed in the [SRF](srf.md) and pinned no tighter than needed (see RSK-06).
Standards implemented from public documents only (CCSDS 122.0-B, EOPF PSFD, Sentinel-2 L1 ATBD) — the
originality policy excludes any proprietary source.

## 4. PA milestones

PA evidence is bundled per release: SRN + CHANGELOG + green pipeline + V&V report update. The
qualification-level assessment (document inventory, criteria closure, open items) is the
[QR report](qr.md).

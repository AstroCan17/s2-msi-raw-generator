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

# Introduction

## Purpose
This Software Design Document (SDD) describes the architecture and detailed design of the **Sentinel-2
MSI Reverse E2ES** (`s2_e2es`). It is the design counterpart of the Software Requirements Specification
(`docs/srs.md`) and the Algorithm Theoretical Basis Document (`docs/atbd/atbd.md`), authored per
**ECSS-E-ST-40C Rev.1** (SDD DRD), tailored for a single Configuration Software Component (CSC).

## Objective
Define how the software realizes the reverse radiometric chain (ATBD §5, steps S1–S15) that degrades a
real Sentinel-2 **L1A/L1B** product back to a synthetic **L0 RAW** product, so that the requirements in
the SRS are met and verifiable. The design also supports the radiometric **round-trip V&V** (forward
correct ∘ reverse impress) and the in-flight **calibration sub-set** (inverse-crime cure).

## Scope
Covers the static architecture (the `s2_e2es` Python package and its modules), the dynamic data flow of
the reverse chain, the key design decisions, and the internal interfaces between components. Geometry
inversion (L1C entry / de-orthorectification) is **out of scope** — cancelled per Issue #17, because
L1A/L1B are already in per-detector sensor geometry. External-processor integration is out of scope by
design (the deliverable is an original, self-contained implementation from public references).

## Content
- **Overview** (`overview.md`) — static architecture (component view, data flow, dependency graph),
  dynamic architecture, behaviour, interface context, and resource budget.
- **Design** (`design.md`) — general design, overall architecture and key design decisions, per-module
  detailed design, and internal interface design.
- **Traceability** (`traceability.md`) — the requirements-to-design-to-code-to-test matrix.

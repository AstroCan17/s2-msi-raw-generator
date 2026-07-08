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
This Software Design Document (SDD) describes the architecture and detailed design of the **Sentinel-2 MSI Synthetic Raw Data Generator** (`s2_msi_raw_generator`). It is the design counterpart of the Software Requirements Specification
(`docs/srs.md`) and the Algorithm Theoretical Basis Document (`docs/atbd/atbd.md`), authored per
**ECSS-E-ST-40C Rev.1** (SDD DRD), tailored for a single Configuration Software Component (CSC).

## Objective
Define how the software **inverts** the operational Sentinel-2 L0→L1B radiometric correction chain,
running a real Sentinel-2B **L1B** product backwards through the exact inverse of each operational step
— undoing offset, relative-response/PRNU, dark, un-binning, SWIR re-staging, defective-pixel, crosstalk
and on-board equalisation — to reconstruct **L1A → L0plus → L0**. MTF-deconvolution is OFF, so PSF and
noise are **not** re-applied. Success is validated against the real ESA **L0 'img'** (reconstructed L0
DN agrees within ≤ ~4 DN on the 10/20 m bands), so that the requirements in the SRS are met and
verifiable. The design also supports the in-flight **calibration sub-set** (inverse-crime cure). The
inversion stages correspond to the ladder steps of ATBD §5 (exact numbering per the ATBD §5 stage
listing).

## Scope
Covers the static architecture (the `s2_msi_raw_generator` Python package and its modules), the dynamic data flow of
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

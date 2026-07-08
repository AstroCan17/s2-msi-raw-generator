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

# Interface Requirements Document (IRD)

**Project:** Sentinel-2 MSI L0 reconstruction generator (`s2_msi_raw_generator`) — runs a real Sentinel-2B
**L1B** backwards through the exact inverse of the operational L0→L1B radiometric chain to reconstruct
**L1A → L0plus (CCSDS-122 ISP) → L0**, validated against the real ESA L0 `img`. · **DRD:** ECSS-E-ST-40C Rev.1
Annex C (IRD). The interface *requirements* are owned by the [SRS](srs.md) (single source, REQ-IF-NNN);
this IRD collects and contextualises them without duplicating their normative text. The interface
*designs* satisfying them are controlled in the [ICD](icd.md).

## 1. Introduction

### 1.1 Purpose
Identify every external interface of the CSCI, state which requirement governs it and where its design
is controlled. The system context and actors are described in the [SSS](sss.md) §2.1.

### 1.2 Convention
Requirement IDs below are **references** into the SRS §5 (and, for interfaces introduced by the
real-data reverse-ladder run, SRS §3.4b); the SRS text is normative. ICD anchors (`ICD-IF-*`) name the controlling
design section in the [ICD](icd.md).

## 2. Interface inventory

| Interface | Direction | Governing requirement (SRS) | Design control (ICD) |
|---|---|---|---|
| L1A/L1B product input (EOPF Zarr) | in | REQ-IF-001 | ICD §Interfaces (input) |
| L0 RAW product output (canonical + open container) | out | REQ-IF-002, REQ-FUNC-042 | ICD-IF-L0 |
| Operational GIPP (S2A `S2A_OPER_GIP_*` XML) | in | REQ-IF-003 | ICD §Interfaces (GIPP) |
| Compressed ISP payload / CCSDS-122 codec stream | internal ↔ out | REQ-FUNC-092 | ICD-IF-C122, ICD-IF-ISP |
| Product file naming (EOPF PSFD §3) | out | REQ-FUNC-091 | ICD-IF-NAME |
| Calibration-database ADFs (`spectral.zarr`, cal-DB) | out | REQ-FUNC-039 | ICD §ADF outputs |
| Public S3 bucket fetch (anonymous, verified GET) — pulls the real S2B L1B that seeds the ladder | in | REQ-FUNC-093 (reverse-ladder real-L1B fetch/validation) | ICD §Data sources |
| `msi-processor` handoff (open-container L0 + ADFs) | out | REQ-FUNC-042, SYS-03 | ICD-IF-L0; processor ICD |

## 3. Interface requirements

### 3.1 Product interfaces
- **REQ-IF-001** (SRS §5) — input: EOPF L1A/L1B Zarr, `measurements/d{DD}/b{xx}/img` /
  `…/DD{nn}/B{xx}/l1a_raw_image`.
- **REQ-IF-002** (SRS §5) — output: EOPF L0 Zarr v2, 156 measurement arrays + quality masks + ISP +
  STAC / sensor-configuration / provenance metadata.
- **REQ-FUNC-042** (SRS §3.3) — the additional open-container L0 form ingested by the `msi-processor`
  `l0_decode` unit.

### 3.2 Data-carrier interfaces
- **REQ-FUNC-092** (SRS §3.4b) — CCSDS-122-lossless payloads in real CCSDS space packets, with a
  bit-exact ground decode (`read_l0_isp_dn`).
- **REQ-FUNC-091** (SRS §3.4b) — EOPF PSFD §3 file naming, round-tripping through
  `naming.parse_psfd_name`; underivable fields fall back to documented, flagged defaults.

### 3.3 Auxiliary-data interfaces
- **REQ-IF-003** (SRS §5) — real S2A operational GIPP XML ingest (R2EQOG/R2DEPI/BLINDP/R2PARA/R2CRCO).
- **REQ-FUNC-039** (SRS §3.4) — ESUN `spectral.zarr` calibration-database ADF in the schema the
  processor's `toa` unit consumes.

## 4. Validation
Each interface requirement carries its verification method and evidence in the SRS and the
[traceability matrix](sdd/traceability.md). The primary interface-level validation on real data is the
reverse ladder itself: the reconstructed L0 RAW `img` compared to the real ESA L0 `img`, with the 10/20 m
bands agreeing to ≤~4 DN. The supporting interface checks — CCSDS-122 / L0plus bit-exact ground decode
(`decode(L0plus)==L1A`, REQ-FUNC-092), PSFD naming round-trip (REQ-FUNC-091), and EOQC on both L0 forms —
are reported in the [real-data reverse-ladder validation](vv/real_e2e.md).

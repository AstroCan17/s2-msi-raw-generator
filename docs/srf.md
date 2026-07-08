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

# Software reuse file

ECSS-E-ST-40C Rev.1 / ECSS-Q-ST-80C. This SRF records reused software and reused data, and states the
originality of the reverse-ladder L0 reconstruction tool: it runs a real Sentinel-2B **L1B** backwards
through the exact inverse of the operational L0->L1B radiometric chain to reconstruct **L1A -> L0plus -> L0**,
validated against the real ESA L0 `img`.
<!-- NAMING CASCADE: repo s2-msi-raw-generator / package s2_msi_raw_generator is a project-wide rename
     across all ECSS docs; not applied unilaterally here. -->

## Introduction

The deliverable reuses only general-purpose, permissively-licensed libraries and **public** ESA/Copernicus
calibration **data**. No mission-processor source code is reused or vendored. All algorithms are original
implementations from public specifications.

## Reused software

| Component | Role | License |
|-----------|------|---------|
| `numpy` | numerical arrays, the entire processing core | BSD-3-Clause |
| `zarr` | EOPF L1A/L1B read + L0 RAW write (optional `read` extra) | MIT |
| Python stdlib `xml.etree.ElementTree` | original GIPP XML parser | PSF |
| `pytest` | test runner (dev only) | MIT |


No EOPF CPM, no geometry library, and no credentialed package is required for the realized path.

## Reused data

All reused data is **public** ESA/Copernicus reference data; only the data values are used (no code):

| Data | Use | Source / provenance |
|------|-----|---------------------|
| Spectral Response Functions | per-unit centre/bandwidth/equivalent wavelength | SRF doc COPE-GSEG-EOPG-TN-15-0007 v4.0 |
| Operational GIPP | per-pixel dark + relative response, defects, offsets | R2EQOG / R2DEPI / BLINDP / R2PARA / R2CRCO (read as data) |
| Sentinel-2 L1 ATBD | forward radiometric model $X = A\cdot G\cdot L + D$ (the algorithm we invert) | S2-PDGS-MPC-ATBD-L1 §4.1.1 (public specification) |

## Originality statement

The reverse-ladder inverse radiometric chain (invert offset, relative-response/PRNU, dark, un-bin, SWIR
re-stage, defective, crosstalk, on-board-eq; MTF-deconvolution OFF), the GIPP reader, the calibration
sub-set and the L1A/L0plus/L0 product assembly are **original implementations** written from the public
Sentinel-2 L1 ATBD and the GIPP data layout. **No external mission-processor source code is copied,
vendored, imported or referenced by name** in this deliverable. This satisfies REQ-QUAL-003 (originality),
verified by inspection (source review + name grep) in the V&V report. The ladder's own V&V uses only this
project's code: the L0plus codec round-trip (decode(L0plus)==L1A, bit-exact) and validation of the
reconstructed L0 against the real ESA L0 `img` (10/20 m bands <=~4 DN).

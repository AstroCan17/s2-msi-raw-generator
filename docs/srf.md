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
originality of the Sentinel-2 MSI Reverse E2ES.

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
| `pillow` / `imageio` / `matplotlib` | optional PNG export for `save_images.py` only | permissive |

No EOPF CPM, no geometry library, and no credentialed package is required for the realized path.

## Reused data

All reused data is **public** ESA/Copernicus reference data; only the data values are used (no code):

| Data | Use | Source / provenance |
|------|-----|---------------------|
| Official ESA PSF matrices | S6 PSF re-blur kernels (per band, per unit) | published PSF matrices; bundled at `s2_e2es/data/psf/` with `PROVENANCE.md` |
| Spectral Response Functions | per-unit centre/bandwidth/equivalent wavelength | SRF doc COPE-GSEG-EOPG-TN-15-0007 v4.0 |
| Product noise model (α, β) | S13 sensor-noise coefficients | read from the L1A product `quality_indicators_info/.../noise_model` |
| Operational GIPP | per-pixel dark + relative response, defects, offsets | R2EQOG / R2DEPI / BLINDP / R2PARA / R2CRCO (read as data) |
| Sentinel-2 L1 ATBD | forward radiometric model `X = A·G·L + D` (the algorithm we invert) | S2-PDGS-MPC-ATBD-L1 §4.1.1 (public specification) |

## Originality statement

The forward/inverse radiometric model, the GIPP reader, the reverse chain, the calibration sub-set and the
L0 RAW assembly are **original implementations** written from the public Sentinel-2 L1 ATBD and the GIPP
data layout. **No external mission-processor source code is copied, vendored, imported or referenced by
name** in this deliverable; the round-trip V&V uses only this project's own code. This satisfies
REQ-QUAL-003 (originality), verified by inspection (source review + name grep) in the V&V report.

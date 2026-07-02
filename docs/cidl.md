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

# Configuration item data list

ECSS-E-ST-40C Rev.1 (with ECSS-Q-ST-80C for product assurance). This CIDL enumerates the configuration
items of the Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) deliverable.

## Introduction

The configuration items are the deliverable documentation, the online project files, and the software
configuration items (the `s2_msi_raw_generator` package, its packaged calibration data, the scripts, and the tests).
All items are version-controlled in the project git repository (`gitlab.eopf` `e2es/s2-msi-raw-generator`); the
authoritative baseline is the `main` branch tip.

## Applicable and reference documents

### Applicable documents
| Ref | Document |
|-----|----------|
| AD 1 | ECSS-E-ST-40C Rev.1 — Space engineering · Software |
| AD 2 | ECSS-Q-ST-80C — Space product assurance · Software product assurance |

### Reference documents
| Ref | Document |
|-----|----------|
| RD 1 | `docs/atbd/atbd.md` — Algorithm Theoretical Basis Document (issued v1.0) |
| RD 2 | Sentinel-2 L1 ATBD (S2-PDGS-MPC-ATBD-L1) — forward radiometric model §4.1.1 |
| RD 3 | Sentinel-2 Spectral Response Functions, doc COPE-GSEG-EOPG-TN-15-0007 v4.0 |
| RD 4 | Sentinel-2 operational GIPP (R2EQOG / R2DEPI / BLINDP / R2PARA / R2CRCO) |

## List

### Customer-controlled documentation
| Item | File | DRD |
|------|------|-----|
| Algorithm Theoretical Basis Document | `docs/atbd/atbd.md` | ATBD |
| Software Requirements Specification | `docs/srs.md` | SRS (SSS + IRD folded) |
| Software Design Document | `docs/sdd/` | SDD |
| Interface Control Document | `docs/icd.md` | ICD |
| Data Processing Model | `docs/dpm/` | DPM |
| Verification & Validation plan | `docs/vv/plan.md` | SVerP + SValP |
| Verification & Validation report | `docs/vv/report.md` | SVR |
| Software User Manual | `docs/sum.md` | SUM |
| Software Release Note | `docs/srn.md` | SRelD |
| Configuration Item Data List | `docs/cidl.md` | CIDL |
| Software Configuration File | `docs/scf.md` | SCF |
| Software Reuse File | `docs/srf.md` | SRF |
| Software Development Plan | `docs/sdp.md` | SDP (SRevP/SMP/SPAP folded) |

### Online documentation
| Item | File |
|------|------|
| Project overview | `README.md` |
| Change log | `CHANGELOG.md` |
| License | `LICENSE` (Apache-2.0) |
| Calibration-data provenance | `s2_msi_raw_generator/data/psf/PROVENANCE.md` |

### Software configuration items
| Item | Path |
|------|------|
| Sensor model | `s2_msi_raw_generator/sensor.py` |
| ADF assembly | `s2_msi_raw_generator/adf.py` |
| Operational-GIPP reader | `s2_msi_raw_generator/gipp.py` |
| ATBD forward/inverse radiometric model | `s2_msi_raw_generator/forward_radiometric_atbd.py` |
| Reverse chain (S1–S15) | `s2_msi_raw_generator/reverse.py` |
| Calibration sub-set | `s2_msi_raw_generator/calibration.py` |
| ISP / telemetry | `s2_msi_raw_generator/isp.py` |
| EOPF product reader | `s2_msi_raw_generator/io.py` |
| L0 RAW product assembly | `s2_msi_raw_generator/l0product.py` |
|S2 PSF matrices | `s2_msi_raw_generator/data/psf/{S2A,S2B,S2C}/*.csv` |
| CCSDS-122 lossless codec (stream: ICD-IF-C122) | `s2_msi_raw_generator/ccsds122.py` |
| Product naming system (ECSS-M-ST-40C identification coding; rule: ICD-IF-NAME / EOPF PSFD §3) | `s2_msi_raw_generator/naming.py` |
| Anonymous S3 fetch (bucket inputs) | `s2_msi_raw_generator/s3fetch.py` |
| Pipeline driver (real + synthetic chains; V&V: `docs/vv/real_e2e.md`) | `scripts/run_pipeline.py` |
| Demonstration & V&V scripts | `scripts/*.py` |
| Test suite | `tests/test_*.py` |
| Build / packaging | `pyproject.toml` |
| Continuous integration | `.gitlab-ci.yml` |

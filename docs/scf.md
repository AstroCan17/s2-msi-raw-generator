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

# Software configuration file

ECSS-E-ST-40C Rev.1. This SCF records the as-built configuration of `s2_msi_raw_generator`, the SW config
item that runs a real Sentinel-2B L1B backwards through the exact inverse of the operational L0→L1B
radiometric chain to reconstruct L1A → L0plus → L0.

## Introduction

The Software Configuration File documents the inventory, baseline, build means and known issues of the
`s2_msi_raw_generator` software configuration item, so that the delivered package can be rebuilt and run
reproducibly. The item inverts the operational radiometric chain step by step (invert offset,
relative-response/PRNU, dark, un-bin, SWIR re-stage, defective, crosstalk, on-board-eq); MTF-deconvolution
is OFF, so PSF and noise are not re-applied. Success is the reconstructed L0 'img' matching the real ESA L0
(10/20 m bands ≤ ~4 DN).

## Software configuration item overview

| Field | Value |
|-------|-------|
| Name | Sentinel-2 MSI L1B → L1A/L0plus/L0 reverse reconstruction |
| Package | `s2_msi_raw_generator` |
| Version | `0.3.0` (`s2_msi_raw_generator/__init__.py`) |
| Repository | `gitlab.eopf` `ipf/s2-msi-raw-generator`, branch `main` |
| License | Apache-2.0 |
| Language / runtime | Python ≥ 3.11 |
| Build backend | `flit_core` (`pyproject.toml`) |

## Inventory of materials

- **Source modules** (`s2_msi_raw_generator/`): `sensor.py`, `adf.py`, `gipp.py`, `forward_radiometric_atbd.py`,
  `reverse.py`, `calibration.py`, `isp.py`, `io.py`, `l0product.py`, `__init__.py`.
- **Packaged data** (`s2_msi_raw_generator/data/psf/`):S2 PSF matrices, 12 bands × 3 units (S2A/S2B/S2C) CSV
  (B10 absent by design) + `PROVENANCE.md`.
- **Scripts** (`scripts/`): `demo_reverse_real.py`, `demo_build_l0.py`, `derive_prnu_dark.py`,
  the single pipeline driver `run_pipeline.py` (all phases).
- **Tests** (`tests/`): `test_reverse.py`, `test_real_data.py`, `test_calibration.py`,
  `test_roundtrip_atbd.py`, `test_l0product.py`, `test_gipp.py`, `test_isp.py`, `test_integration.py`,
  `test_inc3_steps.py`; full inventory = `tests/test_*.py` (21 files, 201 tests at v0.3.0).
- **Documentation** (`docs/`): ATBD, SRS, SDD, ICD, DPM, V&V, SUM, SRN, CIDL, SCF, SRF, SDP.
- **Project files**: `pyproject.toml`, `.gitlab-ci.yml`, `README.md`, `CHANGELOG.md`, `LICENSE`.

## Baseline documents

The baseline is the `main` branch tip. Applicable standards: ECSS-E-ST-40C Rev.1, ECSS-Q-ST-80C.
Reference data: ATBD (RD 1), Sentinel-2 L1 ATBD, SRF doc COPE-GSEG-EOPG-TN-15-0007, operational GIPP.

## Means necessary for the software configuration item

| Means | Requirement |
|-------|-------------|
| Python | ≥ 3.11 |
| Runtime dependency | `numpy ≥ 1.26` |
| I/O extra (`read`) | `zarr ≥ 3` |
| Test extra (`dev`) | `pytest ≥ 8`, `zarr` |

No EOPF CPM and no credentials are required for the realized path.

## Installation instructions

```bash
pip install -e ".[read]"     # numpy + zarr
pytest                       # 201 tests at v0.3.0
```

Real-data runs additionally need a GIPP folder (`S2A_OPER_GIP_*.xml`) and an EOPF L1A/L1B Zarr; both are
referenced by configurable paths (not bundled), e.g. `data/gipp` and `data/PDI_MSI_S2_L1A.zarr`.

## Change list

See `CHANGELOG.md`. Increments 0–4 delivered the S1–S15 reverse inversion chain, PSF/SRF ADFs and the
L0 product assembly; increment 5 aligned the per-step inversion with the operational radiometric chain
(the same chain the ladder reruns backwards, with MTF-deconvolution OFF); increment 6 added the
operational-GIPP per-pixel ADFs; increment 7 the L0plus codec round-trip check (decode(L0plus)==L1A,
bit-exact) and L0 'img' validation against the real ESA L0 (10/20 m ≤ ~4 DN); increment 8 the calibration
sub-set (cal-DB / PRNU-dark derivation); the documentation increment delivered the ECSS DRD set.

## Possible problems and known errors

- The operational input is a real Sentinel-2B **L1B**, and the reconstructed L0 'img' is validated against
  the real ESA L0 (10/20 m bands ≤ ~4 DN). Where a **DN-scaled CPM fixture** L1A (`PDI_MSI_S2_L1A`) is used
  instead, it is not physically calibrated radiance — suitable for structure checks and for the L0plus codec
  round-trip (decode(L0plus)==L1A is bit-exact), not for absolute radiometry.
- The operational **GIPP** and **L1A** are not stored in the repository (size / provenance); supply
  them via the configurable path arguments / environment variables (`S2_E2ES_GIPP_DIR`, `S2_E2ES_L1A`).
- L1C entry + geometry reverse is **cancelled** (not applicable to an L1A/L1B entry); a few requirements
  are **deferred** (see SRS §3.5).

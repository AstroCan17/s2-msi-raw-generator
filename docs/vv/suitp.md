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

# Software Unit & Integration Test Plan (SUITP)

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1
(SUITP). Scope split: the [V&V plan](plan.md) owns the verification *strategy* (methods T/A/I/R across
all requirement classes); this SUITP details the **unit and integration test level** — inventory,
environment, pass/fail criteria and execution control. Results: [SUITR](suitr.md).

## 1. Software under test

The CSCI `s2_msi_raw_generator` (all modules) plus its driver scripts, at the `main` baseline. Items
under test are the public functions of each module; the integration level exercises module chains up to
the full reverse pipeline and the Synthetic L0 product contract.

## 2. Test organisation & environment

- **Framework:** `pytest`; configuration in `pyproject.toml` (`testpaths = ["tests"]`).
- **Environment:** Python ≥ 3.11, `numpy` + `zarr` + `pytest` only; CI image `python:3.12-slim`
  (no credentials, no EOPF CPM). Locally reproducible with the same three installs.
- **Fixtures:** synthetic-only by default — tiny inline GIPP XML/JSON fixtures, packaged PSF CSVs
  (`s2_msi_raw_generator/data/psf/`), generated frames. No network access in any non-gated test.
- **Environment-gated S2 L1B tests:** skip unless `S2_GIPP_DIR` (operational GIPP folder) and/or
  `S2_L1A_INPUT` (a S2 L1A `.zarr`) are set; exercised on the SDE.
- **Execution control:** the CI `unit-tests` job runs the full suite on every MR and on `main`
  (`pytest tests/ -q --junitxml=report.xml`, JUnit artifact); a red job blocks merge. The manual
  `e2e-l1b` / `e2e-s2-l1b` jobs add the processor-coupled integration level in the eopf environment.

## 3. Test inventory

131 test functions across 21 files, expanding to **206 collected cases** via parametrisation.

### 3.1 Unit level

| File | Funcs | Items under test |
|---|---|---|
| `test_reverse.py` | 11 | sensor model; S1 radiance→DN (apply absolute gain A); bit-exact invertibility of the reverse chain steps (offset S4, relative-response/PRNU S7, dark S11, un-bin S5, SWIR re-stage S8, crosstalk S9, on-board-eq S12, defective S10); 12-bit quantize/clip to Synthetic L0 DN (S14) |
| `test_esa_adf_data.py` | 11 | ESA SRF load & normalisation (sensor/spectral model); per-unit calibration parameters (dark, PRNU/relative-response, offset, gain) parsed from the operational GIPP |
| `test_calibration.py` | 4 | calibration sub-set recovery (dark, relative response, absolute coefficient) |
| `test_roundtrip_atbd.py` | 5 | bit-exact invertibility of each reversible reverse-chain step (offset/PRNU/dark/un-bin/SWIR/crosstalk/on-board-eq), FPN flattening (relative-response/PRNU inversion); headline validation is now the Synthetic L0 vs the reference ESA L0 `img` (10/20 m bands ≤ ~4 DN) |
| `test_gipp.py` | 8 | GIPP JSON/XML parsers (REQOG/RDEPI/BLIND/RPARA/RCRCO), ADF assembly |
| `test_inc3_steps.py` | 6 | S4/S5/S8/S9/S10 steps individually |
| `test_ccsds122.py` | 9 | DWT 9/7-M reversibility (edge cases), block/scan round-trip, Rice coding, segment-header parse, compress∘decompress bit-exact; env-gated S2 L1A window |
| `test_isp.py` | 11 | CCSDS primary header, CUC time, APID rules, frame ISP contract, SAD packets |
| `test_isp_packetize.py` | 7 | `SEQ_FIRST/CONT/LAST` grammar, 14-bit counter continuity, `reassemble∘packetize = id`, offsets tiling |
| `test_naming.py` | 12 | PSFD §3 grammar, `parse_psfd_name` round-trip, metadata-derived fields + flagged defaults |
| `test_s3fetch.py` | 11 | S3 list/paging parse (fixture XML, no network), verified GET semantics, path-traversal guard |
| `test_datation.py` | 5 | GPS/OBT line datation, epoch metadata |
| `test_sad.py` | 6 | AOCS/orbit/thermal SAD synthesis and CCSDS packing |
| `test_quality.py` / `test_quality_report.py` | 4+4 | QAFlag/MSK_QUALIT taxonomy; EOQC report |
| `test_adf_writer.py` | 5 | calibration-database ADF writer (`spectral.zarr`, ESUN schema) |
| `test_quicklook.py` | 3 | dependency-free quicklook rendering |

### 3.2 Integration level

| File | Funcs | Chain under test |
|---|---|---|
| `test_integration.py` | 1 | S2/synthetic L1B → `reverse_full` (S1–S14, with PSF re-blur S6 and noise S13 DISABLED — MTF-deconvolution off, noise not re-applied): offset/PRNU/dark/un-bin/SWIR-restage/crosstalk/on-board-eq inversion (+ defective S10) → L0plus → Synthetic L0, then S15 ISP → full Synthetic L0 product, 2 det × 6 bands incl. SWIR + defects |
| `test_l0product.py` | 5 | L0 write + reopen: 156-array contract, STAC/sensor-config/provenance metadata, compressed-ISP branch |
| `test_e2e_l1b.py` | 3 | open-container Synthetic L0 → processor-schema handshake (CI-side schema checks; full chain in the manual `e2e-l1b` job) |
| `test_s2_l1b_e2e_driver.py` | 3 | driver phases preflight → package → ground-decode on a synthetic PDI fixture; SDE-gated decode/validate phases |

## 4. Features not tested at this level

- Absolute radiometry against a physically-calibrated product (no such public product; see RSK-04).
- Real image-ISP payload decode (proprietary MRCPB; `.bin` objects GET-403 — RSK-01). The
  structural scan of reference streams is part of the E2E validation, not the unit/integration level.
- Interoperability with external CCSDS-122 reference decoders (documented divergence DEC-05).

## 5. Pass/fail criteria

- A test **passes** only on exact assertion — bit-identity uses `np.array_equal`; numerically bounded
  checks state their tolerance in the test (and in the [V&V report](report.md) §3 table).
- The suite passes when **all non-gated tests pass** (0 failures, 0 errors); env-gated skips are
  expected in CI and must pass when their data is supplied.
- Regression rule: a change may not reduce the collected-test count without an MR-recorded rationale.

## 6. Risks & contingencies

Test-level risks are RSK-03 (bucket drift → gated tests), RSK-06 (dependency drift → CI catches on
next MR) and RSK-07 (processor-env coupling → confined to manual jobs) in the
[risk register](../risk-register.md).

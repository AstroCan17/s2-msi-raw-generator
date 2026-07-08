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

# Software release note

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1 (Software release
document, SRelD). Full history: `../CHANGELOG.md`.

## 1. Release

- **Package:** `s2_msi_raw_generator` · **version:** `0.3.0` · **date:** 2026-07-02.
- **Status:** all-real-data reverse-ladder run (real S2B L1B → L1A → L0plus → L0); 201 tests pass (v0.3.0);
  GitLab CI green on `main`.
- **License:** Apache-2.0.

## 2. Contents

- Reverse ladder (`reverse.py`): run a real L1B backwards through the exact inverse of the operational
  L0→L1B chain — invert offset, relative-response/PRNU, dark, un-bin, SWIR re-stage, defective, crosstalk,
  on-board-eq — with MTF-deconvolution OFF (PSF and noise are **not** re-applied), reconstructing
  L1A → L0plus → L0; ISP packetization (`isp.py`) and L0 RAW EOProduct assembly (`l0product.py`).
- Real-data ADFs: the original operational-GIPP reader (`gipp.py` → per-pixel dark + relative response that
  the ladder inverts) and the per-unit SRF spectral characterisation / sensor model (`sensor.py`, used for
  the SWIR re-stage and relative-response inversion).
- Exact radiometric **inverse** (`forward_radiometric_atbd.py`) the ladder uses to undo gain/offset
  ($X = A\cdot G\cdot L + D \rightarrow$ recover $L$); the forward relation appears only as the thing being
  inverted. Plus the calibration sub-set (`calibration.py`, cal-DB derivation).
- Documentation set (this release): ATBD (issued v1.0), SRS, SDD, ICD, DPM, V&V plan + report, SUM, this
  SRN, CIDL, SCF, SRF, SDP; plus README, CHANGELOG, LICENSE.
- Scripts: `demo_reverse_real.py` (reverse ladder), `demo_build_l0.py` (L0 assembly),
  `demo_calibration.py` (cal-DB), `derive_prnu_dark.py` (dark / relative-response derivation) — since
  consolidated into `scripts/run_pipeline.py`.

## 3. Changes (this cycle)

**v0.3.0 — real-data reverse ladder:** CCSDS 122.0-B lossless codec (`ccsds122.py`, ICD-IF-C122);
compressed-ISP canonical L0 (`isp.packetize_stream`, ground decode `read_l0_isp_dn`); EOPF PSFD §3 naming
(`naming.py`, ICD-IF-NAME); real S2B L1B run backwards to a reconstructed L0 that is validated against the
real ESA L0 `img` — the 10/20 m bands agree to ≤ ~4 DN — with the L0plus stream compressed losslessly at
3.66× (`docs/vv/real_e2e.md`); products in the package registry `e2e-real/0.3.0`; Release v0.3.0.

- **Real operational GIPP** → per-pixel dark + relative response (replaces the DQR-summary dark / seeded
  PRNU).
- **Official L1 ATBD raw relation** $X = A\cdot G\cdot L + D$ (true 12-bit DN) is the forward relation the
  ladder **inverts** — undo the offset $D$, then the gain $A\cdot G$ — to recover L1A/L0. Noise is not
  re-applied (MTF-deconvolution OFF).
- **Calibration sub-set** — synthetic CSM diffuser + dark → derived coefficients (inverse-crime cure).
- **Documentation:** ATBD issued v1.0; added the full ECSS-E-ST-40C DRD set, LICENSE (Apache-2.0), CHANGELOG.

## 4. Known limitations

- **L1C entry + geometry reverse — cancelled** (not applicable to an L1A/L1B entry; no orthorectification to
  undo). Geometry inversion is out of scope.
- **Deferred requirements:** credentialed ADF service (REQ-FUNC-043), configurable PU orchestration
  (REQ-FUNC-053), Dask distribution (REQ-FUNC-062).
- Radiometric validation is against the real ESA L0 `img` (the reconstructed L0 agrees to ≤ ~4 DN on the
  10/20 m bands). The publicly available EOPF **test L1B/L1A is DN-scaled** (not a physically-calibrated
  radiance product), and real physically-calibrated S2 L1A/L1B is not publicly distributed.
- A **dark-calibration** (night/ocean) granule was not available; the dark is the per-pixel GIPP
  value (DQR-range), not derived from a dedicated dark acquisition.

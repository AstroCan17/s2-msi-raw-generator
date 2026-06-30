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

**Project:** Sentinel-2 MSI Reverse E2ES (`s2_e2es`) · **DRD:** ECSS-E-ST-40C Rev.1 (Software release
document, SRelD). Full history: `../CHANGELOG.md`.

## 1. Release

- **Package:** `s2_e2es` · **version:** `0.3.0.dev0` · **date:** 2026-06-30.
- **Status:** all-real-data reverse E2ES; 104 tests pass; GitLab CI green on `main`.
- **License:** Apache-2.0.

## 2. Contents

- Reverse radiometric chain S1–S15 (`reverse.py`, `isp.py`) and L0 RAW EOProduct assembly (`l0product.py`).
- Real-data ADFs: official ESA PSF matrices (`s2_e2es/data/psf/`), per-unit SRF spectral characterisation
  and product noise model (`sensor.py`), and the original operational-GIPP reader (`gipp.py`).
- Forward radiometric model + exact inverse (`forward_radiometric_atbd.py`) and the calibration sub-set
  (`calibration.py`).
- Documentation set (this release): ATBD (issued v1.0), SRS, SDD, ICD, DPM, V&V plan + report, SUM, this
  SRN, CIDL, SCF, SRF, SDP; plus README, CHANGELOG, LICENSE.
- Scripts: `demo_reverse_real.py`, `demo_build_l0.py`, `roundtrip_real_l1a.py`, `demo_calibration.py`,
  `save_images.py`, `derive_prnu_dark.py`.

## 3. Changes (this cycle)

- **Real operational GIPP** → per-pixel dark + relative response (replaces the DQR-summary dark / seeded
  PRNU).
- **Official L1 ATBD raw model** `X = A·G·L + D` in true 12-bit DN; `cal_gain` anchored on the noise
  α,β + SNR@Lref; noise impressed on the signal DN.
- **Original ATBD forward + round-trip V&V** on a L1A (RMSE ~1e-14).
- **Calibration sub-set** — synthetic CSM diffuser + dark → derived coefficients (inverse-crime cure).
- **Documentation:** ATBD issued v1.0; added the full ECSS-E-ST-40C DRD set, LICENSE (Apache-2.0), CHANGELOG.

## 4. Known limitations

- **L1C entry + geometry reverse — cancelled** (not applicable to an L1A/L1B entry; no orthorectification to
  undo). Geometry inversion is out of scope.
- **Deferred requirements:** credentialed ADF service (REQ-FUNC-043), configurable PU orchestration
  (REQ-FUNC-053), Dask distribution (REQ-FUNC-062).
- The publicly available EOPF **test L1A is DN-scaled** (not a physically-calibrated radiance product);
  absolute-radiometry checks therefore rely on round-trip self-consistency with the GIPP. Real
  physically-calibrated S2 L1B/L1A is not publicly distributed.
- A **dark-calibration** (night/ocean) granule was not available; the dark is the per-pixel GIPP
  value (DQR-range), not derived from a dedicated dark acquisition.

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

# Risk register

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · ECSS-M-ST-80C-style
risk register, tailored for a single-CSC E2ES. Reviewed at each release (SRN cycle); risks realized or
retired are moved to §4.

## 1. Scoring

Likelihood **A** (minimum) … **E** (maximum); severity **1** (negligible) … **5** (catastrophic).
Index = likelihood × severity; **red** ≥ D4/E3, **yellow** ≥ C3/B4, **green** below.

## 2. Active risks

| ID | Risk | L | S | Index | Mitigation / fallback |
|---|---|---|---|---|---|
| RSK-01 | **Real image-ISP ground truth unavailable** — the PSD L0 SAFE image `.bin` objects are HTTP 403 under the bucket policy, so real image-packet accounting stays informative-only; a future policy change could also remove the SADATA tars used for the structural scan. | C | 2 | yellow | Limitation recorded verbatim in `isp_structural.json` and [Real-L1A E2E validation](vv/real_e2e.md); the acceptance criteria never depended on the 403'd objects. Re-run the structural scan if access opens. |
| RSK-02 | **Codec interoperability** — the documented §4.5.3 divergence (DEC-05, [DJF](djf.md)) means external CCSDS-122 reference decoders cannot read our streams; consumers must use the packaged decoder. | E (by design) | 2 | yellow | Divergence documented in ICD-IF-C122 with the rate cost quantified; decoder ships in the package; a future full-BPE MR closes the gap if interop is ever required. |
| RSK-03 | **Public bucket availability / drift** — inputs (L1A, GIPP, real L0 references) come from a public bucket whose content or policy may change, breaking the env-gated real-data tests and driver phases. | B | 3 | green | Fetch layer verifies size/ETag-md5 per object and writes a manifest; fetched inputs are cached on the SDE (`~/data-store/inputs`); published registry packages (`e2e-real/0.3.0`) freeze the authoritative run's products. |
| RSK-04 | **DN-scaled test L1A** — the public EOPF L1A is not a physically-calibrated radiance product, so absolute-radiometry validation is limited to round-trip self-consistency with the real GIPP. | E (state of the data) | 2 | yellow | Recorded in SRN §Known limitations and V&V report §Anomalies; if a calibrated L1A/L1B becomes public, extend `test_real_data` with absolute checks. |
| RSK-05 | **Single-developer bus factor** — one developer holds the context; review independence relies on tooling (CI gates, tests) rather than a second reviewer. | E | 2 | yellow | Full ECSS doc set + 206-test suite + traceability keep the project transferable; MR-based history records every decision ([SRevP](srevp.md)). |
| RSK-06 | **Dependency drift (zarr / numpy / Python)** — the zarr v2/v3 shim (DEC-09) and the unpinned CI image mean upstream majors can break the suite. | B | 2 | green | CI runs on every MR; the shim isolates zarr API differences in `_zarrio`; pins can be added reactively without design change. |
| RSK-07 | **Processor-side environment coupling** — the E2E drivers depend on the `msi-processor` + `eopf==2.8.1` environment on the SDE; CPM upgrades may break the manual `e2e-l1b`/`e2e-real-l1a` jobs. | C | 2 | green | eopf imports are lazy and confined to the drivers; the core suite (201 tests) is unaffected; the open-container interface (REQ-FUNC-042) is schema-tested in CI without eopf. |

## 3. Top exposure

No red risks. The dominant *accepted* limitations are RSK-01/RSK-04 — both are properties of the public
data landscape, not of the software; both are documented at the point of use and do not affect any
acceptance criterion.

## 4. Retired risks

| ID | Risk | Outcome |
|---|---|---|
| RSK-90 | Non-reproducible band seeding (salted `hash()`) | Realized and fixed — `zlib.crc32` seeds (DEC-10, CHANGELOG v0.3.0 Fixed). |
| RSK-91 | zarr v2/v3 write incompatibility (dual-venv workaround) | Retired by the `_zarrio` shim (MR !23, !26). |
| RSK-92 | Codec throughput on full frames (BPE too slow for 13 full bands) | Retired — segment-vectorised bit-plane packing; the authoritative 13-band full-frame run completed within the SDE job budget. |

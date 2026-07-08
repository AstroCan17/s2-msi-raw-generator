<!-- Copyright 2026 Can Deniz Kaya

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License. -->

# Sentinel-2 MSI Synthetic Raw Data Generator

**Runs a real Sentinel-2B L1B *backwards* through the exact inverse of the operational
L0 → L1B radiometric chain to reconstruct the L1A → L0plus → L0 product ladder** (focal-plane
DN, 12 detectors × 13 bands).

Step by step the ladder **inverts** each operational radiometric correction — offset,
relative-response/PRNU, dark, un-bin, SWIR re-stage, defective pixels, crosstalk and
on-board equalization — against the **real operational GIPP** (per-pixel dark + relative
response), reconstructing the focal-plane counts. Every radiometric coefficient is **real
ESA-sourced** — nothing is fitted or synthetic. **MTF-deconvolution is OFF**, so the PSF
and noise are **not** re-applied.

Its purpose is to reconstruct the **L1A / L0plus / L0 ladder** from a real L1B and validate
it against the real ESA L0 `img`. A calibration sub-set derives the coefficients from
synthetic CSM sun-diffuser + dark acquisitions (the inverse-crime cure). Implemented from
the public L1 ATBD and the GIPP data only.

Source repository:
[gitlab.eopf.copernicus.eu/ipf/s2-msi-raw-generator](https://gitlab.eopf.copernicus.eu/ipf/s2-msi-raw-generator)

## Reverse L1B → L1A → L0plus → L0 ladder (real S2B, 2024-04-08)

The generator's headline path: a real **S2B L1B** run *backwards* through the full operational
radiometric chain into the EOPF product ladder — synthetic **L1A** (decompressed raw counts) →
**L0plus** (CCSDS-122 ISP + ancillary) → **L0** (decoded `img`, **format-identical to the real ESA
`S02MSIL0__` product**). Validated against the real ESA L0 `img` for all 13 bands (detector d05): the
**ten 10 m + 20 m bands agree to ≤ ~4 DN**; the three native-60 m bands (B01/B09/B10) are limited by the
×3 un-bin. Full per-band table, S8-SWIR / framing figures and the run command:
[Reverse ladder V&V report](vv/real_e2e_run_report.md).

![Synthetic L1A vs original ESA L0, all 13 bands (synthetic | real | difference)](_static/showcase/reverse_l1b_allbands.png)

The **L0plus** stage packages the reconstructed L1A as CCSDS-122 ISP records; the codec
round-trip is lossless — `decode(L0plus)` reproduces the L1A counts bit-exactly (overall
lossless ratio ≈ **3.66×**), a supporting check on the ladder's product assembly.

The "real ESA L0" panels contain **modified Copernicus Sentinel data 2024** (Sentinel-2B, 2024-04-08),
shown as low-resolution demo previews only — no raw product data is redistributed.

```{toctree}
:maxdepth: 1
:caption: "Project documentation:"

atbd/atbd
sss
srs
ird
sdd/index
djf
icd
dpm/index
vv/index
cidl
scf
srf
```

```{toctree}
:maxdepth: 1
:caption: "Management & assurance:"

sdp
spa-plan
srevp
risk-register
qr
```

```{toctree}
:maxdepth: 1
:caption: "User documentation:"

sum
srn
API Reference <api/s2_msi_raw_generator>
Source Repository (GitLab) <https://gitlab.eopf.copernicus.eu/ipf/s2-msi-raw-generator>
license
```

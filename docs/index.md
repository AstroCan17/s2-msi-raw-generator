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

**The forward-instrument conjugate of the `msi-processor` — it degrades a real
Sentinel-2 L1A/L1B product back to a synthetic L0 RAW product** (focal-plane DN, 12
detectors × 13 bands).

Where the forward processor *inverts* the instrument effects (radiometric calibration, PSF
deconvolution, equalization, …), the reverse E2ES *impresses* them: a 14-step radiometric
chain (S1–S15) reconstructs a focal-plane L0 RAW. Every radiometric ADF is **real
ESA-sourced** — official PSF matrices, the SRF spectral characterisation, the product noise
model, and the **operational GIPP** (per-pixel dark + relative response) — nothing is
fitted or synthetic.

It serves two purposes: realistic **L0 RAW generation** when true Sentinel-2 L0 is
unavailable, and an original radiometric **round-trip V&V** on L1A data with the real
GIPP (forward correct → reverse impress is an exact inverse, RMSE ~1e-14). A calibration
sub-set derives the coefficients from synthetic CSM sun-diffuser + dark acquisitions (the
inverse-crime cure). Implemented from the public L1 ATBD and the GIPP data only.

Source repository:
[gitlab.eopf.copernicus.eu/ipf/s2-msi-raw-generator](https://gitlab.eopf.copernicus.eu/ipf/s2-msi-raw-generator)

## Real-data E2E (authoritative run, SDE 2026-07-02)

The full **real-L1A** end-to-end (REQ-FUNC-093; details & numbers: [Real-L1A E2E
validation](vv/real_e2e.md)): the public-bucket L1A packaged as a **CCSDS-122-compressed,
real-space-packet L0** (overall lossless ratio **3.66×**, 30 642 packets), ground-decoded
bit-exactly, pushed through msi-processor `l0_decode` — **L1A′ bit-identical to the original
in 13/13 bands**, radiometric GIPP round-trip RMSE ≈ 1e-14.

| Real L1A scene (B04/B03/B02, raw per-detector geometry) | DWT LL3 subband (codec view) |
|---|---|
| ![Real L1A RGB crop](_static/showcase/real_l1a_rgb.png) | ![DWT LL3](_static/showcase/real_dwt_ll3.png) |

A dark ocean scene with cloud speckle; the band-to-band colour misregistration is *real* —
L1A is raw per-detector geometry (co-registration happens at L1B/L1C). Products are published
in the GitLab **Generic Package Registry** (`e2e-real/0.3.0`, PSFD `.zarr.zip` names).

### Single band, stage by stage (B04, real product)

One band through the reverse chain — ideal DN, instrument effects impressed (S6–S13:
PSF re-blur, PRNU, noise, dark, onboard equalization), generated 12-bit RAW (S14). Zoomed
256×256 cloud-edge crops; impressed noise matches the product model to **+1.4 %**,
quantization RMSE is the theory value **0.29 DN**, full-chain radiance recovery
**PSNR 45.1 dB** (bias +0.02 %). Full strips, metric tables and the reproduce command:
repository `README.md` §Result (`S2_E2ES_PHASES=figures scripts/run_pipeline.py`).

| original — ideal DN | effects impressed | RAW L0 DN |
|---|---|---|
| ![B04 original](_static/showcase/result_b04_original_zoom.png) | ![B04 effects](_static/showcase/result_b04_effects_zoom.png) | ![B04 raw](_static/showcase/result_b04_raw_zoom.png) |

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

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

# Context overview

```mermaid
flowchart LR
    L1["L1A / L1B<br/>Sentinel-2 product<br/>(EOPF Zarr, radiance / raw counts)"]
    GIPP["operational S2A GIPP<br/>R2EQOG / R2DEPI / BLINDP /<br/>R2PARA / R2CRCO (XML)"]
    ADF["ADF<br/>PSF matrices (CSV), SRF,<br/>product noise model"]
    E2ES["s2_e2es reverse E2ES<br/>(S1–S15, radiometric)"]
    L0["L0 RAW EOProduct<br/>(Zarr, 156 arrays + ISP + STAC)"]
    CAL["calibration sub-set:<br/>synth diffuser + dark →<br/>derived ADF (inverse-crime)"]
    L1 --> E2ES
    GIPP --> E2ES
    ADF --> E2ES
    E2ES --> L0
    E2ES -.-> CAL
```

**Inputs.** A Sentinel-2 **L1A** (raw DN) or **L1B** (radiance) EOPF Zarr granule; the operational
S2A **GIPP** (per-pixel dark + relative response, defects, offsets, crosstalk); packaged ADFs (ESA
**PSF** matrices, **SRF** spectral characterisation, per-band **noise** model $\alpha,\beta$).

**Processing.** The reverse chain (S1–S15) impresses the instrument effects to reconstruct
focal-plane counts. A separate **calibration sub-set** synthesises sun-diffuser + dark acquisitions and
*derives* the calibration coefficients back — the coefficients a downstream processor would actually use
(inverse-crime cure).

**Output.** A synthetic **L0 RAW** EOProduct (the ICD-IF-L0 Zarr: 156 detector/band frames, quality masks,
optional CCSDS ISP telemetry, STAC + sensor-configuration metadata).

**Verification context.** The radiometric round-trip (`raw → forward correct → reverse impress → raw′`)
on a L1A with the GIPP confirms the forward and reverse are exact inverses (residual $\approx 0$).

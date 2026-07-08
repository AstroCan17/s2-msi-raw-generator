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
    BKT[("public S3 bucket dpr-common:<br/>real L1A · real PSD L0 SAFE · GIPP")]
    L1["real Sentinel-2B L1B<br/>(EOPF Zarr, radiance / counts)<br/>— ladder input"]
    GIPP["operational S2A GIPP<br/>R2EQOG / R2DEPI / BLINDP /<br/>R2PARA / R2CRCO (XML)"]
    ADF["ADF<br/>SRF (spectral characterisation)"]
    E2ES["s2_msi_raw_generator reverse ladder<br/>(invert L0→L1B corrections;<br/>CCSDS-122 + packetize)"]
    L0["L0 RAW EOProduct<br/>(Zarr, compressed-ISP streams + STAC,<br/>PSFD names — ICD-IF-NAME)"]
    CAL["calibration sub-set:<br/>synth diffuser + dark →<br/>derived ADF (inverse-crime)"]
    MSI["msi-processor l0_decode<br/>→ L1A′"]
    REP["validation & report:<br/>reconstructed-L0 vs real ESA L0 'img'<br/>(10/20 m ≤~4 DN) · L0plus codec<br/>round-trip decode==L1A bit-exact"]
    BKT -->|"s3fetch"| L1
    BKT -.->|"real L0 (structural ref)"| REP
    L1 --> E2ES
    GIPP --> E2ES
    ADF --> E2ES
    E2ES --> L0
    E2ES -.-> CAL
    L0 --> MSI --> REP
    L1 -.-> REP
```

**Inputs.** The primary input is a **real Sentinel-2B L1B** (radiance / counts) EOPF Zarr granule; the
operational S2A **GIPP** (per-pixel dark + relative response/PRNU, defects, offsets, crosstalk,
on-board-eq); and the **SRF** for spectral characterisation. L1A is not an input — it is an intermediate
the ladder *produces* on the way down to L0.

**Processing.** The reverse ladder runs the real L1B backwards through the **exact inverse** of the
operational L0→L1B radiometric correction chain — invert offset, relative-response/PRNU, dark, un-bin,
SWIR re-stage, defective, crosstalk, on-board-eq — to reconstruct **L1A → L0plus → L0**. MTF-deconvolution
is OFF, so PSF and noise are **not** re-applied. A separate **calibration sub-set** synthesises
sun-diffuser + dark acquisitions and *derives* the calibration coefficients back — the coefficients a
downstream processor would actually use (inverse-crime cure).

**Output.** The reconstructed **L0 RAW** EOProduct (the ICD-IF-L0 Zarr: 156 detector/band frames, quality
masks, optional CCSDS ISP telemetry, STAC + sensor-configuration metadata); the ladder also emits the
**L1A** and **L0plus** (CCSDS-122 ISP) intermediates en route.

**Verification context.** The reconstructed **L0** is compared against the **real ESA L0 'img'**: the
10/20 m bands agree to **≤~4 DN**. As a supporting check, the **L0plus codec round-trip** is bit-exact —
`decode(L0plus) == L1A`.

## Calibration database (ADF output)

Besides the L0 RAW product, the generator also *derives* the radiometric calibration coefficients and
writes them as a versioned set of EOPF **Auxiliary Data Files** — the **calibration database** — that
the downstream processor (the L1PP blocks of `msi-processor`) consumes directly. This is the single
shared sensor-model ADF of the E2ES ⇄ processor coupling: the generator produces the ADF; the
processor keeps calibration internal. Coefficients are **derived** (synthetic diffuser + dark), not the
truth ADF, so the round-trip is non-tautological.

```mermaid
flowchart LR
    subgraph SRC["derived coefficients (per band)"]
        PR["NUC gain g_d"]
        OF["NUC offset o_d"]
        DK["dark k"]
        AA["abs gain (~1/A)"]
        ES["ESUN (solar irradiance)"]
    end
    subgraph DB["cal-DB — EOPF ADFs (zarr v2)"]
        NUC["nuc.zarr<br/>/gain, /offset"]
        DARK["dark.zarr<br/>/dark_offset"]
        RADO["radiometric.zarr<br/>/gain, /offset"]
        SPECT["spectral.zarr<br/>/esun"]
    end
    PR --> NUC
    OF --> NUC
    DK --> DARK
    AA --> RADO
    ES --> SPECT
```

The NUC `gain`/`offset` follow the processor's two-point convention (`estimate_nuc`); the absolute
`radiometric.gain` is diffuser-derived ($\approx 1/\mathrm{cal\_gain}$); `spectral.zarr` carries the per-band
**ESUN** (Thuillier 2003, S2A — ATBD §A.3) the processor's `toa` unit needs for TOA reflectance. Written by
`s2_msi_raw_generator.adf_writer` (`s2_msi_raw_generator.caldb`, pipeline phase `build-caldb`).

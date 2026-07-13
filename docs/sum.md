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

# Software user manual

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1 (SUM). The E2ES
runs a **S2B L1B** backward through the **exact inverse of the operational L0→L1B
radiometric chain** (invert offset, relative-response/PRNU, dark, un-bin, SWIR re-stage, defective,
crosstalk, on-board-eq; MTF-deconvolution is OFF, so PSF and noise are **not** re-applied) to
reconstruct **L1A → L0plus (CCSDS-122 ISP) → Synthetic L0**. Success is the Synthetic L0 matching the reference
ESA reference ESA L0 `img` (10/20 m bands ≤~4 DN). It also provides cal-DB derivation tooling.

## 1. Installation

Python ≥ 3.11. The runtime needs only **numpy** and **zarr** — no EOPF CPM, no external processor.

```bash
pip install -e ".[read]"     # numpy + zarr (reader + L0 writer)
# or for development (adds pytest):
pip install -e ".[dev]"
```


## 2. Quick start

```bash
pytest                        # full suite (S2 L1B/eopf cases skip without env)
```

The packagedS2 PSF matrices live under `s2_msi_raw_generator/data/psf/`; no external data is needed for the unit
tests. S2 L1B runs need EOPF L1A/L1B `.zarr` and the operational GIPP folder (see §4).

## 3. The pipeline

All operations run through the **single driver** `scripts/run_pipeline.py`: a phase-structured,
idempotent pipeline over one data-store root (`inputs/ caldb/ l0/ l1a_prime/ l1b/ quicklook/
figures/ report/`; `$OUTPUT_DIR`). Copy `.env.example` to `.env` and set the five required path
variables before running the driver. Nominal L0s land under `l0/`;
every calibration product (the `S02MSIDCA`/`S02MSISCA` campaign L0s + the cal-DB ADFs) under
`caldb/`. Every product file name follows the EOPF PSFD §3 convention
(`s2_msi_raw_generator.naming`, REQ-FUNC-091).

| Phase set | Phases | Needs |
|---|---|---|
| **Nominal mode** (default; REQ-FUNC-093) | `fetch-l1a fetch-l0 preflight package ground-decode l0-decode validate radiometric-vv scan-l0 quicklook report` — S2B L1B → inverse radiometric chain → Synthetic L1A → L0plus → Synthetic L0, validated vs the reference ESA L0 | numpy+zarr; `ground-decode`/`l0-decode`/`validate` need `eopf==2.8.1` + `msi_processor` |
| **Calibration mode** (`calibration`; REQ-FUNC-048) | `cal-acquire cal-package build-caldb report` — dark (DASC) + sun-diffuser (ABSR) campaign → **downlink Synthetic L0 products** `S02MSIDCA`/`S02MSISCA` + Option-Y cal-DB, all under `<store>/caldb/` | numpy+zarr only |
| **On demand** | `derive-adf` | numpy+zarr only |
| **Data-store sync** | `fetch-store` (pull, anonymous) · `publish-store` (push, job/`glab` token) | numpy+stdlib; DB = the [ipf/data-store](https://gitlab.eopf.copernicus.eu/ipf/data-store) registry |

```bash
# copy and edit paths once
cp .env.example .env

# pull the shared data-store into the local working copy ($OUTPUT_DIR)
S2_PHASES=fetch-store python scripts/run_pipeline.py

# S2 L1B chain, all phases (fetch → package → decode → validate → report)
python scripts/run_pipeline.py

# re-run individual phases (idempotent; JSON per phase under <store>/report/)
S2_PHASES=preflight,package,ground-decode S2_LINES=4096 python scripts/run_pipeline.py

# calibration campaign: dark + sun-diffuser acquisitions as downlink Synthetic L0 products
# (S02MSIDCA / S02MSISCA, compressed ISPs) + the Option-Y cal-DB — everything → <store>/caldb/
python scripts/run_pipeline.py calibration

# standalone Option-Y cal-DB (same numbers as the campaign derivation — deterministic seeds)
S2_PHASES=build-caldb python scripts/run_pipeline.py

# operational per-detector PRNU (+ dark from a dark-calibration granule) → .npz for BandADF.from_product
S2_PHASES=derive-adf S2_L1A_INPUT=<L1A.zarr> [S2_DARK=<dark.zarr>] python scripts/run_pipeline.py
```

Run the gated tests on S2 data:

```bash
S2_GIPP_DIR=<GIPP_dir> S2_L1A_INPUT=<L1A.zarr> pytest tests/ -q
```

## 4. CLI + configuration reference

`run_pipeline.py [nominal|calibration]` — the CLI takes **only the mode** (default
`nominal`). Copy `.env.example` to `.env` and set paths; optional tuning uses `S2_*` variables:

| Variable | Required | Meaning (consuming phases) |
|---|---|---|
| `S2_L1B_INPUT` | yes | S2 L1B zarr (reverse-l1b, figures) |
| `S2_L0_INPUT` | yes | ESA L0 zarr (validate-reverse, import-l0) |
| `S2_GIPP_DIR` | yes | `aux/gipp-json` band-organised ADF JSON |
| `S2_AUX_DIR` | yes | `aux/` (framing, adf-eopf for RSWIR/REOB2/RCRCO) |
| `OUTPUT_DIR` | yes | pipeline store root (`l0/`, `report/`, …) |
| `S2_PHASES` | no | mode's default set — comma phase list |
| `S2_LINES` | `0` (full) | first-N-lines window |
| `S2_BANDS` | all 13 | band list |
| `S2_SEED` | `0` | RNG seed (cal-acquire, build-caldb) |
| `S2_NDET` | `400` | campaign / cal-DB detector width |
| `S2_CAL_LINES` | `256` | calibration lines per frame |
| `S2_JOBS` | all cores | parallel workers |
| `S2_L1A_INPUT` | — | L1A path override (preflight, derive-adf) |
| `S2_DARK` | — | dark-calibration granule (derive-adf) |
| `S2_PUBLISH_NAME` / `_VERSION` / `_LAYER` | `products` / — / `products` | publish-store coordinates |

Phases are idempotent and re-runnable individually; each writes its JSON under
`<store>/report/` and the final `report` phase assembles `e2e_report.md`. See
`docs/vv/s2_l1b_e2e.md` for the S2 L1B chain acceptance criteria.

## 5. Outputs

- **Synthetic L0 RAW product** — EOPF L0 Zarr (zarr v2): `measurements/d{DD}/b{BB}/band{N}` (uint16, 156 arrays),
  `quality/d{DD}/b{BB}/mask` (uint8), optional `conditions/anc_data/s{APID}/` ISP telemetry, and root
  STAC + `sensor_configuration` + `processing_history.adf_provenance` metadata. See the ICD (`icd.md`).
- **Open-container L0 + cal-DB + L1B** — the processor handoff products (PSFD `_OC` suffix; ADF set
  `nuc/dark/radiometric/spectral[/noise].zarr` + calibration acquisitions `flatfield.zarr`,
  `dark.zarr:/frame`; PSFD-named L1B reflectance).
- **V&V evidence** — per-phase JSONs + `e2e_report.md` under `<store>/report/`. The primary
  acceptance evidence is the `validate` phase: Synthetic L0 vs the reference ESA L0 `img` (10/20 m
  bands ≤~4 DN). `radiometric-vv` is a secondary self-consistency sanity check of the inverse
  radiometric operators.
- **Images** — `quicklook/` PNGs (the Synthetic-L0 quicklook).

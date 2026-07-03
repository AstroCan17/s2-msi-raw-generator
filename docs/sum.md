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
degrades a Sentinel-2 L1A/L1B product back to a synthetic L0 RAW product and provides real-data
verification & calibration tooling.

## 1. Installation

Python ≥ 3.11. The runtime needs only **numpy** and **zarr** — no EOPF CPM, no external processor.

```bash
pip install -e ".[read]"     # numpy + zarr (reader + L0 writer)
# or for development (adds pytest):
pip install -e ".[dev]"
```


## 2. Quick start

```bash
pytest                        # full suite (real-data/eopf cases skip without env)
```

The packagedS2 PSF matrices live under `s2_msi_raw_generator/data/psf/`; no external data is needed for the unit
tests. Real-data runs need an EOPF L1A/L1B `.zarr` and the operational GIPP folder (see §4).

## 3. The pipeline

All operations run through the **single driver** `scripts/run_pipeline.py`: a phase-structured,
idempotent pipeline over one data-store root (`inputs/ caldb/ l0/ l1a_prime/ l1b/ quicklook/
figures/ report/`; `$S2_DATA_STORE`, default `~/data-store`). Nominal L0s land under `l0/`;
every calibration product (the `S02MSIDCA`/`S02MSISCA` campaign L0s + the cal-DB ADFs) under
`caldb/`. Every product file name follows the EOPF PSFD §3 convention
(`s2_msi_raw_generator.naming`, REQ-FUNC-091).

| Phase set | Phases | Needs |
|---|---|---|
| **Nominal mode** (default; REQ-FUNC-093) | `fetch-l1a fetch-l0 preflight package ground-decode l0-decode validate radiometric-vv scan-l0 quicklook report` — real S2 product → synthetic RAW downlink | numpy+zarr; `ground-decode`/`l0-decode`/`validate` need `eopf==2.8.1` + `msi_processor` |
| **Calibration mode** (`calibration`; REQ-FUNC-048) | `cal-acquire cal-package build-caldb report` — dark (DASC) + sun-diffuser (ABSR) campaign → **real downlink L0 products** `S02MSIDCA`/`S02MSISCA` + Option-Y cal-DB, all under `<store>/caldb/` | numpy+zarr only |
| **On demand** | `derive-adf` · `figures` | numpy+zarr only |
| **Data-store sync** | `fetch-store` (pull, anonymous) · `publish-store` (push, job/`glab` token) | numpy+stdlib; DB = the [ipf/data-store](https://gitlab.eopf.copernicus.eu/ipf/data-store) registry |

```bash
# pull the shared data-store into the local working copy ($S2_DATA_STORE, default ~/data-store)
S2_E2ES_PHASES=fetch-store python scripts/run_pipeline.py

# real chain, all phases (fetch → package → decode → validate → report)
S2_E2ES_GIPP_DIR=<GIPP_dir> python scripts/run_pipeline.py

# re-run individual phases (idempotent; JSON per phase under <store>/report/)
S2_E2ES_PHASES=preflight,package,ground-decode S2_E2ES_LINES=4096 python scripts/run_pipeline.py

# calibration campaign: dark + sun-diffuser acquisitions as REAL downlink L0 products
# (S02MSIDCA / S02MSISCA, compressed ISPs) + the Option-Y cal-DB — everything → <store>/caldb/
python scripts/run_pipeline.py calibration

# standalone Option-Y cal-DB (same numbers as the campaign derivation — deterministic seeds)
S2_E2ES_PHASES=build-caldb python scripts/run_pipeline.py

# real per-detector PRNU (+ dark from a dark-calibration granule) → .npz for BandADF.from_product
S2_E2ES_PHASES=derive-adf S2_E2ES_L1A=<L1A.zarr> [S2_E2ES_DARK=<dark.zarr>] python scripts/run_pipeline.py

# README/docs single-band stage figures + quality metrics table
S2_E2ES_PHASES=figures S2_E2ES_L1B=<L1B.zarr[.zip]> python scripts/run_pipeline.py
```

Run the gated tests on real data:

```bash
S2_E2ES_GIPP_DIR=<GIPP_dir> S2_E2ES_L1A=<L1A.zarr> pytest tests/ -q
```

## 4. CLI + configuration reference

`run_pipeline.py [nominal|calibration]` — the CLI takes **only the mode** (default
`nominal`). Everything else is environment-driven:

| Variable | Default | Meaning (consuming phases) |
|---|---|---|
| `S2_DATA_STORE` | `~/data-store` | data-store root (all phases) |
| `S2_E2ES_PHASES` | mode's default set | comma phase list, e.g. `preflight,package` |
| `S2_E2ES_LINES` | `0` (full) | first-N-lines window (preflight→validate, quicklook, derive-adf) |
| `S2_E2ES_BANDS` | all 13 | band list, e.g. `B03,B04` (preflight chain, cal-acquire, derive-adf) |
| `S2_E2ES_SEED` | `0` | RNG seed (cal-acquire, build-caldb, figures) |
| `S2_E2ES_NDET` | `400` | campaign / cal-DB detector width (cal-acquire, build-caldb) |
| `S2_E2ES_CAL_LINES` | `256` | calibration-acquisition lines per frame (cal-acquire, cal-package) |
| `S2_E2ES_L1A` | store download | L1A path override (preflight chain, derive-adf) |
| `S2_E2ES_DARK` | — | dark-calibration granule (derive-adf) |
| `S2_E2ES_GIPP_DIR` | — | operational GIPP dir (radiometric-vv, figures) |
| `S2_E2ES_L1B` | — | real L1B for the `figures` phase |
| `S2_E2ES_PUBLISH_NAME` / `_VERSION` / `_LAYER` | `products` / — / `products` | publish-store package coordinates (`_VERSION` is required by the phase) |

Phases are idempotent and re-runnable individually; each writes its JSON under
`<store>/report/` and the final `report` phase assembles `e2e_report.md`. See
`docs/vv/real_e2e.md` for the real-chain acceptance criteria.

## 5. Outputs

- **L0 RAW product** — EOPF L0 Zarr (zarr v2): `measurements/d{DD}/b{BB}/band{N}` (uint16, 156 arrays),
  `quality/d{DD}/b{BB}/mask` (uint8), optional `conditions/anc_data/s{APID}/` ISP telemetry, and root
  STAC + `sensor_configuration` + `processing_history.adf_provenance` metadata. See the ICD (`icd.md`).
- **Open-container L0 + cal-DB + L1B** — the processor handoff products (PSFD `_OC` suffix; ADF set
  `nuc/dark/radiometric/spectral[/noise].zarr` + calibration acquisitions `flatfield.zarr`,
  `dark.zarr:/frame`; PSFD-named L1B reflectance).
- **V&V evidence** — per-phase JSONs + `e2e_report.md` under `<store>/report/`
  (`radiometric-vv` = the GIPP round-trip table).
- **Images** — `quicklook/` PNGs and the `figures` phase's stage-by-stage set
  (`result_<band>_*.png`, committed under `docs/_static/showcase/`).

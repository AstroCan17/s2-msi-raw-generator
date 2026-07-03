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
figures/ report/`). Every product file name follows the EOPF PSFD §3 convention
(`s2_msi_raw_generator.naming`, REQ-FUNC-091).

| Phase set | Phases | Needs |
|---|---|---|
| **Real chain** (default; REQ-FUNC-093) | `fetch-l1a fetch-l0 preflight package ground-decode l0-decode validate radiometric-vv scan-l0 quicklook report` | numpy+zarr; `l0-decode`/`validate` need `eopf==2.8.1` + `msi_processor` |
| **Synthetic chain** (`--synthetic`; REQ-FUNC-042) | `build-l0-synth l0-to-l1b` | numpy+zarr; `l0-to-l1b` needs the eopf env |
| **On demand** | `build-caldb` · `derive-adf` · `figures` | numpy+zarr only |
| **Data-store sync** | `fetch-store` (pull, anonymous) · `publish-store` (push, job/`glab` token) | numpy+stdlib; DB = the [ipf/data-store](https://gitlab.eopf.copernicus.eu/ipf/data-store) registry |

```bash
# pull the shared data-store into a local working directory
python scripts/run_pipeline.py <store> --phases fetch-store

# real chain, all phases (fetch → package → decode → validate → report)
python scripts/run_pipeline.py ~/data-store --gipp <GIPP_dir>

# re-run individual phases (idempotent; JSON per phase under <store>/report/)
python scripts/run_pipeline.py <store> --phases preflight,package,ground-decode --lines 4096

# synthetic flat-field chain into the repo's tracked data store
python scripts/run_pipeline.py <store> --synthetic

# full 13-band derived Option-Y cal-DB (nuc/dark/radiometric/spectral[+noise] ADFs
# + the raw calibration acquisitions: flatfield.zarr and dark.zarr /frame — the consumer's
# radiometric calibration-mode inputs)
python scripts/run_pipeline.py <store> --phases build-caldb

# real per-detector PRNU (+ dark from a dark-calibration granule) → .npz for BandADF.from_product
python scripts/run_pipeline.py <store> --phases derive-adf --l1a <L1A.zarr> [--dark <dark.zarr>]

# README/docs single-band stage figures + quality metrics table
python scripts/run_pipeline.py <store> --phases figures --fig-l1b <L1B.zarr[.zip]>
```

Run the gated tests on real data:

```bash
S2_E2ES_GIPP_DIR=<GIPP_dir> S2_E2ES_L1A=<L1A.zarr> pytest tests/ -q
```

## 4. CLI reference

`run_pipeline.py <store> [--phases …] [--synthetic] [--l1a PATH] [--dark PATH] [--gipp DIR]
[--bands …] [--detectors 1-12] [--lines N] [--band-groups N] [--max-payload N] [--jobs N]
[--seed N] [--caldb-n-det N] [--store-decoded yes|no] [--fig-l1b PATH] [--fig-band B04]
[--fig-detector N] [--fig-line-start N] [--fig-lines N] [--fig-zoom-*] [--fig-out DIR]`

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

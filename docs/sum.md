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

Optional, only to render preview PNGs with `save_images.py`: `pip install pillow` (or `imageio` /
`matplotlib`).

## 2. Quick start

```bash
pytest                        # 104 tests (2 real-data tests skip without env vars)
```

The packagedS2 PSF matrices live under `s2_msi_raw_generator/data/psf/`; no external data is needed for the unit
tests. Real-data runs need an EOPF L1A/L1B `.zarr` and the operational GIPP folder (see §4).

## 3. Reverse chain → L0 RAW

```bash
# reverse one band of a  L1B granule (radiance → L0 DN), prints a self-consistency check
python scripts/demo_reverse_real.py <L1B.zarr.zip> [detector] [band]

#  L1B → assemble a full synthetic L0 RAW product (156-array Zarr + STAC/sensor-config)
python scripts/demo_build_l0.py [out_dir]
```

## 4. Real-data V&V and calibration

Point the scripts at a L1A `.zarr` and the operational GIPP directory. A convenient layout (the
`data/` folder is gitignored):

```bash
mkdir -p data
ln -s /path/to/GIPP                       data/gipp
ln -s /path/to/PDI_MSI_S2_L1A.zarr        data/PDI_MSI_S2_L1A.zarr
```

```bash
# round-trip V&V: forward correct → reverse impress == identity on  DN (~1e-14 RMSE)
python scripts/roundtrip_real_l1a.py data/PDI_MSI_S2_L1A.zarr data/gipp B02 B03 B11 B12

# calibration sub-set: synthetic CSM diffuser + dark → derived dark/gain (inverse-crime cure)
python scripts/demo_calibration.py data/gipp

# save viewable images (bit-exact .npy + uint8 PNG) of raw / corrected / residual / calibration frames
python scripts/save_images.py data/PDI_MSI_S2_L1A.zarr data/gipp B03 --out images
```

Run the gated tests on data:

```bash
S2_E2ES_GIPP_DIR=data/gipp S2_E2ES_L1A=data/PDI_MSI_S2_L1A.zarr pytest tests/ -q
```

## 5. CLI reference

| Script | Arguments |
|---|---|
| `demo_reverse_real.py` | `[L1B.zarr.zip] [detector=4] [band=B03]` |
| `demo_build_l0.py` | `[out_dir]` |
| `roundtrip_real_l1a.py` | `<L1A.zarr> <GIPP_dir> [bands…] [--detector N] [--lines 2048]` |
| `demo_calibration.py` | `[GIPP_dir]` (GIPP if given, else synthetic ADFs) |
| `save_images.py` | `<L1A.zarr> <GIPP_dir> [band=B03] [--detector 1] [--lines 1024] [--out images]` |
| `derive_prnu_dark.py` | `--l1a <L1A/L1B.zarr> [--dark <dark.zarr>] [--bands …] [--detectors 1-12] [--out *.npz]` |

## 6. Outputs

- **L0 RAW product** — EOPF L0 Zarr (zarr v2): `measurements/d{DD}/b{BB}/band{N}` (uint16, 156 arrays),
  `quality/d{DD}/b{BB}/mask` (uint8), optional `conditions/anc_data/s{APID}/` ISP telemetry, and root
  STAC + `sensor_configuration` + `processing_history.adf_provenance` metadata. See the ICD (`icd.md`).
- **V&V tables** — per-band RMSE / FPN (`roundtrip_real_l1a.py`), calibration recovery (`demo_calibration.py`).
- **Images** — `save_images.py` writes, per stage, a bit-exact `.npy` and a min-max-normalised uint8 `.png`
  (raw L1A, forward-corrected L1B, round-trip residual ≈ black, synthetic calibration dark + diffuser).

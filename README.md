# Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`)

End-to-End performance Simulator for Sentinel-2 MSI — the **reverse / forward-instrument
conjugate** of the `msi-processor` (L0c→L2A). It degrades a  Sentinel-2 **L1A/L1B** product
back to a synthetic **L0 RAW** product (focal-plane DN, 12 detectors × 13 bands), for:

1. **RAW generation** — realistic L0 RAW when true Sentinel-2 L0 is unavailable.
2. **Round-trip V&V** — an original radiometric round-trip on a **L1A** with the **real
   operational GIPP**: raw `X` → forward correction (dark + equalization) → `Y` → reverse impress →
   `X′`. The residual `X′ − X` ≈ 0 (verified to ~1e-14 on S2 DN) proves the forward and reverse
   are exact inverses. Built from the public L1 ATBD — no external processor.

**Scope:** radiometric-only, 14-step chain (S1 radiance→DN … S15 ISP packets); input is
L1A/L1B, already in per-detector sensor geometry, so there is no geometry inversion (Issue #17).
An L1C entry + geometry reverse was considered and **cancelled** — with an L1A/L1B entry there is
no orthorectification to undo.

## Workflow

The generator is the **producer** in an end-to-end loop: it degrades a real L1A/L1B into a synthetic
**L0 RAW** product *and* derives a **calibration database** (EOPF ADFs) that the downstream
`msi-processor` (its L1PP blocks) consumes to invert the chain. Who produces/consumes what, the
input/output data, and where it is stored:

```mermaid
flowchart LR
    IN[("Real S2 L1A/L1B<br/>EOPF product (bucket)")]
    ADFsrc[("ADF sources<br/>GIPP - PSF - SRF")]
    subgraph GEN["s2_msi_raw_generator — Synthetic Raw Data Generator - PRODUCER"]
        direction TB
        REV["reverse chain S1-S15<br/>(reverse.py)"]
        C122["ccsds122 — CCSDS-122 lossless<br/>(DWT 9/7-M + bit-plane coder)"]
        PKT["isp packetize<br/>(SEQ_FIRST/CONT/LAST + CUC)"]
        CAL["calibration.py<br/>derive D, g, A"]
        ADFW["adf_writer.py"]
        REV --> C122 --> PKT
    end
    L0c[("canonical L0 — compressed ISPs<br/>(PSFD name S02MSIL0__…)")]
    GD["ground decode<br/>(reassemble + decompress,<br/>bit-exact — read_l0_isp_dn)"]
    L0oc[("open-container L0<br/>(…_OC)")]
    CALDB[("cal-DB - EOPF ADFs<br/>nuc / dark / radiometric / spectral<br/>+ noise (E2ES-side)")]
    subgraph PROC["msi-processor - CONSUMER"]
        direction TB
        L0D["l0_decode → L1A′"]
        RAD["radiometric unit"]
        TOA["toa unit"]
    end
    VAL["validation: L1A′ ≡ L1A<br/>(bit-identity, kept lines)"]
    L1[("L1B / L1C<br/>product")]
    IN --> REV
    ADFsrc --> REV
    ADFsrc --> CAL
    PKT -->|"stores"| L0c
    L0c --> GD --> L0oc
    CAL --> ADFW -->|"stores: EOPF zarr ADFs"| CALDB
    L0oc -->|"consumes"| L0D
    L0D --> RAD
    CALDB -->|"consumes: nuc, dark"| RAD
    CALDB -->|"consumes: radiometric"| TOA
    RAD --> TOA --> L1
    L0D -.-> VAL
    IN -.-> VAL
```

All chain products live under one **data-store** root (`l0/`, `caldb/`, `l1b/`, `quicklook/`;
real-data runs add `inputs/`, `l1a_prime/`, `report/`) with **EOPF PSFD §3** file names
(ICD-IF-NAME). The real-data end-to-end (bucket L1A → compressed-ISP L0 → `l0_decode` → L1A′ →
bit-identity validation + real-L0 structural comparison) is driven by
`scripts/run_pipeline.py` (see `docs/vv/real_e2e.md`).

The processor keeps calibration *internal* (a mode of its radiometric unit); the generator only
supplies the ADF — a single shared sensor-model ADF, one source of truth. Build it with
the pipeline's `build-caldb` phase (see Usage). Coefficients are **derived** (diffuser + dark), not the truth
ADF, so the round-trip is non-tautological.

## Result

**Real-data run (SDE, 2026-07-02):** the public-bucket **real L1A** packaged as a
CCSDS-122-compressed, real-space-packet **L0** (lossless ratio **3.66×**, 30 642 CCSDS
packets), ground-decoded bit-exactly and pushed through msi-processor `l0_decode` —
**L1A′ bit-identical to the original in 13/13 bands**; radiometric GIPP round-trip
RMSE ≈ 1e-14. Numbers & criteria: `docs/vv/real_e2e.md`; products: GitLab package registry
`s2-msi-e2e-real/0.3.0` (PSFD `.zarr.zip` names).

![Real L1A scene — B04/B03/B02, raw per-detector geometry (band misregistration is real; co-registration happens at L1B/L1C)](docs/_static/showcase/real_l1a_rgb.png)

### Single band, stage by stage — B04, real product

What the generator actually *does* to one band (B04, detector d07, 650 lines of the real
Sentinel-2 L1B granule): the ideal DN image, the same image after the instrument effects are
impressed (PSF re-blur → PRNU → noise → dark → onboard equalization, chain steps S6–S13),
and the generated 12-bit RAW L0. Zoomed crops (256×256 cloud edge, 2×) show the texture
changes; each panel is independently 2–98 % percentile-stretched, so what changes between
panels is the texture, not the display range.

| original — ideal DN (S1) | effects impressed (S6–S13) | RAW L0 DN (S14, uint16) |
|---|---|---|
| ![B04 original zoom](docs/_static/showcase/result_b04_original_zoom.png) | ![B04 effects zoom](docs/_static/showcase/result_b04_effects_zoom.png) | ![B04 raw zoom](docs/_static/showcase/result_b04_raw_zoom.png) |

Full 2552 × 650 strips: [original](docs/_static/showcase/result_b04_original.png) ·
[effects](docs/_static/showcase/result_b04_effects.png) ·
[raw](docs/_static/showcase/result_b04_raw.png) ·
[impressed-noise field](docs/_static/showcase/result_b04_delta.png) (the S13 noise alone —
its brightness follows the signal, σ=√(α²+β·DN)).

| Stage | DN min | DN max | mean | std | SNR (dB) | entropy (bits/px) |
|---|---|---|---|---|---|---|
| original — ideal DN (S1) | 1103.5 | 10486.9 | 1362.8 | 645.03 | 6.5 | 5.36 |
| effects impressed (S6–S13) | 1577.3 | 10880.9 | 1843.1 | 642.19 | 9.2 | 8.14 |
| RAW L0 DN (S14, uint16) | 1577.0 | 4095.0 | 1807.5 | 356.23 | 14.1 | 7.95 |

| Quality figure | Value |
|---|---|
| PSF re-blur RMSE vs ideal DN (S6) | 25.52 DN |
| impressed noise σ — measured vs model √(α²+β·DN) | 7.44 vs 7.34 DN (**+1.4 %**) |
| saturated px clipped by S14 (DN > 4095, bright cloud cores) | 1.53 % |
| quantization RMSE, unsaturated px (theory 1/√12 ≈ 0.29) | **0.29 DN** |
| full-chain radiance recovery (fwd(RAW) vs input), unsaturated px | RMSE 3.06 · **PSNR 45.1 dB** · bias +0.02 % |

Reading the numbers: the impressed noise matches the product noise model to 1.4 %; the
quantization error is exactly the uniform-quantizer theory value; recovering radiance from the
generated RAW returns the input to 45 dB with a +0.02 % bias — the only irreversible losses are
the modelled ones (noise, 12-bit clipping of the saturated cloud cores, quantization). The DN
pedestal (mean 1363 → 1843) is the re-applied dark signal + onboard equalization. Reproduce
locally (numpy+zarr only): `S2_E2ES_PHASES=figures S2_E2ES_L1B=<L1B.zarr[.zip]> python scripts/run_pipeline.py`. In this run
the PSF/SRF/noise model are real ESA data; the per-pixel dark/PRNU are the synthetic fallback
(set `S2_E2ES_GIPP_DIR=<dir>` for the operational-GIPP versions).

## Package

| Module | Responsibility |
|---|---|
| `s2_msi_raw_generator/sensor.py` | S2 band model — per-band gains/TDI/Lref/integration-time (datasheet) |
| `s2_msi_raw_generator/adf.py` | ADFs — **real** ESA PSF matrices (`data/psf/`) + SRF spectral + SNR@Lref noise; PRNU/dark from the operational GIPP (`BandADF.from_gipp`) |
| `s2_msi_raw_generator/gipp.py` | Original reader for the operational S2A **GIPP** (R2EQOG per-pixel dark+gains, R2DEPI, BLINDP, R2PARA, R2CRCO) |
| `s2_msi_raw_generator/forward_radiometric_atbd.py` | Public-ATBD forward radiometric model + exact inverse (round-trip V&V on the L1A) |
| `s2_msi_raw_generator/calibration.py` | S2 calibration sub-set — synthetic CSM sun-diffuser + dark → **derived** gain/dark coeffs (inverse-crime cure) |
| `s2_msi_raw_generator/reverse.py` | Reverse chain steps **S1–S14** + `reverse_full` / `reverse_mvp` |
| `s2_msi_raw_generator/isp.py` | **S15** — CCSDS ISP packet generation + SAD telemetry |
| `s2_msi_raw_generator/io.py` | Real EOPF L1A/L1B Zarr reader (`zarr`) |
| `s2_msi_raw_generator/l0product.py` | L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config + ISP) |
| `s2_msi_raw_generator/adf_writer.py` | **Calibration database** — writes derived coeffs as EOPF ADFs (`nuc`/`dark`/`radiometric`/`spectral`/`noise`) for the downstream L1PP processor |

## Documentation

Full **ECSS-E-ST-40C Rev.1** software documentation set under `docs/` (tailored for a single-CSC E2ES):

| DRD | File | Content |
|---|---|---|
| ATBD | `docs/atbd/atbd.md` | Algorithm theoretical basis — S1–S15 chain + Annex A datasheet (issued v1.0) |
| SRS | `docs/srs.md` | Requirements (REQ-FUNC/PERF/IF/QUAL) + verification methods |
| SDD | `docs/sdd/` | Software design — architecture, module design, REQ→code→test traceability |
| ICD | `docs/icd.md` | Interfaces — L1A/L1B + GIPP inputs, the L0 RAW output (ICD-IF-L0) |
| DPM | `docs/dpm/` | Data processing model — the reverse chain blocks + parameter/data list |
| V&V | `docs/vv/` | Verification & validation plan + report (201 tests at v0.3.0, RMSE ~1e-14; real-data E2E: vv/real_e2e) |
| SUM | `docs/sum.md` | User manual — install, usage, CLI |
| SRN | `docs/srn.md` | Release note |
| CIDL / SCF / SRF / SDP | `docs/{cidl,scf,srf,sdp}.md` | Config item list, config file, reuse file, development plan |

**CHANGELOG** — `CHANGELOG.md`. **License** — `LICENSE` (Apache-2.0). All instrument data is real
ESA-sourced (official PSF, SRF, product noise model, operational GIPP) — nothing fitted or synthetic;
implemented from public references only.

## Usage

```bash
pip install -e ".[read]"                 # numpy + zarr (eopf not required)
pytest                                   # full suite
```

Everything runs through the **single pipeline driver** `scripts/run_pipeline.py`
(phase-structured, idempotent; all product names PSFD §3). The CLI takes **only the mode** —
the store root is `$S2_DATA_STORE` (default `~/data-store`) and every knob is an
`S2_E2ES_*` environment variable:

```bash
# nominal mode (default): real S2 product → synthetic RAW downlink → <store>/l0/
# (fetch → package → ground-decode → l0_decode → validate → report)
python scripts/run_pipeline.py

# calibration mode: dark (DASC) + sun-diffuser (ABSR) campaign acquisitions packaged as
# REAL downlink L0 products (S02MSIDCA / S02MSISCA, compressed ISPs) + Option-Y cal-DB,
# everything → <store>/caldb/
python scripts/run_pipeline.py calibration

# shared data-store (ipf/data-store registry): pull / push the product DB
S2_E2ES_PHASES=fetch-store python scripts/run_pipeline.py
S2_E2ES_PHASES=publish-store S2_E2ES_PUBLISH_VERSION=<X.Y.Z> python scripts/run_pipeline.py

# on-demand phases
S2_E2ES_PHASES=build-caldb python scripts/run_pipeline.py                        # Option-Y cal-DB ADFs
S2_E2ES_PHASES=derive-adf S2_E2ES_L1A=<L1A.zarr> python scripts/run_pipeline.py  # real PRNU/dark → npz
S2_E2ES_PHASES=figures S2_E2ES_L1B=<L1B.zarr.zip> python scripts/run_pipeline.py # Result figures
```

The GIPP folder holds the `S2A_OPER_GIP_*.xml` files (R2EQOG ×13, R2DEPI, BLINDP, R2PARA,
R2CRCO); the L1A is an EOPF L1A Zarr (`measurements/DDnn/Bxx/l1a_raw_image`). Products and inputs
live in the shared [ipf/data-store](https://gitlab.eopf.copernicus.eu/ipf/data-store) registry —
pull a working copy with `S2_E2ES_PHASES=fetch-store`. Real-data tests run
when `S2_E2ES_GIPP_DIR` / `S2_E2ES_L1A` are set. The full variable reference is in
`docs/sum.md` §4. For interactive inspection of the generated products (band images, ISP
decode checks, cal-DB gains, reports) open `notebooks/inspect_products.ipynb` in JupyterLab.

## Status

**Complete — full S1–S15 reverse chain (incl. CCSDS-122 compressed ISPs), real-data E2E validated (L1A′ bit-identical 13/13); 201 tests, CI green.**

| Increment | Content |
|---|---|
| 0 | Scaffold, CI, ATBD + Annex A datasheet |
| 1 | MVP radiometric core (S1, S6, S7, S11–S14) + sensor model +S2 PSF / SRF ADFs |
| 2 | L0 RAW EOProduct assembly (156-array Zarr) |
| 3 | S3/S4/S5/S8/S9/S10 (framing, offset, binning, SWIR re-arrangement (reverse), crosstalk, defects) |
| 4 | S15 CCSDS ISP packet generation + SAD telemetry |
| 5 | Real per-band noise model (α,β) + official ATBD raw model (`X=A·G·L+D`), DQR dark |
| 6 | Real operational **GIPP** → per-pixel dark + relative response (`gipp.py`, `from_gipp`) |
| 7 | Original ATBD forward + **round-trip V&V on L1A** (RMSE ~1e-14) |
| 8 | S2 **calibration sub-set** — CSM diffuser + dark → derived coeffs (inverse-crime cure) |
| 9 | **L0 completion → L0→L1B E2E** — ESUN spectral ADF, real datation, STAC geometry/orbit + orbit-ephemeris, real SAD (AOCS/orbit/thermal), QAFlag/MSK_QUALIT quality + EOQC report, open-container handoff to `msi-processor` |

**All radiometric ADFs are real** (official ESA PSF, SRF, product noise model, operational GIPP) —
nothing fitted or synthetic. Runs end-to-end on S2 L1A/L1B with `numpy` + `zarr` only.
EOPF CPM 2.8.1, ECSS-E-ST-40C. The L1C-entry + geometry-reverse module is cancelled (not applicable
to an L1A/L1B entry).

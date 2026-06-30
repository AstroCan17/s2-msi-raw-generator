# Sentinel-2 MSI Reverse E2ES (`s2_e2es`)

End-to-End performance Simulator for Sentinel-2 MSI — the **reverse / forward-instrument
conjugate** of the `msi-processor` (L0c→L2A). It degrades a real Sentinel-2 **L1A/L1B** product
back to a synthetic **L0 RAW** product (focal-plane DN, 12 detectors × 13 bands), for:

1. **RAW generation** — realistic L0 RAW when true Sentinel-2 L0 is unavailable.
2. **Round-trip V&V** — real L1B → reverse → L0 → `msi-processor` forward → L1B′; the residual
   `L1B′ − L1B` measures the processor's restoration quality on real ESA data.

**Scope:** radiometric-only, 14-step chain (S1 radiance→DN … S15 ISP packets); input is
L1A/L1B, already in per-detector sensor geometry, so there is no geometry inversion (Issue #17).
An L1C entry + geometry reverse was considered and **cancelled** — with an L1A/L1B entry there is
no orthorectification to undo.

## Package

| Module | Responsibility |
|---|---|
| `s2_e2es/sensor.py` | S2 band model — real per-band gains/TDI/Lref/integration-time (datasheet) |
| `s2_e2es/adf.py` | ADFs — **real** ESA PSF matrices (`data/psf/`) + SRF spectral + SNR@Lref noise; PRNU/dark from real products (`scripts/derive_prnu_dark.py`) |
| `s2_e2es/reverse.py` | Reverse chain steps **S1–S14** + `reverse_full` / `reverse_mvp` |
| `s2_e2es/isp.py` | **S15** — CCSDS ISP packet generation + SAD telemetry |
| `s2_e2es/io.py` | Real EOPF L1A/L1B Zarr reader (`zarr`) |
| `s2_e2es/l0product.py` | L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config + ISP) |

## Documentation

- **ATBD** — `docs/atbd/atbd.md` (algorithm theoretical basis: the 14-step reverse chain
  and Annex A — the sourced Sentinel-2 MSI datasheet).

## Usage

```bash
pip install -e ".[dev]"
pytest                                   # 29 tests
python scripts/demo_reverse_real.py      # reverse one band of a real L1B granule
python scripts/demo_build_l0.py          # real L1B → assembled synthetic L0 RAW product
```

## Status

**v1 complete — full 14-step reverse chain implemented (Increments 0–4), CI green.**

| Increment | Content |
|---|---|
| 0 | Scaffold, CI, ATBD + Annex A datasheet |
| 1 | MVP radiometric core (S1, S6, S7, S11–S14) + sensor model + real ESA PSF / SRF ADFs |
| 2 | L0 RAW EOProduct assembly (156-array Zarr) |
| 3 | S3/S4/S5/S8/S9/S10 (framing, offset, binning, SWIR re-stagger, crosstalk, defects) |
| 4 | S15 CCSDS ISP packet generation + SAD telemetry |

Runs end-to-end on real ESA L1B. EOPF CPM 2.8.1, ECSS-E-ST-40C. **Next:** independent round-trip
V&V against the pinned `msi-processor` wheel. (The L1C-entry + geometry-reverse module is cancelled —
not applicable to an L1A/L1B entry.)

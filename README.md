# Sentinel-2 MSI Reverse E2ES (`s2_e2es`)

End-to-End performance Simulator for Sentinel-2 MSI — the **reverse / forward-instrument
conjugate** of the `msi-processor` (L0c→L2A). It degrades a real Sentinel-2 **L1A/L1B** product
back to a synthetic **L0 RAW** product (focal-plane DN, 12 detectors × 13 bands), for:

1. **RAW generation** — realistic L0 RAW when true Sentinel-2 L0 is unavailable.
2. **Round-trip V&V** — real L1B → reverse → L0 → `msi-processor` forward → L1B′; the residual
   `L1B′ − L1B` measures the processor's restoration quality on real ESA data.

**Scope (v1):** radiometric-only, 14-step chain (S1 radiance→DN … S15 ISP packets); input is
L1A/L1B in per-detector sensor geometry, so no geometry inversion (Issue #17). L1C entry +
geometry reverse is a future module.

## Documentation

- **ATBD** — `docs/atbd/atbd.md` (algorithm theoretical basis: the 14-step reverse chain
  and Annex A — the sourced Sentinel-2 MSI datasheet).

## Status

Increment 0 (preconditions / doc-first). EOPF CPM 2.8.1. ECSS-E-ST-40C.

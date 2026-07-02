# `data/output/` — the E2E data store

`scripts/run_e2e_l0_to_l1b.py` treats one directory as the run's central **data store**; this folder is
its default. Every product of the chain lands under this single root:

| Sub-folder | Content | Git |
|---|---|---|
| `l0/` | L0 RAW **open-container** product (`L0c_opencontainer.zarr`) — decoded detector frames + `quality/l0_flags` + `conditions/*` that `msi-processor` ingests | **ignored** (large satellite-image product) |
| `caldb/` | Calibration database — `nuc` / `dark` / `radiometric` / `spectral` / `noise` `.zarr` + `PROVENANCE.md` | ignored (`*.zarr/`; regenerable) |
| `l1b/` | L1B **TOA-reflectance** product (`L1B_TOA.zarr`) written back by the processor step (SDE-only) | ignored (`*.zarr/`) |
| `quicklook/` | Small PNG previews of the products (`l0_rgb.png`, `l1b_rgb.png`) | **committed** (showcase) |

`msi-processor` consumes the `l0/` + `caldb/` products directly from this store — pass explicit paths
(or a dedicated store root such as `~/data-store` on the SDE) to the E2E driver. The `.zarr` products
are gitignored (large / regenerable); the small quicklook PNGs are committed for the README and the
documentation site.

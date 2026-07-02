# `data/output/` — generator products

Written by `scripts/run_e2e_l0_to_l1b.py` (and `scripts/build_cal_db.py`):

| Sub-folder | Content | Git |
|---|---|---|
| `l0/` | L0 RAW **open-container** product (`L0c_opencontainer.zarr`) — decoded detector frames + `quality/l0_flags` + `conditions/*` that `msi-processor` ingests | **ignored** (large satellite-image product) |
| `caldb/` | Calibration database — `nuc` / `dark` / `radiometric` / `spectral` / `noise` `.zarr` + `PROVENANCE.md` | ignored (`*.zarr/`; regenerable) |
| `quicklook/` | Small PNG previews of the products | **committed** (showcase) |

`msi-processor` reads this folder as its input, via a symlink in its own `data/input/`. The `.zarr`
products are gitignored (large / regenerable); the small quicklook PNGs are committed for the README and
the documentation site.

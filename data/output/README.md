# `data/output/` — the E2E data store

`scripts/run_pipeline.py` treats one directory as the run's central **data store**; this folder is
its default for the synthetic chain (`--synthetic`). Every product of the chain lands under this
single root, named per the EOPF PSFD §3 convention (`s2_msi_raw_generator.naming`):

| Sub-folder | Content | Git |
|---|---|---|
| `l0/` | L0 RAW **open-container** product (`S02MSIL0__…_OC.zarr`) — decoded detector frames + `quality/l0_flags` + `conditions/*` that `msi-processor` ingests | **tracked** |
| `caldb/` | Calibration database — `nuc` / `dark` / `radiometric` / `spectral` / `noise` `.zarr` + `PROVENANCE.md` | **tracked** |
| `l1b/` | L1B **TOA-reflectance** product (`S02MSIL1B_….zarr`) written back by the processor step (eopf env: SDE or the manual `e2e-l1b` CI job) | **tracked** |
| `quicklook/` | Small PNG previews of the products (`l0_rgb.png`, `l1b_rgb.png`) | **tracked** |
| `figures/` / `report/` | The `figures` phase's stage images and the per-phase JSON reports | **tracked** |

`msi-processor` consumes the `l0/` + `caldb/` products directly from this store — pass explicit paths
(or a dedicated store root such as `~/data-store` on the SDE) to the pipeline. The whole `data/` E2E
store is tracked in git and syncs with the repository; mind the push size before dropping large real
inputs into `data/input/` (see its README). The committed Result figures live in
`docs/_static/showcase/`.

# `data/` — local working store (not tracked)

Products and inputs live in the shared **[ipf/data-store](https://gitlab.eopf.copernicus.eu/ipf/data-store)**
(registry = DB). Pull a working copy into any directory:

```bash
python scripts/run_pipeline.py data/store --phases fetch-store     # pull (sha256-verified)
python scripts/run_pipeline.py data/store --synthetic              # or produce it yourself
python scripts/run_pipeline.py data/store --phases publish-store --publish-version <X.Y.Z>   # push
```

Everything under `data/` is gitignored.

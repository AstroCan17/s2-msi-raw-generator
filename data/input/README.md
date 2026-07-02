# `data/input/` — E2E inputs

Real reference products the reverse chain consumes: Sentinel-2 **L1A/L1B** EOPF products and the
operational **GIPP** (`S2A_OPER_GIP_*`). These are large and satellite-specific (**S2A**), so they are
**gitignored** — only this file and `.gitkeep` are tracked.

The self-contained E2E driver `scripts/run_e2e_l0_to_l1b.py` synthesises its own radiance internally, so
no external input is required to produce a demo product.

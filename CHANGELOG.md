# Changelog

All notable changes to the Sentinel-2 MSI reverse E2ES (`s2_msi_raw_generator`).

## [Unreleased]

### Added
- **Calibration mode (the `calibration` positional, REQ-FUNC-048)** — synthesizes the calibration
  campaign (dark / CSM-closed + Lambertian sun-diffuser) and packages each acquisition as a
  **real downlink L0 product**: CCSDS-122 compressed ISPs under the PSFD §3 calibration type
  codes `S02MSIDCA` (DASC) / `S02MSISCA` (ABSR), with the new `msi:datatake_type` and
  `acquisition_configuration.operation_mode` metadata (nominal products now stamp
  `NOBS`/`INS-NOBS`); the Option-Y cal-DB is derived from the same frames
  (`caldb.derive_from_acquisitions`).

### Removed
- **The `--synthetic` flat-field demo chain** (`build-l0-synth`/`l0-to-l1b` phases,
  `build_inputs`/`run_processor`/`write_l1b`, the `e2e-l1b` CI job, `test_e2e_l1b`) — the
  consumer chain lives in msi-processor's own pipeline; the OC handoff contract is now
  asserted by `test_l0_handoff`. The interim calibration-acquisition ADFs
  (`flatfield.zarr`, `dark.zarr:/frame`) are superseded by the calibration L0 products
  (DJF DEC-13).
- **Calibration acquisitions in the cal-DB** — `build-caldb` now also writes the raw
  calibration *acquisitions* behind the derived coefficients: `flatfield.zarr`
  (per-band diffuser frames) and `dark.zarr:/frame/<band>` (dark frames) — exactly the
  mandatory ADFs of the consumer's `radiometric` **calibration mode**, closing the
  producer-acquires / consumer-derives loop. `naming.TYPE_CODES` gains `S02MSIL1C` and
  `S02MSIL2A` for the consumer pipeline's product names.

### Changed
- **Mode-only CLI, environment-driven configuration** — `run_pipeline.py` now takes just
  the mode (`nominal` default | `calibration`); the store root comes from `$S2_DATA_STORE`
  (default `~/data-store`) and every tuning knob is an `S2_E2ES_*` variable
  (`PHASES`/`LINES`/`BANDS`/`SEED`/`NDET`/`CAL_LINES`/`L1A`/`DARK`/`GIPP_DIR`/`L1B`/
  `PUBLISH_NAME`/`PUBLISH_VERSION`/`PUBLISH_LAYER`). The 28 CLI flags are removed; the
  never-overridden knobs (`--detectors`, `--band-groups`, `--max-payload`, `--jobs`,
  `--store-decoded`, the nine `--fig-*` flags, `--publish-source`) are deleted outright
  with their defaults hardcoded (publish provenance now stamps `CI_JOB_URL`
  automatically). CI jobs configure via `variables:` instead of flags.
- **Calibration products land under `<store>/caldb/`** — the campaign L0s
  (`S02MSIDCA`/`S02MSISCA`) move from `l0/` next to the cal-DB ADFs, so `l0/` holds only
  nominal products. **Breaking** for consumers that resolved cal products under `l0/`;
  msi-processor's `cal-decode` is updated in lockstep (caldb-first with an `l0/` fallback
  for already-published legacy store packages).
- **Ground decode delegated to the consumer** — the pipeline's `ground-decode` phase now
  uses msi-processor's `ground_decode` (the operational, L1A-side decompression) when
  installed, and cross-checks it bit-exactly against this repo's `read_l0_isp_dn`
  (retained as the E2ES reference decoder — DJF DEC-12). Reports gain
  `decoder`/`decoder_cross_check` fields.
- **Shared data-store** — products and inputs move to the `ipf/data-store` project's
  generic package registry (registry = versioned DB, local store = working copy). New
  pipeline phases `fetch-store` (anonymous pull, sha256-verified manifest) and
  `publish-store` (job-token/`glab`-token push + `manifest/latest` refresh); the
  `publish-e2e-real` CI job becomes `publish-datastore` (parameterised PKG/VER/LAYER).
  The repo's `data/` tracking is removed again in favour of the store (`data/` is
  gitignored; pull with the `fetch-store` phase).
- **Single pipeline driver** — the ten `scripts/` entry points are consolidated into one
  phase-structured `scripts/run_pipeline.py` (real chain = the former `run_e2e_real_l1a.py`
  phases; `--synthetic` = the former `run_e2e_l0_to_l1b.py` chain; on-demand phases
  `build-caldb` / `derive-adf` / `figures` absorb `build_cal_db.py` (now
  `s2_msi_raw_generator.caldb`), `derive_prnu_dark.py` and `result_band_stages.py`; the
  demo/roundtrip/save-images scripts are deleted — `roundtrip_real_l1a.py` was already
  duplicated as the `radiometric-vv` phase). **Every product name now comes from
  `naming.py` (PSFD §3)**: the synthetic open container is `S02MSIL0__…_OC.zarr`
  (was `L0c_opencontainer.zarr`) and the L1B is `S02MSIL1B_….zarr` (was `L1B_TOA.zarr`).
- **`data/` E2E store tracked in git** — the `data/input` + `data/output` gitignore rules
  (and the global `*.zarr/` ignores) are removed; the synthetic products (PSFD-named OC L0,
  cal-DB, quicklooks, phase reports) are committed and sync with the repository.

### Added
- **Single-band stage-by-stage result figures** — new `scripts/result_band_stages.py`
  (numpy+zarr only): renders, for one band/detector of the real L1B, the ideal-DN image, the
  instrument-effects-impressed image (S6–S13) and the generated RAW L0 (S14), with zoom crops,
  the impressed-noise field and a quality table (noise σ vs model +1.4 %, quantization RMSE
  0.29 DN = 1/√12, full-chain radiance recovery PSNR 45.1 dB). Figures committed under
  `docs/_static/showcase/` and shown in the README §Result and the docs landing page; the
  synthetic flat-field demo quicklooks were removed from README/git (still produced by the
  E2E driver, now gitignored).

- **Complete ECSS document set** — nine standalone documents closing the tailored DRL: SSS, IRD, DJF
  (11 decision records), risk register, SPA plan (ECSS-Q-ST-80C), SRevP (with the held-review record),
  SUITP, SUITR, and the QR report for the v0.3.0 baseline. The SDP tailoring section is now a full
  DRL disposition table (every ECSS-E-ST-40C Rev.1 / Q-ST-80C DRD → standalone document or recorded
  tailoring); new "Management & assurance" section on the docs landing page.

### Changed
- **Docs landing page** — the real-data E2E showcase (quicklooks + headline numbers + source
  repository link) moved onto the documentation front page (`docs/index.md`); the separate
  `showcase` page and its synthetic-demo section were removed (superseded by the real-data
  run, REQ-FUNC-093 — the synthetic L0→L1B chain itself is unchanged and stays documented in
  the V&V plan / SUM / `e2e-l1b` CI job).

## [0.3.0] — 2026-07-02

Real-data E2E release: the reverse E2ES now packages a **real bucket L1A** into a
**CCSDS-122-lossless-compressed, real-CCSDS-space-packet L0**, ground-decodes it bit-exactly
and proves **L1A′ ≡ L1A (13/13 bands bit-identical)** through msi-processor `l0_decode`, with
the radiometric GIPP round-trip at RMSE ≈ 1e-14, EOPF **PSFD §3 product naming**
(ICD-IF-NAME) and published products (`s2-msi-e2e-real/0.3.0` generic packages) + validation
report (`docs/vv/real_e2e.md`). Authoritative full-frame run on the SDE, 2026-07-02: overall
lossless compression **3.66×** (637→174 MB, 16-bit base), 30 642 packets, EOQC OK.

### Added
- **Real-L1A E2E driver + PSFD naming + bucket fetch** — `scripts/run_e2e_real_l1a.py`
  (phase-structured, idempotent: fetch-l1a/fetch-l0/preflight/package/ground-decode/l0-decode/
  validate/radiometric-vv/scan-l0/quicklook/report; REQ-FUNC-093): packages the real bucket
  L1A into the compressed-ISP canonical L0 + open-container form under **EOPF PSFD §3 names**
  (new `naming.py`, ICD-IF-NAME — the ECSS-M-ST-40C identification coding system), runs
  msi-processor `l0_decode` to L1A′ and validates bit-identity, line-loss accounting, the GIPP
  radiometric round-trip, EOQC, and a **structural scan of a real PSD L0 SAFE** (packet-tiling
  criterion on its ISP `.bin` files). New stdlib-only `s3fetch.py` (anonymous S3 listing +
  verified parallel GET). New manual CI job **`e2e-real-l1a`** (windowed, artifacts:
  report+quicklooks). Docs: ICD-IF-NAME, SRS REQ-FUNC-091/092/093, CIDL rows,
  `docs/vv/real_e2e.md`, README/DPM diagrams updated to the real-data flow.
- **Compressed ISP payloads + ground decode (real downlink shape)** — the canonical L0's
  `with_isp` branch now CCSDS-122-compresses each band and carries it as **real CCSDS space
  packets**: `isp.packetize_stream` (segment groups = codec segments = 8 image lines,
  `SEQ_FIRST/CONT/LAST` grammar, continuous 14-bit counter, per-group CUC epoch),
  `isp.iter_packets` / `isp.reassemble_segments` (strict grammar+continuity), stored as
  `measurements/d{DD}/b{BB}/{isp, isp_offsets, packet_data_length}` (+ compression attrs;
  achieved per-band ratios replace the static `compression_rate` metadata). New
  `l0product.read_l0_isp_dn` = the ground (L1A-side) decompression — bit-exact. New
  `write_l0_product(..., store_decoded=False)` stores **ISPs only**, mirroring the real S2 L0.
  `io.read_l1a_raw` gains a `dtype` kwarg (uint16 reads without the float64 spike). (ICD-IF-L0
  updated; REQ-FUNC-092)

### Changed
- **Removed the per-line `isp_header` array** from the canonical L0 (superseded by the packet
  stream; repo-internal schema change, msi-processor consumes the open-container form).

### Fixed
- `reverse_to_l0_frames` band reseeding now uses `zlib.crc32` instead of salted `hash()` —
  DN streams are reproducible across processes (REQ-QUAL-004; synthetic demo outputs change once).
- **CCSDS 122.0-B lossless image compression** (`s2_msi_raw_generator/ccsds122.py`, pure numpy) —
  the documented alternative to Sentinel-2's proprietary onboard MRCPB wavelet scheme: 3-level
  integer DWT 9/7-M, 8×8 block/family + 16-block gaggle structure, self-describing segment
  headers, DC/BitDepthAC DPCM + per-gaggle Rice coding; §4.5 AC stages with raw-packed planes
  (documented divergence from §4.5.3 VLC word mapping — see ICD-IF-C122). Encoder **and**
  decoder; `compress_frame`∘`decompress_frame` is bit-exact (14 unit tests + env-gated real-L1A
  window). Full 21384×2592 band ≈ 19 s each way. Groundwork for compressed ISP payloads
  (REQ-FUNC-092; ATBD §5.S15 rewritten to the real two-step onboard chain).
- **Showcase (real E2E products) + `e2e-l1b` CI job** — README + docs `showcase` page with the
  committed L0 DN / L1B reflectance quicklooks from a real chain run; new **manual CI job**
  `e2e-l1b` builds the full `eopf==2.8.1` + `msi_processor` environment (job-token clone of
  `ipf/msi-processor`), runs the L0→L1B chain **and** the E2E pytest suite, and uploads the L1B
  product + quicklooks as artifacts — the real E2E is now CI-reproducible, not SDE-only.
- **L1B persistence + L1B quicklook (single data-store root)** — `scripts/run_e2e_l0_to_l1b.py` now
  treats its `work_dir` as the run's central **data store** (`l0/`, `caldb/`, `l1b/`, `quicklook/`
  under one root; default `data/output/`, e.g. `~/data-store` on the SDE). New `write_l1b` persists
  the L1B `EOProduct` via eopf's native `EOZarrStore` (`<store>/l1b/L1B_TOA.zarr`, SDE-only) and the
  driver renders an **L1B reflectance quicklook** (`quicklook/l1b_rgb.png`) next to the L0 one.
  Quicklook writer gains unit tests (uint16 DN, float reflectance + NaN, flat band, upscale).
- **`data/` E2E folders + quicklook** — `data/input/` (reference L1A/GIPP; gitignored) and
  `data/output/{l0,caldb,quicklook}/`; `scripts/run_e2e_l0_to_l1b.py` writes products there by default.
  New dependency-free `s2_msi_raw_generator/quicklook.py` (stdlib-only PNG writer) renders an RGB preview.
  The large `.zarr` products are gitignored; the small **quicklook PNGs** are committed (README/site showcase).
- **zarr v2/v3 write compatibility** (`s2_msi_raw_generator/_zarrio.py`) — the L0 + cal-DB writers now run under
  **both** zarr 3 (local/CI) and **zarr 2.18** (the `eopf==2.8.1` SDE env; eopf pins zarr <3). Products stay in
  the zarr **v2** on-disk format either way. Consequence: the full **L0→L1B E2E runs in a single venv** alongside
  `msi-processor` (no separate zarr-3 venv). `scripts/run_e2e_l0_to_l1b.py::run_processor` rewritten to the real
  eopf/msi_processor API — **validated on the SDE**: generator L0 + cal-DB → `l0_decode → radiometric → enhancement
  → toa` → real **L1B TOA reflectance** for all bands (VNIR ~0.18, NIR ~0.27, SWIR ~0.05).
- **Open-container L0 handoff + L0→L1B E2E** — `l0product.write_l0_opencontainer` writes the *decoded* L0
  (`measurements/detector/<band>` uint16 + `quality/l0_flags/<band>` QAFlag + per-line `conditions/*`) that
  `msi-processor`'s `l0_decode` ingests directly; `scripts/run_e2e_l0_to_l1b.py` drives the full
  L0→`radiometric`→`toa`(reflectance) chain (SDE, needs `eopf`+`msi_processor`). CI asserts the schema +
  the `nuc.gain` ↔ detector-width invariant (`tests/test_e2e_l1b.py`). (REQ-FUNC-042)
- **Real Satellite Ancillary Data** (`s2_msi_raw_generator/sad.py`) — replaces the placeholder all-zero SAD
  payload with real telemetry: a synthesised Sentinel-2 sun-synchronous orbit (ECEF position/velocity), a
  nadir/velocity-aligned attitude quaternion and a thermal cycle (`synth_orbit_attitude`), packed as real
  CCSDS ISP (`pack_sad_isp`, big-endian float64 [q0..q3,x,y,z,vx,vy,vz,T]) into `conditions/anc_data/s{APID}/isp`;
  plus a real CCSDS outer-framing decoder (`scan_ccsds_packets`/`decode_sadata_framing`) for real SADATA/HKTM
  tars. L0 metadata gains `orbit_ephemeris_start/stop` (TAI/UTC/UT1 + ECEF pos/vel). numpy-only, no network.
  (REQ-FUNC-036/037)
- **Quality-flag taxonomy** (`s2_msi_raw_generator/quality.py`) — L0 quality expressed as msi-processor
  `QAFlag`-compatible seeds (NO_DATA/LOST_PACKET/SATURATED/DEFECTIVE, same bit values for monotone-OR
  interop); the canonical L0 mask is now the Sentinel-2 `MSK_QUALIT` 8-bit-plane layout
  (`l0_flags`/`to_msk_qualit`/`from_s10_qa`). (REQ-FUNC-040)
- **EOQC quality report** (`s2_msi_raw_generator/quality_report.py`) — EOPF EOQC-style per-product report
  (overall OK/KO + per-check list: STAC content/geometry, Sensing_Time, ISO_Time, Datation_Sync,
  Time_Correlation, orbit bounds, structure), embedded in the L0 `quality` group and writable as standalone
  JSON. ECSS-Q-ST-20C. (REQ-FUNC-041)
- **Real line datation** (`s2_msi_raw_generator/datation.py`) — `Datation` (ADF_DATAT model) stamps each ISP
  line with a real GPS/OBT time from an acquisition epoch (was `t0=0`); `isp.parse_cuc_time`; per-band
  `band_time_stamp` + acquisition epoch in the L0 metadata. (REQ-FUNC-035)
- **L0 STAC geometry & orbit metadata** — `build_root_metadata` now writes the footprint (`bbox` + closed
  `geometry`), `sat:relative_orbit`/`sat:absolute_orbit`/`sat:orbit_state`, `constellation`, `product:type`,
  `processing:*`, `eopf:datastrip_id`, and a **real datetime span** (start/end from datation) with S2A
  footprint/orbit defaults (overridable via `footprint`/`orbit`). Fixes the dangling REQ-FUNC-054 ref. (REQ-FUNC-038)
- **ESUN spectral ADF** (`spectral.zarr`) — the cal-DB writer now emits per-band ESUN (extraterrestrial solar
  irradiance, Thuillier 2003; S2A/S2B — ATBD §A.3) as `/esun/<band>` float32 scalars, the exact schema the
  `msi-processor` `toa` unit consumes for TOA reflectance. `sensor.ESUN` / `sensor.esun()`,
  `adf_writer.write_calibration_db(..., include_spectral=True)`, `scripts/build_cal_db.py`. (REQ-FUNC-039)
- **Calibration sub-set** (`s2_msi_raw_generator/calibration.py`) — the S2 two-reference radiometric calibration:
  synthetic CSM sun-diffuser + dark acquisitions → derive dark `D`, relative response `g`, absolute
  coefficient `A` (public L1 ATBD §4.1.1.2.2). A processor uses the *derived* coefficients, not the
  truth — the inverse-crime cure. Verified on the GIPP (dark <0.05 DN, `g` corr >0.99, `A≈cal_gain`).
- **Real operational GIPP reader** (`s2_msi_raw_generator/gipp.py`) — original `xml.etree` parser of the S2A
  GIPP: R2EQOG (per-pixel dark `COEFF_D` + cubic/bilinear relative-response gains), R2DEPI, BLINDP,
  R2PARA, R2CRCO. `BandADF.from_gipp()` builds per-pixel dark + PRNU ADFs.
- **Original ATBD forward + round-trip V&V** (`s2_msi_raw_generator/forward_radiometric_atbd.py`) — forward
  radiometric correction and its exact inverse from the public L1 ATBD; `scripts/roundtrip_real_l1a.py`
  validates forward∘reverse to ~1e-14 RMSE on a **L1A** with the GIPP.
- L1A raw reader (`io.read_l1a_raw`), image export (`scripts/save_images.py`), demos
  (`demo_calibration.py`), `LICENSE` (Apache-2.0), this changelog.

### Changed
- Radiometric model adopts the official L1 ATBD raw equation `X = A·G·L + D` in true 12-bit DN.
- Per-band noise model uses the product `noise_model` (α, β; S2-RUT `σ=√(α²+β·DN)`).
- Dark/PRNU now per-pixel from the GIPP (was DQR-summary / seeded).
- L1C-entry + geometry-reverse module **cancelled** (not applicable to an L1A/L1B entry).

## [0.3.0] — Increments 0–4

- Full S1–S15 reverse chain (radiance→DN, PSF re-blur, PRNU, SWIR re-arrangement (reverse), defects, dark, onboard
  equalization, noise, 12-bit quantize, CCSDS ISP packets).
- L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config).
- S2 PSF matrices (SentiWiki) + SRF spectral characterisation.
- Sensor model with per-band gains/TDI/line-period from EOPF products.
- GitLab CI (unit tests), ATBD + Annex A datasheet.

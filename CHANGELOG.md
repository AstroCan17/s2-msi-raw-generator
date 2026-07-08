# Changelog

All notable changes to the Sentinel-2 MSI reverse E2ES (`s2_msi_raw_generator`).

`s2_msi_raw_generator` runs a real Sentinel-2B **L1B** backwards through the exact inverse of the
operational L0→L1B radiometric chain (invert offset, relative-response/PRNU, dark, un-bin, SWIR
re-stage, defective, crosstalk, on-board-eq) to reconstruct **L1A → L0plus (CCSDS-122 ISP) → L0**.
MTF-deconvolution is OFF, so PSF and noise are not re-applied. Success = the reconstructed L0 vs the
real ESA L0 `img` (≤~4 DN on the 10/20 m bands); the L0plus codec round-trip `decode(L0plus)==L1A`
is bit-exact (supporting check).

## [Unreleased]

### Added
- **Data-store inventory and consistency report** — new `s2_msi_raw_generator.inventory`
  module plus the on-demand `inventory` pipeline phase writes `<store>/INVENTORY.md` and
  `report/inventory.json` from metadata-only scans of Zarr directories/zip archives, classifying
  generated products, public L0/L0P references, cal-DB entries, reports, staging zips and broken
  links while flagging cross-scene comparisons and name↔STAC identity mismatches.
- **Public-L0 same-scene bridge** — new `s2_msi_raw_generator.import_l0` module and
  `import-l0` phase convert a public distribution L0 detector (`measurements/dNN/bNN/img`) into
  the PDI-style L1A layout consumed by the pipeline, preserving real STAC orbit/platform identity
  and recording `import_provenance` plus per-band CRCs for A0 bit-exact copy checks.
- **`notebooks/compare_real_l0.ipynb`** — the ladder's headline validation: the
  ladder-reconstructed L0 next to the real ESA L0 `img` (`inputs/public-data/level-0/
  S02MSIL0__*.zarr.zip`, `measurements/dNN/bNN/img`), reporting the 10/20 m-band agreement
  (≤~4 DN) with overlaid DN histograms (μ/σ/p2–p98), an all-band mean±σ summary, a
  column-profile FPN/PRNU signature check, and an inventory of the `S02MSIL0P_*` annotation
  companions (geometry/quality, no image DN).
- **`notebooks/pipeline_walkthrough.ipynb`** — the reverse-ladder walkthrough with an image
  per rung: real L1B window → invert offset → relative-response/PRNU → dark → un-bin →
  SWIR re-stage → defective → crosstalk → on-board-eq → L1A/L0plus/L0, with
  MTF-deconvolution and noise re-application explicitly OFF (PSF and noise are not
  re-applied). Keeps the CCSDS-122 DWT subbands + segment/packet statistics (S15) and the
  bit-exact ground-decode, and compares the same rungs against the store's persisted phase
  outputs. Both notebooks now self-install the package into the kernel env on first run
  (one-time cell + kernel restart).
- **`notebooks/inspect_products.ipynb`** — interactive data-store explorer: product
  inventory + zarr tree, STAC/compression metadata, stored-DN band images, ISP
  ground-decode verification, calibration campaign + NUC gain plots, quicklooks and
  phase-report summaries. Runs in the plain generator env (numpy + zarr + matplotlib).
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

### Internal
- **Shared metadata helpers (`s2_msi_raw_generator.metadata`)** — the doubled `stac_discovery`
  flattening, `"null"`/`Z`-tolerant ISO parsing, integer coercion and data-take-id absolute-orbit
  recovery that `io`, `naming`, `inventory` and `import_l0` each re-implemented are consolidated into
  one stdlib-only module. Callers keep their own field-preference order (`datetime` vs
  `start_datetime`), so scan/report output is unchanged.
- **Process-pool and zip helpers** — the spawn-context `ProcessPoolExecutor` fan-out (canonical L0
  packaging and `ground-decode`) is unified in `s2_msi_raw_generator._parallel.run_in_process_pool`,
  and the three `_zip_dir` copies (driver + tests) become `s2_msi_raw_generator._fsutil.zip_dir` with
  a `base` selector for the publish (`parent`) vs Zarr-root (`self`) archive layouts.
- **Dead code removed** — unused `io.read_platform` and `l0product.frames_to_strip`, plus the
  never-exercised `--band-groups > 1` subdivision branch in `l0-decode`.

### Changed
- **Orbit identity threading** — pipeline preflight now records platform/orbit acquisition
  context and passes it into both canonical and open-container L0 writers, so PSFD names and STAC
  `sat:*` fields stay aligned. Placeholder products now use relative orbit 45 with absolute orbit
  0 (`A000000`) instead of mixing the A045 file-name default with an unrelated real orbit.
- **Multi-core data generation (`S2_E2ES_JOBS`, default: all cores)** — the per-band CPU
  work fans out to a process pool: CCSDS-122 compression + ISP packetization + SAD in
  `write_l0_product` (package / cal-package) and the decode-and-verify step of
  `ground-decode` (`l0product.decode_verify_band`). Processes, not threads — the codec's
  entropy coder is pure-Python and GIL-bound. zarr writes stay in-process and the products
  are bit-identical to a serial run (`tests/test_parallel_write.py`); the S3 fetch thread
  pool reuses the same setting.
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
  phase-structured `scripts/run_pipeline.py` (the reverse-ladder phases from the former
  `run_e2e_real_l1a.py`; on-demand phases `build-caldb` / `derive-adf` / `figures` absorb
  `build_cal_db.py` (now `s2_msi_raw_generator.caldb`) and `derive_prnu_dark.py`; the
  demo/save-images scripts are deleted). **Every product name now comes from
  `naming.py` (PSFD §3, from `naming.py`)**: the reconstructed open container is
  `S02MSIL0__…_OC.zarr` (was `L0c_opencontainer.zarr`).

### Added
- **Complete ECSS document set** — nine standalone documents closing the tailored DRL: SSS, IRD, DJF
  (11 decision records), risk register, SPA plan (ECSS-Q-ST-80C), SRevP (with the held-review record),
  SUITP, SUITR, and the QR report for the v0.3.0 baseline. The SDP tailoring section is now a full
  DRL disposition table (every ECSS-E-ST-40C Rev.1 / Q-ST-80C DRD → standalone document or recorded
  tailoring); new "Management & assurance" section on the docs landing page.

### Changed
- **Docs landing page** — the documentation front page (`docs/index.md`) now leads with the
  reverse ladder: a real Sentinel-2B L1B run backwards through the exact inverse of the
  operational L0→L1B radiometric chain to reconstruct L1A/L0plus/L0, validated against the
  real ESA L0 `img` (≤~4 DN on the 10/20 m bands). The separate `showcase` page was removed.
  REQ-FUNC-093 is rescoped to the real-data reconstruction/validation driver.

## [0.3.0] — 2026-07-02

Real-data E2E release: delivers the machinery the reverse ladder reuses to run a real
Sentinel-2B L1B backwards to L1A → L0plus → L0 — the **CCSDS-122 lossless codec**, real
**CCSDS space-packet ISPs**, EOPF **PSFD §3 product naming** (ICD-IF-NAME), and the **L0plus
codec round-trip** (`decode(L0plus)==L1A`, bit-exact) — plus **3.66×** lossless compression
(637→174 MB, 16-bit base), 30 642 packets and EOQC OK. Published products
(`e2e-real/0.3.0` generic packages) + validation report (`docs/vv/real_e2e.md`).

### Added
- **Real-L1B reverse-ladder driver + PSFD naming + bucket fetch** — `scripts/run_e2e_real_l1a.py`
  (phase-structured, idempotent: fetch-l1a/fetch-l0/preflight/package/ground-decode/l0-decode/
  validate/scan-l0/quicklook/report; REQ-FUNC-093): reconstructs the real bucket L1A into the
  compressed-ISP canonical L0 + open-container form under **EOPF PSFD §3 names** (new
  `naming.py`, ICD-IF-NAME — the ECSS-M-ST-40C identification coding system), runs the
  **L0plus codec round-trip** (`decode(L0plus)==L1A`, bit-exact) via msi-processor `l0_decode`,
  accounts for line-loss, EOQC, and a **structural scan of a real PSD L0 SAFE** (packet-tiling
  criterion on its ISP `.bin` files). New stdlib-only `s3fetch.py` (anonymous S3 listing +
  verified parallel GET). New manual CI job **`e2e-real-l1a`** (windowed, artifacts:
  report+quicklooks). Docs: ICD-IF-NAME, SRS REQ-FUNC-091/092/093, CIDL rows,
  `docs/vv/real_e2e.md`, README/DPM diagrams updated to the reverse-ladder flow.
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
  the reconstructed DN streams are reproducible across processes (REQ-QUAL-004).
- **CCSDS 122.0-B lossless image compression** (`s2_msi_raw_generator/ccsds122.py`, pure numpy) —
  the documented alternative to Sentinel-2's proprietary onboard MRCPB wavelet scheme: 3-level
  integer DWT 9/7-M, 8×8 block/family + 16-block gaggle structure, self-describing segment
  headers, DC/BitDepthAC DPCM + per-gaggle Rice coding; §4.5 AC stages with raw-packed planes
  (documented divergence from §4.5.3 VLC word mapping — see ICD-IF-C122). Encoder **and**
  decoder; `compress_frame`∘`decompress_frame` is bit-exact (14 unit tests + env-gated real-L1A
  window). Full 21384×2592 band ≈ 19 s each way. Groundwork for compressed ISP payloads
  (REQ-FUNC-092; ATBD §5.S15 rewritten to the real two-step onboard chain).
- **`data/` E2E folders + quicklook** — `data/input/` (reference L1A/GIPP; gitignored) and
  `data/output/{l0,caldb,quicklook}/`; `scripts/run_e2e_l0_to_l1b.py` writes products there by default.
  New dependency-free `s2_msi_raw_generator/quicklook.py` (stdlib-only PNG writer) renders an RGB preview.
  The large `.zarr` products are gitignored; the small **quicklook PNGs** are committed (README/site showcase).
- **zarr v2/v3 write compatibility** (`s2_msi_raw_generator/_zarrio.py`) — the L0 + cal-DB writers now run under
  **both** zarr 3 (local/CI) and **zarr 2.18** (the `eopf==2.8.1` SDE env; eopf pins zarr <3). Products stay in
  the zarr **v2** on-disk format either way, so the reverse-ladder writers run in a single venv alongside
  `msi-processor` (no separate zarr-3 venv).
- **Open-container L0 handoff + L0plus codec round-trip** — `l0product.write_l0_opencontainer` writes the
  *decoded* L0 (`measurements/detector/<band>` uint16 + `quality/l0_flags/<band>` QAFlag + per-line
  `conditions/*`) that `msi-processor`'s `l0_decode` ingests directly; the `decode(L0plus)==L1A` bit-exact
  handoff contract is asserted by `tests/test_l0_handoff.py`. (REQ-FUNC-042, rescoped to the
  handoff/round-trip contract)
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
- **ATBD radiometric inversion core** (`s2_msi_raw_generator/forward_radiometric_atbd.py`) — the exact
  **inverse** radiometric transform from the public L1 ATBD, driven by the GIPP: the ladder's
  radiometric-inversion rung (invert the operational L0→L1B correction to recover L1A DN).
- L1A/L1B raw reader (`io.read_l1a_raw`), `LICENSE` (Apache-2.0), this changelog.

### Changed
- Radiometric model adopts the official L1 ATBD raw equation `X = A·G·L + D` in true 12-bit DN.
- Dark/PRNU now per-pixel from the GIPP (was DQR-summary / seeded).
- L1C-entry + geometry-reverse module **cancelled** (not applicable to an L1A/L1B entry).

## [0.3.0] — Increments 0–4

- Full reverse radiometric-inversion ladder (invert offset, relative-response/PRNU, dark, un-bin,
  SWIR re-stage, defective, crosstalk, on-board-eq → 12-bit DN + CCSDS-122/ISP packetization),
  explicitly **without** PSF re-blur and **without** noise re-application (MTF-deconvolution OFF).
- L0 RAW EOProduct assembly (156-array Zarr + STAC/sensor-config).
- SRF spectral characterisation (sensor model); S2 PSF matrices (SentiWiki) retained only as an
  archived sensor reference (PSF/MTF is not re-applied in the ladder).
- Sensor model with per-band gains/TDI/line-period from EOPF products.
- GitLab CI (unit tests), ATBD + Annex A datasheet.

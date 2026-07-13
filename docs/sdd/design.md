<!--
  Copyright 2026 Can Deniz Kaya

  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
-->

# Software design

## General
The design realizes the **reverse chain**: it inverts the operational L0→L1B radiometric chain from
Sentinel-2B **L1B** DN (offset → relative-response/PRNU → dark → un-bin → SWIR re-stage → defective →
crosstalk → on-board-eq) via `forward_radiometric_atbd.reverse_l1b_to_l0`, reconstructing L1A → L0plus
(CCSDS-122 ISP) → Synthetic L0. The inversion is orchestrated by the `run_pipeline` phases **`reverse-l1b` →
`package-l0` → `validate-reverse`**, with MTF-deconvolution OFF so PSF and noise are **not** re-applied, and
validated against the reference ESA L0 `img` (10/20 m bands ≤~4 DN). The package is layered: a constants/sensor
leaf, an ADF/GIPP layer, the chain, and a product-assembly integrator. Every algorithm is implemented from
the public L1 ATBD and the GIPP data format.

## Overall architecture

### Key design decisions
- **Official ATBD radiometric model $X = A \cdot G \cdot L + D$.** The reverse chain takes the operational
  relation — relative response `G`, dark `D`, on-board equalization and offset — **only as the model it
  inverts** in the downlink DN domain from S2 L1B. It is the exact conjugate inversion of that chain, not
  a forward generator, and it does not apply the forward radiance→DN absolute multiply.
- **Real per-pixel dark + relative response from the operational GIPP** (R2EQOG `COEFF_D` / cubic
  (A,B,C) / bilinear (A1,A2,Zs)); no fitted or seeded values in the referenceized path — these are the
  coefficients the reverse chain inverts.
- **Calibration sub-set (inverse-crime cure).** The downstream calibration coefficients are *derived*
  independently from synthetic CSM sun-diffuser + dark acquisitions, rather than reusing the exact ADF
  values the reverse chain consumed for its inversion.
- **Original, self-contained.** No external processor is installed, imported, or named; the forward model
  comes from the public L1 ATBD and the calibration coefficients from the GIPP data files only.

## Software components design — General

### sensor.py — sensor model (REQ-FUNC-003)
Real harvested S2 constants and the `Band` dataclass. Key API: `BANDS`, `UNITS`, `band()`, `all_bands()`,
`band_number()`, `zarr_band_key()`, `spectral_band_info()`, `unit_from_platform()`; `Band` properties
`.dn_ref`, `.cal_gain`, `.dark_dsnu`. Carries `PHYSICAL_GAIN`, `LREF`, `SNR_AT_LREF`, `NOISE_ALPHA/BETA`,
`TDI_BANDS`, `SWIR_BANDS`, `DN_MAX`, `LINE_PERIOD_MS`, `NUC_TABLE_ID`, `RADIO_ADD_OFFSET_L1B`,
`DARK_PEDESTAL_LSB`, `EQ_GAIN_STD`.

### gipp.py — operational GIPP parser (REQ-FUNC-046, -015, -019, -012, -017, -018)
Original `xml.etree` parser → per-pixel arrays. API: `DetectorEq` (`.rel_gain`), `BandEq` (`.npix`),
`RadioParams`, `GippSet`; `read_r2eqog_band()`, `read_r2depi()`, `read_blindp()`, `read_r2para()`,
`read_r2crco()`, `load_gipp_set()`. **EOPF ADF parsers for the full reverse chain:**
`read_r2eqog_eopf()` (dark+PRNU from `ADF_REQOG`), `read_rswir_eopf()` (SWIR staggered-readout shift map
+ B10 kernel, `ADF_RSWIR`), `read_reob2_eopf()` (on-board-eq `a1/a2/zs/d`, `ADF_REOB2`),
`read_rcrco_eopf()` (13×13 crosstalk, `ADF_RCRCO`); `GippSet` carries the ADF paths and reads
`swir_shift()` / `onboard_eq()` lazily.

### adf.py — ADF assembly (REQ-FUNC-044, -046; REQ-IF-003)
`BandADF` frozen dataclass with `from_gipp()` (per-pixel dark + PRNU, blind-column width alignment),
`from_product()` (L1B-derived), `synthesize()` (fallback) — the reverse chain's ADF inputs.

### forward_radiometric_atbd.py — reverse chain + operational-eq inversion (REQ-FUNC-010, -011, -013, -015, -016, -020, -022)
**Full S2 L1B→Synthetic L0 reverse (the reverse chain):** `reverse_l1b_to_l0()` inverts the full radiometric chain in the
downlink DN domain (offset → `G⁻¹` (relative-response/PRNU) → on-board eq → dark → un-bin → SWIR re-stage →
defective), with `inverse_equalize()` / `forward_equalize()` (on-board-eq inversion — cubic via Newton,
bilinear closed-form) and helpers `reapply_onboard_eq()` (REOB2 bilinear non-linearity) and
`restage_swir_lines()` (S8 whole-line roll / B10 sub-pixel kernel). The reconstructed DN is clipped and
rounded to the 12-bit `uint16` product scale inline (`np.clip`/`np.rint`, REQ-FUNC-022).
Restoration/deconvolution (fwd step 8) is off, so PSF re-blur / noise are **not** re-applied.

### reverse.py — exact-inverse bridge (retained module)
Thin module retained and imported at package load. It exposes the exact-inverse bridge
`reverse_radiometric()` / `forward_radiometric()` between the DN and L1B domains. The operational
radiometric inversion of S2 L1B is performed by `forward_radiometric_atbd.reverse_l1b_to_l0` and `gipp`
(see above), not by a per-step forward-impress chain.

### calibration.py — calibration sub-set (REQ-FUNC-047; REQ-PERF-004)
`DerivedCalibration`; `synth_dark_acquisition()`, `synth_diffuser_acquisition()`, `derive_dark()`,
`derive_relative_response()`, `calibrate()`, `estimated_adf()`.

### isp.py — CCSDS ISP / telemetry (REQ-FUNC-030, -092)
`build_primary_header()`, `parse_primary_header()`, `cuc_time()`, `apid_for()`,
`packetize_stream()` / `iter_packets()` / `reassemble_segments()` (compressed payload transport,
SEQ_FIRST/CONT/LAST grammar), `build_sad_packets()`; `frame_isp_headers()` is legacy.

### ccsds122.py — CCSDS 122.0-B lossless image compression (REQ-FUNC-092; ICD-IF-C122)
`compress_frame()` / `decompress_frame()` (bit-exact), `dwt97m_forward()` / `dwt97m_inverse()`,
`parse_segment_headers()`, `segment_byte_bounds()`, `CompressionStats`.

### naming.py — EOPF PSFD §3 product naming (REQ-FUNC-091; ICD-IF-NAME)
`psfd_name()`, `parse_psfd_name()` (exact inverse), `from_l1a_context()` (flagged fallbacks).

### s3fetch.py — anonymous S3 fetch (REQ-FUNC-093 input path)
`list_prefix()` (paginated), `fetch_prefix()` (verified parallel GET, resume, traversal guard),
`parse_list_xml()`, `save_manifest()`.

### io.py — product reader (REQ-IF-001, REQ-FUNC-001)
`read_l1b_band()`, `read_l1a_raw()`.

### l0product.py — Synthetic L0 RAW assembly (REQ-FUNC-030..-034, -045; REQ-IF-002)
`reverse_to_l0_frames()`, `build_root_metadata()`, `write_l0_product()` (L0plus — CCSDS ISP + ancillary,
`eopf_type` selectable), **`write_l0_decoded_product()`** (decompressed-`img` L0 mirroring the reference S2B
`S02MSIL0__` layout — `measurements/d{DD}/b{BB}/img` + decode-quality attrs, for a direct ESA-L0 compare),
`read_l0_isp_dn()`.

### import_l0.py — L1A materialisation + public-L0 import (REQ-FUNC-001, -045)
`read_public_l0_identity()`, `convert()` (public Synthetic L0 → PDI-style L1A), **`write_l1a_product()`** — the
reverse chain's materialised L1A writer: multi-detector raw counts → `measurements/DD{dd}/{BAND}/l1a_raw_image`
+ L1A STAC, serial (NFS-safe) with a bit-identical re-read assert. Consumed back by `io.read_l1a_raw()`.

The reverse chain (`run_pipeline` phases) is **`reverse-l1b` → `package-l0` → `validate-reverse`**:
reconstruct S2 L1B → materialise L1A, then L1A → L0plus (ISP) → Synthetic L0 (decoded img), then compare the
Synthetic L1A against the reference S2B reference ESA L0 `img` (framing-aligned; no decoding — the archived EOPF L0 already
stores decompressed `img`, verified on the 2024-04-08 TC7D granule).

## Software components design — Aspects of each component
All components are stateless functions or frozen dataclasses operating on NumPy arrays; the only I/O is in
`io.py` (read) and `l0product.py` (write). Coefficient provenance is carried on `BandADF.source` and in
the Synthetic L0 `adf_provenance` metadata (REQ-FUNC-045).

## Internal interface design
Arrays are 2-D `(lines, detector_columns)`; per-pixel coefficients are `(act,)` broadcast over lines.
`BandADF` is the contract object between `adf`/`gipp` and the reverse chain (`forward_radiometric_atbd`);
`DetectorEq` between `gipp` and `forward_radiometric_atbd`; `FrameKey = tuple[int, str]` (detector, band) keys the L0 frame dict in
`l0product`. See the ICD (`docs/icd.md`) for the external product interfaces.

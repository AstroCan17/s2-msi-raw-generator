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
The design realizes the reverse radiometric chain as a set of small, pure-NumPy functions (one per ATBD
§5 step) composed into the `reverse_mvp` / `reverse_full` pipelines, parameterized by per-band ADFs and
driven byS2 calibration data. The package is layered: a constants/sensor leaf, an ADF/GIPP layer,
the chain, and a product-assembly integrator. Every algorithm is implemented from the public L1 ATBD and
the GIPP data format.

## Overall architecture

### Key design decisions
- **Official ATBD raw model $X = A \cdot G \cdot L + D$.** S1 applies the absolute-calibration multiply $\mathrm{DN} = A \cdot L$;
  S7 the relative response `G`; S11 the dark `D`. This matches the public L1 ATBD §4.1.1 forward model so
  the reverse is its exact conjugate.
- **`cal_gain` anchored on the noise model + SNR.** The absolute coefficient `A` (`Band.cal_gain`)
  is derived from the per-band noise α,β and the spec SNR@Lref, so the chain reproduces SNR@Lref
  exactly on the true 12-bit DN scale (the product `physical_gain` is retained as metadata).
- **Real per-pixel dark + relative response from the operational GIPP** (R2EQOG `COEFF_D` / cubic
  (A,B,C) / bilinear (A1,A2,Zs)); no fitted or seeded values in the realized path.
- **Noise impressed on the signal DN, before the dark pedestal**, so $\sigma = \sqrt{\alpha^2 + \beta \cdot \mathrm{DN}_\mathrm{signal}}$ reproduces
  the spec SNR@Lref.
- **Calibration sub-set (inverse-crime cure).** Coefficients handed to a downstream processor are
  *derived* from synthetic CSM sun-diffuser + dark acquisitions, not the truth impressed in S7/S11.
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

### adf.py — ADF assembly (REQ-FUNC-014, -044, -046; REQ-IF-003)
`BandADF` frozen dataclass with `from_gipp()` (per-pixel dark + PRNU, blind-column width alignment),
`from_product()` (L1B-derived), `synthesize()` (fallback); `real_psf_kernel()`, `load_oversampled_psf()`,
`noise_coeffs()`, `fit_noise_coeffs()`.

### forward_radiometric_atbd.py — ATBD model + exact inverse (REQ-FUNC-015, -010; REQ-PERF-003)
`forward_equalize()`, `inverse_equalize()` (cubic via Newton, bilinear closed-form), `forward_correct()`
(L1A→L1B), `reverse_impress()` (L1B→L1A), `column_fpn()`. **Full real-L1B→L0 reverse:**
`reverse_l1b_to_l0()` inverts the full radiometric chain in the downlink DN domain (offset → `G⁻¹` →
on-board eq → dark → un-bin → SWIR re-stage → defective), with helpers `reapply_onboard_eq()` (REOB2
bilinear non-linearity) and `restage_swir_lines()` (S8 whole-line roll / B10 sub-pixel kernel).
Restoration/deconvolution (fwd step 8) is off, so PSF re-blur / noise are not re-applied.

### reverse.py — reverse chain (REQ-FUNC-010..-022)
One function per step: `s1_radiance_to_dn`, `s3_undo_framing`, `s4_undo_radiometric_offset`, `s5_unbin`,
`s6_psf_reblur`, `s7_impress_relative_response`, `s8_restage_swir`, `s9_apply_crosstalk`,
`s10_inject_defects`, `s11_reapply_dark`, `s12_reapply_onboard_eq`, `s13_add_noise`, `s14_quantize`;
chains `reverse_mvp()`, `reverse_full()`; exact-inverse bridge `reverse_radiometric()` /
`forward_radiometric()`.

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

### l0product.py — L0 RAW assembly (REQ-FUNC-030..-034, -045; REQ-IF-002)
`reverse_to_l0_frames()`, `build_root_metadata()`, `write_l0_product()`.

## Software components design — Aspects of each component
All components are stateless functions or frozen dataclasses operating on NumPy arrays; the only I/O is in
`io.py` (read) and `l0product.py` (write). Coefficient provenance is carried on `BandADF.source` and in
the L0 `adf_provenance` metadata (REQ-FUNC-045).

## Internal interface design
Arrays are 2-D `(lines, detector_columns)`; per-pixel coefficients are `(act,)` broadcast over lines.
`BandADF` is the contract object between `adf`/`gipp` and `reverse`; `DetectorEq` between `gipp` and
`forward_radiometric_atbd`; `FrameKey = tuple[int, str]` (detector, band) keys the L0 frame dict in
`l0product`. See the ICD (`docs/icd.md`) for the external product interfaces.

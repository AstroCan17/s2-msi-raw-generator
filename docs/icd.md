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

# Interface control document

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1, Annex E (ICD).
Companion to the SRS (`docs/srs.md`, interface requirements REQ-IF-001/002/003) and the ATBD
(`docs/atbd/atbd.md`).

## Introduction

This document specifies the external and internal interfaces of the reverse E2ES: the products it
consumes (Sentinel-2 L1A/L1B EOPF Zarr), the auxiliary calibration data it reads (the operational
GIPP), and the synthetic **L0 RAW** product it produces (the normative interface **ICD-IF-L0**). All
data interfaces are file-based (Zarr / XML); there is no network, hardware, or database interface.

## Software overview

`s2_msi_raw_generator` is a pure-Python library (runtime deps `numpy`, plus `zarr` for product I/O). It reads a real
L1A/L1B granule, runs the radiometric reverse chain (ATBD §5, S1–S15), and assembles a 156-array L0 RAW
EOProduct. Auxiliary inputs (PSF matrices, SRF, operational GIPP) areS2 data.

## Interface design

### Internal interfaces (module contracts)

| Module | Key entry points | Contract |
|---|---|---|
| `sensor` | `band(name, unit)`, `all_bands()`, `spectral_band_info(unit)`, `unit_from_platform()`, constants | Pure data/model; leaf module — per-band gains/TDI/SRF/noise constants. |
| `gipp` | `load_gipp_set(dir)` → `GippSet`; `read_r2eqog_band`, `read_r2depi`, `read_blindp`, `read_r2para`, `read_r2crco` | Parses  S2A GIPP XML → per-pixel arrays (`DetectorEq`, `BandEq`, `RadioParams`). |
| `adf` | `BandADF` (`from_gipp`, `from_product`, `synthesize`), `real_psf_kernel`, `noise_coeffs` | Builds the per-band ADF set (PSF, noise α,β, per-pixel dark/PRNU). |
| `reverse` | `s1..s14` step functions, `reverse_mvp`, `reverse_full`, `reverse_radiometric`/`forward_radiometric` | NumPy reverse chain on `(lines, detector_columns)` arrays. |
| `forward_radiometric_atbd` | `forward_correct`, `reverse_impress`, `forward_equalize`/`inverse_equalize`, `column_fpn` | Public-ATBD forward model + exact inverse (round-trip bridge). |
| `calibration` | `calibrate`, `estimated_adf`, `synth_dark_acquisition`, `synth_diffuser_acquisition` | Two-reference calibration sub-set → derived coefficients. |
| `io` | `read_l1b_band`, `read_l1a_raw` | Lightweight Zarr reader (no full EOPF CPM). |
| `isp` | `frame_isp_headers`, `build_sad_packets`, `build_primary_header`, `apid_for` | CCSDS ISP / SAD telemetry (S15). |
| `l0product` | `reverse_to_l0_frames`, `build_root_metadata`, `write_l0_product` | Top integrator → writes the ICD-IF-L0 product. |

Dependency direction: `sensor` (leaf) → `adf`/`gipp` → `reverse`/`forward_radiometric_atbd`/`calibration`
→ `l0product` (integrator). `io`, `isp` are leaves.

### External interfaces

- **IF-IN-L1B** — Sentinel-2 **L1B** radiance, EOPF Zarr (`.zarr` dir or `.zarr.zip`). Path
  `measurements/d{DD}/b{xx}/img`, `float32` radiance, dims `(alt, act)`. Read by `io.read_l1b_band`.
- **IF-IN-L1A** — Sentinel-2 **L1A** raw counts, EOPF Zarr. Path `measurements/DD{nn}/B{xx}/l1a_raw_image`,
  `float64` DN (offset $\approx 48$, saturation sentinel 32768). Read by `io.read_l1a_raw`.
- **IF-IN-GIPP** — operational S2A GIPP, directory of `S2A_OPER_GIP_<TYPE>_*.xml`
  (R2EQOG ×13, R2DEPI, BLINDP, R2PARA, R2CRCO). Read by `gipp.load_gipp_set`.
- **IF-OUT-L0-CAL** — calibration-campaign L0 products: dark `S02MSIDCA…zarr` (operation
  mode `DASC`) and sun-diffuser `S02MSISCA…zarr` (`ABSR`) — same canonical carrier as
  ICD-IF-L0 (CCSDS-122 compressed ISPs, PSFD naming, full root metadata); written under
  `<store>/caldb/` next to the cal-DB ADFs.
- **IF-IN-ADF** — packaged PSF matrices (`s2_msi_raw_generator/data/psf/{S2A,S2B,S2C}/*.csv`, 33×33 oversampled).
- **IF-OUT-L0** — synthetic **L0 RAW** EOProduct (Zarr v2) — see ICD-IF-L0 below.
- **IF-MMI** — man-machine: command-line scripts (`scripts/*.py`); stdout reports.

## Interface requirements

| ECSS category | Provision |
|---|---|
| SW-to-SW | EOPF Zarr in (L1A/L1B) and out (L0 RAW), zarr v2 for processor interoperability; GIPP XML in. Realizes **REQ-IF-001**, **REQ-IF-002**, **REQ-IF-003**. |
| SW-to-HW | Not applicable — pure software, no hardware interface. |
| Man-machine | the single CLI driver `scripts/run_pipeline.py` (mode-only CLI `nominal\|calibration`; configuration via `S2_DATA_STORE`/`S2_E2ES_*` environment variables); plain-text stdout + JSON phase reports. |
| Database | Not applicable — file-based products only. |
| Error behaviour | Unknown band/unit → `KeyError`; frame not `uint16`/out-of-range → `TypeError`; missing GIPP file → `FileNotFoundError`. |

### ICD-IF-L0 — L0 RAW output data items (normative)

Produced by `l0product.write_l0_product` (Zarr **v2**; `zarr_format=2` for EOPF/processor interoperability).
Band-key map `B03→b03`, `B8A→b8a`; band-number `B03→"03"`, `B8A→"8A"`; detectors `01`–`12`.

| Path | Type | Dimension | Range / value | Source |
|---|---|---|---|---|
| `measurements/d{DD}/b{BB}/band{N}` *(store_decoded)* | uint16 | (line, column); chunks = full | `[0, 4095]`; attr `short_name="band{N}"` | reverse chain (REQ-FUNC-031) |
| `measurements/d{DD}/b{BB}/isp` *(with_isp)* | uint8 | (stream octets,) | concatenated CCSDS space packets carrying the **CCSDS-122 compressed** frame (ICD-IF-C122 payload; `SEQ_FIRST/CONT/LAST` groups = codec segments = 8 image lines; per-group CUC epoch); group attrs `apid`, `n_packets`, `n_segments`, `max_payload_octets`, `compression{scheme, pixel_bit_depth, raw/compressed_bytes, ratio}` | `ccsds122.compress_frame` + `isp.packetize_stream` (S15, REQ-FUNC-092) |
| `measurements/d{DD}/b{BB}/isp_offsets` *(with_isp)* | uint64 | (n_packets,) | byte offset of each packet in `isp` | `isp.packetize_stream` |
| `measurements/d{DD}/b{BB}/packet_data_length` *(with_isp)* | uint32 | (n_packets,) | data-field octet count (CCSDS field + 1) | `isp.packetize_stream` |
| `quality/d{DD}/b{BB}/mask` | uint8 | = band shape | bit0 saturated ($\mathrm{DN}\ge 4095$), bit1 hot, dead cols | reverse / defects (REQ-FUNC-032) |
| `conditions/anc_data/s{APID}/isp` *(with_isp)* | uint8 | (n_packets, hdr+payload) | CCSDS SAD/housekeeping | `isp.build_sad_packets` |
| `conditions/anc_data/s{APID}/packet_data_length` *(with_isp)* | uint16 | (n_packets,) | octet count | `isp.build_sad_packets` |

A full product = **12 detectors × 13 bands = 156** `band{N}` arrays + 156 `mask` arrays; with
``store_decoded=False`` the `band{N}` arrays are omitted and the product stores **ISPs only**,
mirroring the real S2 L0 (SentiWiki: L0 = compressed ISPs — the ground L1A step decompresses;
here `l0product.read_l0_isp_dn` restores the exact DN). The former per-line `isp_header` array
is **removed** by this issue (superseded by the packet stream; repo-internal schema change).

**Root attributes** (`build_root_metadata`):

| Key | Content | Req |
|---|---|---|
| `stac_discovery` | `type="Feature"`, `properties{platform, instrument="Multi Spectral Imager MSI", eopf:type="S2MSIL0_", datetime, start_datetime, end_datetime}` | REQ-FUNC-033 |
| `other_metadata.NUC_table_ID` / `onboard_compression_flag` / `onboard_equalization_flag` | `3` / `true` / `true` | REQ-FUNC-034 |
| `other_metadata.sensor_configuration.acquisition_configuration` | `active_detectors_list` (zero-padded sorted), `compress_mode`, `equalization_mode`, `nuc_table_id`, `spectral_band_info` (per band: `compression_rate`, `integration_time{unit:ms,value}`, `physical_gains`, `central_wavelength{nm}`, `bandwidth{nm}`, `equivalent_wavelength{nm}` — per-unit SRF), `tdi_configuration_list={"03":"APPLIED","04":"APPLIED","11":"APPLIED","12":"APPLIED"}` | REQ-FUNC-034 |
| `other_metadata.sensor_configuration.time_stamp.line_period` | `1.5658736` (ms) | REQ-FUNC-034 |
| `processing_history` | `processor="s2_msi_raw_generator"`, `processor_version`, `adf_provenance{physical_gains, cal_gain, psf, spectral, noise, dark, equalization, prnu, defects}` | REQ-FUNC-045 |

`unit` (S2A/S2B/S2C) is derived from `platform` via `sensor.unit_from_platform`; APIDs from
`isp.apid_for(detector, band_index)` (11-bit, base 1024).

### ICD-IF-C122 — compressed image payload stream (normative)

ISP image payloads carry a **CCSDS 122.0-B lossless-profile** stream produced by
`s2_msi_raw_generator.ccsds122` (the documented *alternative* to Sentinel-2's proprietary
onboard MRCPB scheme). One stream encodes one detector/band frame and is fully
**self-describing**:

| Field group | Layout (little-endian) | Blue-Book counterpart |
|---|---|---|
| Frame header | `magic "C122LSv1"` u8×8 · `version` u8 · `dwt_levels` u8 (=3) · `height` u32 · `width` u32 · `pixel_bit_depth` u8 · `pad` u8 (`pad_h<<4\|pad_w`) · `segment_blocks` u32 · `n_segments` u32 | Part 3 / Part 4 content |
| Per segment | `flags` u8 (bit0 StartImgFlag, bit1 EndImgFlag) · `n_blocks` u32 · `BitDepthDC` u8 · `BitDepthAC` u8 · section byte-lengths `len_dc`/`len_bda`/`len_ac` u32×3, then the three byte-aligned sections | Part 1A content |
| DC section | raw two's-complement reference (`BitDepthDC` bits) + zigzag-DPCM diffs, per-gaggle Rice (5-bit parameter, 31 = uncoded escape), gaggles of 16 | §4.3 |
| BitDepthAC section | same DPCM+Rice machinery, 6-bit reference width | §4.4 |
| AC section | plane-sequential (`BitDepthAC−1 → 0`) significance → sign → refinement passes, block-major scan, **raw-packed bits** | §4.5 stages |

**Documented divergences** (agreed lossless subset): §4.5.3 word mapping / variable-length
codes replaced by raw-packed stage bits (bit-exact, structurally 122-shaped, *not*
interoperable with reference decoders — the matching decoder is in-package); explicit
byte-aligned header fields carrying the Part 1A/3/4 content; byte-aligned sections.
Segments default to one block row = 8 image lines. Verified by `tests/test_ccsds122.py`
(bit-exact `compress_frame`∘`decompress_frame` identity). (REQ-FUNC-092)

### ICD-IF-NAME — product identification & file naming (normative)

ECSS-M-ST-40C Rev.1 requires every configuration item to carry a **unique identification code
under a defined coding system** (it prescribes the *system*, not a concrete string format —
that is mission-specification territory). This project's coding system for data products is
the **EOPF PSFD §3** file-naming rule, implemented by `s2_msi_raw_generator.naming` and
recorded in the CIDL:

```
TTTTTTTTT_YYYYMMDDTHHMMSS_DDDD_URRR_XVVV[_Z…][.zarr|.zarr.zip]
```

| Field | Content | Source |
|---|---|---|
| `TTTTTTTTT` | 9-char product type (`S02MSIL0_`, `S02MSIL1A`, `S02MSIL1B`, `S02MSIISP`, `S02SADISP`; `_`-padded) | PSFD §3 type codes |
| `YYYYMMDDTHHMMSS` | acquisition start (UTC) | product STAC `datetime` |
| `DDDD` | duration, seconds (round-half-up, min 1, ≤ 9999) | `n_lines × line_period` |
| `U` | platform unit letter (A/B/C) | STAC `platform` |
| `RRR` | relative orbit 001–143 | STAC `sat:relative_orbit` |
| `X` | consolidation: `T` NRT · `_` STC · `S` NTC | run configuration |
| `VVV` | 3-hex discriminator (deterministic CRC of the other fields when not given) | `naming.psfd_name` |
| `_Z…` | optional type-specific suffix (e.g. `_OC` for the open-container form) | caller |

Example: `S02MSIL0__20220803T113642_0033_A123_T5C1.zarr`. `naming.parse_psfd_name` is the
exact inverse; every emitted name must round-trip (REQ-FUNC-091). Fields not derivable from
the source product's metadata fall back to documented defaults and are flagged in the run
report (`derived_from_defaults`).

**Legacy-PSD crosswalk** (S2 PSD `S2-PDGS-TAS-DI-PSD`; kept in *metadata*, not file names):
`eopf:datastrip_id` = `S2A_OPER_MSI_L0__DS_<sensing>_A<orbit>` (PSD datastrip id, written by
`l0product.build_root_metadata`); real bucket products use the PSD forms
`S2A_OPER_PRD_MSIL0P_…​.SAFE`, `S2A_OPER_MSI_L0__GR_…_D<dd>` — the structural-comparison
phase of `scripts/run_pipeline.py` maps these to our PSFD names in its report.

**Operational decoder placement.** The canonical L0's ground decode (packet reassembly +
CCSDS-122 decompression) is implemented on the **consumer side**
(`msi_processor.computing.l0_decode.ground_decode`) — the real-chain L1A-side operation.
This module's `read_l0_isp_dn` remains the E2ES-side *reference* decoder; the pipeline's
`ground-decode` phase runs both and cross-checks them bit-exactly when the consumer is
installed.

## Validation requirements
The output structure is verified by `tests/test_l0product.py` (156-array contract, dtypes, root metadata,
`tests/test_ccsds122.py` (ICD-IF-C122 bit-exact stream), `tests/test_isp_packetize.py` (packet grammar),
`tests/test_naming.py` (ICD-IF-NAME round-trip), `tests/test_s3fetch.py`, `tests/test_real_e2e_driver.py`,
`eopf:type`, `tdi_configuration_list`, `physical_gains`, `line_period`, `adf_provenance`) and
`tests/test_integration.py` (end-to-end product incl. ISP + quality masks). Inputs are exercised on real
ESA L1A/L1B and the GIPP.

## Traceability
### Datatake / operation-mode vocabulary

Every L0-family product identifies its datatake kind in two metadata slots —
`stac_discovery.properties["msi:datatake_type"]` and
`other_metadata.sensor_configuration.acquisition_configuration.operation_mode`:

| Product type (PSFD §3) | `operation_mode` | `msi:datatake_type` | Campaign |
|---|---|---|---|
| `S02MSIL0_` | `NOBS` | `INS-NOBS` | nominal Earth observation |
| `S02MSIDCA` | `DASC` | `INS-DASC` | dark-signal calibration (CSM closed / deep space) |
| `S02MSISCA` | `ABSR` | `INS-ABSR` | absolute-radiometric calibration (Lambertian sun diffuser) |

*Sources:* the `ABSR`/`DASC` mode tokens and the `S02MSISCA`/`S02MSIDCA` type codes are
the EOPF PSFD §3 product table's own vocabulary; `INS-NOBS` is the datatake type observed
in real S2 product metadata — the `INS-DASC`/`INS-ABSR` forms compose the observed `INS-`
prefix with the PSFD tokens (noted here as a reconstruction). Further campaign kinds the
real mission flies (vicarious over cloud-free ocean sites, lunar/deep-space views) map
onto the same carrier and metadata slots and are reserved for future datatake types.

REQ-IF-001 → IF-IN-L1A/L1B; REQ-IF-002 → ICD-IF-L0; REQ-FUNC-048 → IF-OUT-L0-CAL;
REQ-IF-003 → IF-IN-GIPP. Full matrix in
`docs/sdd/traceability.md`.

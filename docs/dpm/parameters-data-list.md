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

# Parameters data list

## Processing parameters

The generator runs a Sentinel-2B **L1B** backwards through the **exact inverse of the operational
L0→L1B radiometric chain** to reconstruct **L1A → L0plus → Synthetic L0** in the downlink DN domain. Per reverse-chain
step: the algorithm, the auxiliary data (ADF) it consumes, and the parameter source. All values are
S2-sourced. The reverse chain enters in the DN domain from the S2 L1B (`units: digital_counts`, **not** radiance);
**PSF and noise are not re-applied** (MTF-deconvolution is OFF, so L0 and L1B stay spatially identical).

| Step | Operation | ADF / parameter | Source |
|---|---|---|---|
| S4 | remove radiometric offset (−100 L1B) | `RADIO_ADD_OFFSET` | GIPP **R2PARA** (`sensor.RADIO_ADD_OFFSET_L1B`) |
| S5 | un-bin 60 m (B01/B09/B10) | binning factor / kernel | GIPP **R2BINN** (3×7, factor 3) |
| S7 | invert relative response (PRNU), apply $G^{-1}$ | cubic $A,B,C$ (VNIR) / bilinear $A_1,A_2,Z_s$ (SWIR) | GIPP **R2EQOG** (`adf.from_gipp`) |
| S8 | SWIR re-arrangement, reverse (B10/B11/B12) | per-column shift map | detector layout (`reverse.s8_restage_swir`) |
| S9 | invert crosstalk (add back) | per-band OPTICAL+ELECTRICAL row (≈0 for S2A) | GIPP **R2CRCO** |
| S10 | re-insert blind/defective pixels | saturated/blind column indices | GIPP **R2DEPI** / **BLINDP** |
| S11 | invert dark signal (add back) | per-pixel dark $D$ (`COEFF_D`) $\approx$ 440–522 LSB | GIPP **R2EQOG**; DQR fallback `DARK_PEDESTAL_LSB` |
| S12 | reverse onboard equalization | per-detector gain (stability 0.05 % $1\sigma$) | `sensor.EQ_GAIN_STD` |
| S14 | quantize 12-bit | `DN_MAX = 4095` | spec (`sensor.DN_MAX`) |
| S15 | ISP / SAD telemetry | APID base 1024, line period 1.5658736 ms | CCSDS (`isp`) |

Per-band static parameters (`sensor.py`): `PHYSICAL_GAIN`, `LREF`, `SNR_AT_LREF`, `NOISE_ALPHA/BETA`,
`INTEGRATION_TIME_MS`, `COMPRESSION_RATE`, per-unit SRF (`BAND_CENTRE_NM`/`BANDWIDTH_NM`/
`EQUIV_WAVELENGTH_NM`), `TDI_BANDS={B03,B04,B11,B12}`, `SWIR_BANDS={B10,B11,B12}`, `NUC_TABLE_ID=3`.
`SNR_AT_LREF` and `NOISE_ALPHA/BETA` are sensor-characterization values **not applied by the reverse chain** (there
is no synthetic gain derivation and no noise re-impression — the L1B carries its own noise realization);
they are retained only for reporting / SNR context. `COMPRESSION_RATE` (CCSDS-122), the SRF/wavelength set,
the TDI/SWIR band sets and `NUC_TABLE_ID` are consumed by the reverse chain.

**Calibration sub-set parameters** (`calibration.py`): diffuser radiance $L_\mathrm{diff}$ (default $1.5 \cdot L_\mathrm{ref}$),
`n_dark`/`n_diffuser` averaging lines; outputs derived $D(j)$, relative response $g(j)$ ($\langle g \rangle = 1$),
absolute coefficient $A$.

## S2 L1B reverse path (`reverse-l1b` phase)

A S2B **EOPF L1B is already digital
counts** (`units: digital_counts`, not radiance), so the `reverse-l1b` phase
(`forward_radiometric_atbd.reverse_l1b_to_l0`) enters in the **downlink DN domain** and inverts the
**full** L0→L1B radiometric chain — every step ESA applies (`payload.yaml` `AllRadiometricCorrectionL1B`,
all `feature_flag_* = True` **except** deconvolution/denoising), undone in reverse order:

$$X_\mathrm{L0} = G^{-1}\!\left(L1B + \mathrm{RADIO\_ADD\_OFFSET}\right) + D_\mathrm{L0}\cdot\frac{D}{\langle D\rangle}$$

then the spatial / cross-band steps. Per (band, detector), in reverse order:

| Fwd step | Reverse op | Source (ADF/GIPP) | Notes |
|---|---|---|---|
| offset (12) | $+\,\mathrm{RADIO\_ADD\_OFFSET}$ (−100) | **R2PARA** `radiance_offset_l1b` | per band |
| binning (11) | ×3 un-bin (replication, S5) | `RES_GROUPS["r60m"]` | 60 m B01/B09/B10; sub-pixel irrecoverable |
| defective (7) | re-stamp defective columns → NoData (S10) | **R2DEPI** `singularity_columns` | destructive fwd → marker only; mostly empty for S2B |
| SWIR-rearr (6) | re-introduce staggered readout (S8) | **RSWIR** `swir_band_list/swir_band/detector` (+`interpolation_filter/coefs`) | B11/B12 ±1-line roll (exact); B10 ±⅓-line 3-tap conv (lossy); edge rows lost |
| rel-response (5) | impress $G^{-1}$ (cubic VNIR / bilinear SWIR, S7) | **R2EQOG** (`inverse_equalize`) | dominant PRNU term |
| crosstalk (4) | add crosstalk back $X_k{+}{=}\sum_l \mathrm{dtalk}_{kl}X_l$ (S9) | **RCRCO** optical+electrical 13×13 | phase-level, same-res groups; ≈0 for S2A/B (optical 0, electrical ≤0.004) |
| dark (2) | $+\,D_\mathrm{L0}\cdot D/\langle D\rangle$ (S11) | `sensor.L0_DARK_LSB` (≈51) + **R2EQOG** COEFF_D shape | downlink dark ≠ raw COEFF_D (≈440) |
| onboard-eq (1) | re-apply bilinear non-linearity (S12) | **REOB2** `coeff_a1/a2/zs` (`reapply_onboard_eq`) | S2B $a_1{\approx}1.005,a_2{\approx}0.995$ (sub-percent); its dark $d{\approx}455$ cancels COEFF_D |

Blind columns are then re-inserted from **BLINDP**, and CCSDS-122 + ISP package the L0 (S15). The full-
chain ADFs (RSWIR/REOB2/RCRCO) are auto-found under `{S2_AUX_DIR}/adf-eopf` or set via
`$S2_{RSWIR,REOB2,RCRCO}_ADF`; `S2_REVERSE_FULL=0` restores the radiometric-only reverse.

**MTF restoration / deconvolution (forward step 8) is deliberately skipped — and so are PSF re-blur
and noise re-impression.** In the operational forward chain `feature_flag_with_deconvolution = False` and
`feature_flag_with_denoising = False` (s2msi `payload.yaml`, gated by ADF_RPARA `restoration`); SentiWiki:
*"Restoration (de-convolution MTF + wavelet de-noising) — disabled by default (instrument MTF already
high)."* Because the forward chain never sharpens the image, **L1B still carries the full instrument PSF
and its noise realization** (L0 and L1B are spatially identical) — re-blurring or re-noising would
double-count. Both are non-invertible in any case (deconvolution is lossy; the exact noise realization is
unrecoverable), so they are correctly omitted, not approximated.

Success is the Synthetic L0 DN vs the reference ESA L0 `img`: validated against the 2024-04-08 S2B PPB
pair (13 bands), the Synthetic L0 agrees within ≤ ~4 DN on the 10/20 m bands (median ≤ ~5 %), active-region
column FPN matches, and the L0plus codec round-trip (`decode(L0plus) == L1A`) is bit-exact; S8 brings the
SWIR (B11/B12) images into spatial agreement.
Inputs: `$S2_L1B_INPUT` (S2 L1B `.zarr`), `$S2_GIPP_DIR` (gipp-json); detectors via
`$S2_DETECTORS` (default 5).

## Data items

| Item | Type | Role | Directory | Consumed by (input to) |
|---|---|---|---|---|
| S2B L1B (`digital_counts`) | EOPF Zarr | input product | `<store>/inputs/` (`$S2_L1B_INPUT` / `$S2_L1A_INPUT`; public L0 under `inputs/public-data/level-0/`) | `forward_radiometric_atbd.reverse_l1b_to_l0` in the DN domain (reverse chain produces **L1A → L0plus → Synthetic L0**); sensor-model harvest (`sensor.py`) |
| operational GIPP | JSON (`GS2_*` schema) | auxiliary calibration data (per-pixel) | `$S2_GIPP_DIR` (`aux/gipp-json/{Bxx}/`) | `gipp.py` → `adf.BandADF.from_gipp`; reverse steps **S4/S5/S7/S9/S10/S11** |
| PSF matrices | CSV (33×33) | auxiliary — optical kernel (packaged, **not applied** by the reverse chain) | `s2_msi_raw_generator/data/psf/{S2A,S2B,S2C}/` (packaged) | `adf.real_psf_kernel` → `BandADF.psf`; retained for reference only — **PSF re-blur is skipped** (deconvolution OFF, L0≡L1B spatially) |
| `BandADF` | in-memory dataclass | assembled per-band ADF (dark, PRNU, eq, cross-band maps) | in-memory — `s2_msi_raw_generator/adf.py` | `reverse_l1b_to_l0` (**S7/S11/S12** + cross-band: `prnu_gain`, `dark_dn`, `eq_gain`); `calibration` campaign. `psf` and `noise_a/b` are carried but **not consumed** (re-blur/noise skipped) |
| signal/raw DN frames | `numpy` `(lines, cols)` | intermediate per step | in-memory — `s2_msi_raw_generator/reverse.py` | next reverse step → `ccsds122` compress + `isp` packetize (**S15**) → `l0product.write_l0_product` |
| Synthetic L0 RAW EOProduct | Zarr v2 (156 arrays + masks + ISP) | output product (ICD-IF-Synthetic L0) | `$OUTPUT_DIR/l0/` (`l0product.write_l0_product`) | `l0product.read_l0_isp_dn` (`ground-decode`/`l0-decode` → `validate`); downstream **msi-processor** |
| derived calibration | `DerivedCalibration` | estimated dark/gain/A from the calibration sub-set | `<store>/caldb/` (dataclass `s2_msi_raw_generator/calibration.py`) | downstream **msi-processor** (nuc/dark/radiometric/spectral ADFs); `calibration.estimated_adf` (test-only) |

`<store>` = `$OUTPUT_DIR`, with sub-dirs `inputs/ caldb/ l0/ l1b/ quicklook/ figures/ report/` (`scripts/run_pipeline.py`).

**S15 compression/packetization parameters** (`ccsds122.py`, `isp.py`, `l0product.write_l0_product`):
`pixel_bit_depth` (12, or 16 when DN > 4095 — e.g. the 32768 saturation sentinel; preflight-chosen),
`segment_blocks` (default one block row = 8 image lines — line-accurate packet datation),
`isp_max_payload` (octets per packet data field, default 8192), `store_decoded`
(False → ISP-only product mirroring the ESA S2 Synthetic L0).

## Operational GIPP set (gipp-json)

Source: band-organised JSON under `$S2_GIPP_DIR` (`aux/gipp-json/{B01..B12,B8A,B00}/S2B_ADF_*.json`), wrapping the documented `GS2_*` schemas. Global ADFs (RDEPI, BLIND, RPARA, RCRCO) live in `B00/`; per-band REQOG in `{Bxx}/`.

| GIPP | Role | Reverse step | Creation | Validity-start (epoch) | Bands |
|---|---|---|---|---|---|
| `R2EQOG` | equalization / NUC (per-pixel dark + PRNU) | S7, S11 | 2020-03-10 | **2020-03-17** | per-band (B01–B12, B8A) |
| `R2DEPI` | defective-pixel map | S10 | 2018-07-13 | 2018-07-16 | B00 |
| `R2PARA` | radiometric offset (−100 L1B) | S4 | 2016-06-07 | 2015-06-22 | B00 |
| `R2CRCO` | crosstalk | S9 | 2015-10-23 | 2015-06-22 | B00 |
| `BLINDP` | blind-pixel columns | S10 | 2015-06-05 | 2015-06-22 | B00 |
| `R2BINN` | 60 m binning kernel | S5 | 2015-06-05 | 2015-06-22 | B00 |

No absolute-cal GIPP (`R2ABCA`) and no PSF are present in this set — PSF ships packaged (see *Data items*) but
is not applied, and no absolute-cal step is needed since the reverse chain enters from the S2 L1B DN (not radiance).
The NUC we correct with (`R2EQOG`, epoch **2020-03-17**) is the binding
constraint: it is ~4 years older than the ESA EOPF `REQOG` ADF (2024-04-17) below, and further still from any
2024-era acquisition — the core temporal-provenance issue tracked in issue #1.

## ESA calibration ADF set (bucket snapshot)

Source: ESA EOPF Auxiliary Data Files on OVH S3, `dpr-common/ADF-S02MSI/` (path-style addressing).
Snapshot inventory: **3858 objects, ~7.0 GiB**, per satellite (`S2A`/`S2B`; some processor-common `S2_`).
File names encode `S2x_ADF_<TYPE>_<applicability-start>_<validity-stop>_<creation>.json`. The validity-stop
`21000101` is ESA's open-ended placeholder, so the **applicability-start is the date that ADF version was
last (re)computed and became valid** — i.e. the effective calibration epoch.

Radiometric subset consumed by the reverse chain, with the epoch(s) present in the snapshot and the
recompute cadence:

| ADF (EOPF) | Role / GIPP | Reverse step | Epoch(s) in snapshot | Size (S2A+S2B) | Recompute cadence |
|---|---|---|---|---|---|
| `REQOG` | R2EQOG — equalization / NUC (per-pixel dark + PRNU) | S7, S11 | 2024-04-17 | 123.6 MB | **~monthly** (ESA S2 MSI Annual Performance Report) |
| `RABCA` | R2ABCA — absolute radiometric gain | (abs. cal.; not yet wired) | 2024-04-17, **2024-07-04** | 0.2 MB | periodic — two epochs ~78 d apart in snapshot |
| `RPARA` | R2PARA — radiometric offset (−100 L1B) | S4 | 2024-04-17 | small | static / event-driven |
| `RBINN` | R2BINN — 60 m binning kernel | S5 | 2024-04-17 | small | static |
| `RCRCO` | R2CRCO — crosstalk | S9 | 2024-04-17 | small | static |
| `RDEPI` | R2DEPI — defective-pixel map | S10 | **2024-04-16**, 2024-04-17 | 0.1 MB | event-driven (new dead pixels) |
| `BLIND` | blind-pixel columns | S10 | 2024-04-17 | 0.5 MB | event-driven |
| `RSWIR` | SWIR band re-arrangement LUT | S8-related | 2024-04-17 | 2.5 MB | static |

Non-radiometric ADFs found at other dates (for reference; the two later epochs the inventory surfaced):
`MRLUT` **2024-04-30** (reflectance-conversion LUT, L1C/L2A — not sensor NUC), `DATAT` 2024-04-17 &
**2024-07-22** (datation table), `TILEP` 2024-04-15, and the L2A atmospheric set
(`L2AGS`/`L2ALC`/`L2ASN`/`L2AWB`) 2024-03-01. Two large non-reverse-chain radiometric tables are also
present at 2024-04-17: `REOB2` (125.9 MB) and `VDIRP` (58.8 MB) — roles not yet mapped.

**Temporal-validity implication** — every reverse-chain radiometric ADF in this snapshot has an
applicability-start in **2024-04 (± days)**, so it is only temporally valid for acquisitions sensed around
**2024-04 – 2024-05**. Correcting an earlier acquisition (e.g. the 2018 turkey L1B) with this set applies a
~6-year-stale NUC; the pipeline's `_adf_temporal_validity` guard flags exactly this gap (issue #1). The
snapshot is a point-in-time export of the *currently-valid* ADF versions, so for most types it holds a
single epoch — the cadence column reflects the ESA APR (REQOG) and the multi-epoch evidence in the
snapshot (RABCA, RDEPI), not a per-type derivation.

## Selected validation datatake — 2024-04-08 S2B (`Validation/PPB`)

The temporal-provenance gap above (stale or future NUC vs acquisition epoch — issue #1, !58 Phase 5 open
item) is closed by selecting the input from the other direction: pick the datatake whose sensing epoch is
*covered* by ESA calibration set of the same platform. Inventorying an S3 listing of the ESA EOPF
validation bucket (985 140 keys; filtered by file-name validity windows, never read in full) surfaced
exactly **one S2 L1Btake L0↔L1B pair**, under `Validation/PPB/`:

| Product | Size | Objects |
|---|---|---|
| `S02MSIL0__20240408T053621_0566_B105_TC7D.zarr` (also as single-object `.zarr.zip`) | 60.3 GB | 88 966 |
| `S02MSIL1B_20240408T053621_0566_B105_T5B0.zarr` | 57.9 GB | 31 114 |

Datatake: **2024-04-08T05:36:21 UTC, 566 s, Sentinel-2B, relative orbit 105**. Per PSFD §3.2 the trailing
`XVVV` field is *aux-consolidation + quasi-unique hex*, **not** an MGRS tile — the differing `TC7D`/`T5B0`
suffixes do not indicate different scenes; product identity is the shared `sensing + duration + PRRR`
triple (both are full d01–d12 datastrip products). The pair enables validation in both directions:
S2 L1B → reverse chain → synthetic L0 ↔ ESA L0, and ESA L0 → msi-processor → synthetic L1B ↔ S2 L1B.

Bundled with the pair: `GCPs.zip` (373 MB, geometric validation) and IERS `bulletina-xxxvii-014`
(April 2024). The L0 zarr embeds its SAD under `conditions/ancillary_data/` (33 groups: attitudes,
ephemeris, 29 SAD packet groups, thermal, time-correlation) — **no separate SADATA product is required**.

### Temporally consistent S2B aux set

Filtering the same listing by validity window (`V<start> ≤ 20240408T053621 ≤ <stop>`, parsed from file
names) yields three format variants of the matching S2B calibration set:

| Set | Path prefix | Count | Reverse-chain radiometric epoch |
|---|---|---|---|
| XML GIPP (S2B) | `Products/eschalk/adf/gipp/01_xml_gipps/` | 174 files, 26 types | `R2EQOG` **2023-12-11** (per band, ×13) |
| EOPF ADF (S2B) | `Auxiliary/MSI/S02B_ADF_*` | 32 files, 20 types | `REQOG`/`RABCA` **2023-12-11**; `RDEPI` 2023-04-11 |
| JSON GIPP (converted) | `Products/eschalk/adf/gipp/02_auto_converted_xml_gipps_to_json/` | 169 files, 37 types | same epochs as XML |

Unlike the local S2A GIPP snapshot (`R2EQOG` epoch 2020-03-17, ~4 y stale) and the `dpr-common` ADF
snapshot (applicability 2024-04-17 — *after* this sensing date), the S2B `R2EQOG`/`REQOG` epoch
**2023-12-11 precedes and covers 2024-04-08**: the acquisition falls inside the ADF validity window, so
the `_adf_temporal_validity` guard (!58) passes without a stale-NUC caveat. Every GIPP type the reverse
chain consumes (`R2EQOG`, `BLINDP`, `R2CRCO`, `R2DEPI`, `R2PARA`, `R2BINN`) is present in the set. PSF
remains the packaged `data/psf/S2B/` CSVs (12 bands; no B10 — identity kernel, by design), retained for
reference only since PSF re-blur is not applied.

### Known limitations

- The listing holds **no S2 L1Btake L1A** (placeholder products only) — validation runs L1B↔Synthetic L0.
- No `S02MSISCA`/`S02MSIDCA` products — calibration-mode (sun-diffuser/dark) verification cannot be fed
  from this source.
- The GIPP parser is validated against S2A files; the S2B set is structurally identical by naming
  convention but must be confirmed on first parse.

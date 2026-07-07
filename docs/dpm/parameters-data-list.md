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

Per reverse-chain step: the algorithm, the auxiliary data (ADF) it consumes, and the parameter source.
All values areS2-sourced.

| Step | Operation | ADF / parameter | Source |
|---|---|---|---|
| S1 | radiance → equalized DN, $X = A \cdot L$ | $A$ = `Band.cal_gain` (per band) | derived from noise $\alpha,\beta$ + $\mathrm{SNR}@L_\mathrm{ref}$ (`sensor`) |
| S4 | remove radiometric offset (−100 L1B) | `RADIO_ADD_OFFSET` | GIPP **R2PARA** (`sensor.RADIO_ADD_OFFSET_L1B`) |
| S5 | un-bin 60 m (B01/B09/B10) | binning factor / kernel | GIPP **R2BINN** (3×7, factor 3) |
| S6 | PSF re-blur | per-band/unit 33×33 PSF (oversampling 5) | **ESA PSF** matrices (`s2_msi_raw_generator/data/psf/`); B10 = identity |
| S7 | impress relative response (PRNU) | cubic $A,B,C$ (VNIR) / bilinear $A_1,A_2,Z_s$ (SWIR) | GIPP **R2EQOG** (`adf.from_gipp`) |
| S8 | SWIR re-arrangement, reverse (B10/B11/B12) | per-column shift map | detector layout (`reverse.s8_restage_swir`) |
| S9 | re-apply crosstalk | per-band OPTICAL+ELECTRICAL row (≈0 for S2A) | GIPP **R2CRCO** |
| S10 | re-insert blind/defective pixels | saturated/blind column indices | GIPP **R2DEPI** / **BLINDP** |
| S11 | re-apply dark signal | per-pixel dark $D$ (`COEFF_D`) $\approx$ 440–522 LSB | GIPP **R2EQOG**; DQR fallback `DARK_PEDESTAL_LSB` |
| S12 | reverse onboard equalization | per-detector gain (stability 0.05 % $1\sigma$) | `sensor.EQ_GAIN_STD` |
| S13 | add sensor noise | per-band $\alpha, \beta$, $\sigma=\sqrt{\alpha^2+\beta\cdot\mathrm{DN}}$ | product **noise model** (`sensor.NOISE_ALPHA/BETA`) |
| S14 | quantize 12-bit | `DN_MAX = 4095` | spec (`sensor.DN_MAX`) |
| S15 | ISP / SAD telemetry | APID base 1024, line period 1.5658736 ms | CCSDS (`isp`) |

Per-band static parameters (`sensor.py`): `PHYSICAL_GAIN`, `LREF`, `SNR_AT_LREF`, `NOISE_ALPHA/BETA`,
`INTEGRATION_TIME_MS`, `COMPRESSION_RATE`, per-unit SRF (`BAND_CENTRE_NM`/`BANDWIDTH_NM`/
`EQUIV_WAVELENGTH_NM`), `TDI_BANDS={B03,B04,B11,B12}`, `SWIR_BANDS={B10,B11,B12}`, `NUC_TABLE_ID=3`.

**Calibration sub-set parameters** (`calibration.py`): diffuser radiance $L_\mathrm{diff}$ (default $1.5 \cdot L_\mathrm{ref}$),
`n_dark`/`n_diffuser` averaging lines; outputs derived $D(j)$, relative response $g(j)$ ($\langle g \rangle = 1$),
absolute coefficient $A$.

## Real-L1B reverse path (`reverse-l1b` phase)

The S1–S15 chain above enters from **synthetic radiance**. A real ESA **EOPF L1B is already digital
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
chain ADFs (RSWIR/REOB2/RCRCO) are auto-found next to `$S2_E2ES_EQOG_ADF` or set via
`$S2_E2ES_{RSWIR,REOB2,RCRCO}_ADF`; `S2_E2ES_REVERSE_FULL=0` restores the radiometric-only reverse.

**MTF restoration / deconvolution (forward step 8) is deliberately skipped — and so are PSF re-blur (S6)
and noise (S13).** In the operational forward chain `feature_flag_with_deconvolution = False` and
`feature_flag_with_denoising = False` (s2msi `payload.yaml`, gated by ADF_RPARA `restoration`); SentiWiki:
*"Restoration (de-convolution MTF + wavelet de-noising) — disabled by default (instrument MTF already
high)."* Because the forward chain never sharpens the image, **L1B still carries the full instrument PSF
and its noise realization** (L0 and L1B are spatially identical) — re-blurring or re-noising would
double-count. Both are non-invertible in any case (deconvolution is lossy; the exact noise realization is
unrecoverable), so they are correctly omitted, not approximated.

Validated against the real 2024-04-08 S2B PPB pair (13 bands): median ≤ ~5 %, active-region column FPN
matches, CCSDS-122/ISP round-trip bit-exact; S8 brings the SWIR (B11/B12) images into spatial agreement.
Inputs: `$S2_E2ES_L1B` (real L1B `.zarr`), `$S2_E2ES_GIPP_DIR`, `$S2_E2ES_EQOG_ADF`; detectors via
`$S2_E2ES_L1B_DETECTORS` (default 5).

## Data items

| Item | Type | Role | Directory | Consumed by (input to) |
|---|---|---|---|---|
| L1B radiance / L1A raw | EOPF Zarr (float) | input product | `<store>/inputs/` (`$S2_E2ES_L1A` / `$S2_E2ES_L1B`; public L0 under `inputs/public-data/level-0/`) | reverse-chain **S1** entry (`reverse.reverse_mvp`, radiance) via `phase_package`; sensor-model harvest (`sensor.py`) |
| operational GIPP | XML | auxiliary calibration data (per-pixel) | `<store>/inputs/s2-sensor/GIPP/` (`$S2_E2ES_GIPP_DIR`) | `gipp.py` → `adf.BandADF.from_gipp`; reverse **S4/S5/S7/S9/S10/S11** + `radiometric-vv` round-trip |
| PSF matrices | CSV (33×33) | auxiliary — optical kernel | `s2_msi_raw_generator/data/psf/{S2A,S2B,S2C}/` (packaged) | `adf.real_psf_kernel` → `BandADF.psf` → reverse **S6** (`reverse.s6_psf_reblur`) |
| `BandADF` | in-memory dataclass | assembled per-band ADF (PSF, noise, dark, PRNU) | in-memory — `s2_msi_raw_generator/adf.py` | `reverse.reverse_mvp` (**S6–S13**: `psf`, `prnu_gain`, `dark_dn`, `eq_gain`, `noise_a/b`); `calibration` campaign |
| signal/raw DN frames | `numpy` `(lines, cols)` | intermediate per step | in-memory — `s2_msi_raw_generator/reverse.py` | next reverse step → `ccsds122` compress + `isp` packetize (**S15**) → `l0product.write_l0_product` |
| L0 RAW EOProduct | Zarr v2 (156 arrays + masks + ISP) | output product (ICD-IF-L0) | `<store>/l0/` (writer `l0product.write_l0_product`) | `l0product.read_l0_isp_dn` (`ground-decode`/`l0-decode` → `validate`); downstream **msi-processor** |
| derived calibration | `DerivedCalibration` | estimated dark/gain/A from the calibration sub-set | `<store>/caldb/` (dataclass `s2_msi_raw_generator/calibration.py`) | downstream **msi-processor** (nuc/dark/radiometric/spectral ADFs); `calibration.estimated_adf` (test-only) |

`<store>` = `$S2_DATA_STORE` (default `~/data-store`), with sub-dirs `inputs/ caldb/ l0/ l1a_prime/ l1b/ quicklook/ figures/ report/` (`scripts/run_pipeline.py`).

**S15 compression/packetization parameters** (`ccsds122.py`, `isp.py`, `l0product.write_l0_product`):
`pixel_bit_depth` (12, or 16 when DN > 4095 — e.g. the 32768 saturation sentinel; preflight-chosen),
`segment_blocks` (default one block row = 8 image lines — line-accurate packet datation),
`isp_max_payload` (octets per packet data field, default 8192), `store_decoded`
(False → ISP-only product mirroring the real S2 L0).

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
(`forward_radiometric_atbd.reverse_l1b_to_l0`) enters in the **downlink DN domain** — the vault-canonical
inverse of the L0→L1B chain (SentiWiki: `onboard-eq⁻¹ · dark · blind · crosstalk · relative-response ·
SWIR-rearr · defective · restoration(off) · binning · −RADIO_ADD_OFFSET`):

$$X_\mathrm{L0} = G^{-1}\!\left(L1B + \mathrm{RADIO\_ADD\_OFFSET}\right) + D_\mathrm{L0}\cdot\frac{D}{\langle D\rangle}$$

| Term | Meaning | Source |
|---|---|---|
| $\mathrm{RADIO\_ADD\_OFFSET}$ | product offset, −100 (L1B) per band | GIPP **R2PARA** (`radiance_offset_l1b`) |
| $G^{-1}$ | impress relative response (cubic VNIR / bilinear SWIR) | GIPP **R2EQOG** (`inverse_equalize`) |
| $D_\mathrm{L0}$ | **downlink-domain** dark ≈ 51 DN (blind-column floor) | `sensor.L0_DARK_LSB` (per-satellite) |
| $D/\langle D\rangle$ | DSNU column *shape* only (COEFF_D normalized) | GIPP **R2EQOG** COEFF_D |
| ×3 un-bin (S5) | 60 m B01/B09/B10 (replication) | `RES_GROUPS["r60m"]` |

The downlink-domain dark $D_\mathrm{L0}$ (≈51) is **not** the raw-detector COEFF_D (≈440, a different
domain — near-unity onboard gain, `sensor.EQ_GAIN_STD`). **PSF re-blur (S6) and noise (S13) are not
re-applied** — restoration is off in the forward chain and the noise realization is already in L1B (both
are non-invertible terms). **SWIR re-arrangement (S8)** is not applied (image median unaffected; needs a
per-column shift map). Blind columns are re-inserted from **BLINDP**. Validated against the real
2024-04-08 S2B PPB pair (13 bands): median ≤ ~5 %, active-region column FPN matches, CCSDS-122/ISP
round-trip bit-exact. 60 m sub-pixel structure is irrecoverable (binning averaged 3→1). Inputs:
`$S2_E2ES_L1B` (real L1B `.zarr`), `$S2_E2ES_GIPP_DIR`, `$S2_E2ES_EQOG_ADF`; detectors via
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

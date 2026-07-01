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
| S8 | re-stagger SWIR (B10/B11/B12) | per-column shift map | detector layout (`reverse.s8_restage_swir`) |
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

## Data items

| Item | Type | Role |
|---|---|---|
| L1B radiance / L1A raw | EOPF Zarr (float) | input product |
| operational GIPP | XML | auxiliary calibration data (per-pixel) |
| PSF matrices | CSV (33×33) | auxiliary — optical kernel |
| `BandADF` | in-memory dataclass | assembled per-band ADF (PSF, noise, dark, PRNU) |
| signal/raw DN frames | `numpy` `(lines, cols)` | intermediate per step |
| L0 RAW EOProduct | Zarr v2 (156 arrays + masks + ISP) | output product (ICD-IF-L0) |
| derived calibration | `DerivedCalibration` | estimated dark/gain/A from the calibration sub-set |

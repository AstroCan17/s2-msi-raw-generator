---
title: "Sentinel-2 MSI Synthetic Raw Data Generator — L1→L0 Algorithms Theoretical Basis Document"
document_number: "S2MSI-E2ES-ATBD-0001"
version: "1.0"
date: "2026-06-30"
status: issued
confidentiality: Internal
---

> **Issued.** This ATBD defines the Sentinel-2 MSI **reverse** End-to-End performance Simulator
> (E2ES) — the L1→L0 algorithm chain (S1–S15). Algorithm structure, conjugacy, and **real**
> numerical values are populated: per-band gains/TDI/timing from products, official ESA PSF
> matrices, the SRF spectral characterisation, the product noise model, and the **operational
> S2A GIPP** (per-pixel dark + relative response). Radiometric inversion is validated by an original
> round-trip on a **L1A** (RMSE ~1e-14), and the calibration sub-set derives the coefficients
> from synthetic CSM-diffuser + dark acquisitions (inverse-crime cure). Implemented from the public
> L1 ATBD + GIPP data only.

---

# 1. INTRODUCTION

## 1.1 Project description

The Sentinel-2 MSI Synthetic Raw Data Generator (a **reverse E2ES**) is the **forward-instrument conjugate** of the `msi-processor`
(a generic high-resolution push-broom MSI processor, EOPF CPM 2.8.1, L0c→L2A, 8 units,
CI-green). Where the processor *inverts* instrument effects (radiometric calibration, PSF
deconvolution, co-registration, orthorectification, atmospheric correction), the E2ES
*impresses* them: it takes a Sentinel-2 **L1A/L1B** product (at-sensor radiance, already in
per-detector sensor geometry) and degrades it back to a synthetic **L0 RAW** product (focal-plane
digital numbers, 12 staggered detectors × 13 bands). Because L1A/L1B are already sensor-geometry,
the chain is **radiometric-only** — there is no geometry inversion (orthorectification undo) to
perform (Issue #17). An L1C entry + geometry-reverse module was considered and **cancelled**: with
an L1A/L1B entry there is nothing to de-orthorectify.

The E2ES serves two purposes:
1. **RAW generation** — produce realistic L0 RAW when true Sentinel-2 L0 is
   proprietary/unavailable, feeding processor development and testing.
2. **Round-trip V&V** — an original radiometric round-trip on a **L1A** with the **GIPP**:
   raw `X` → our ATBD forward correction (dark subtract + relative-response equalization) → corrected
   `Y` → our reverse impress → `X′`. The residual `X′ − X` ≈ 0 (verified to ~1e-14 on S2 DN)
   proves the forward and reverse are exact inverses; a controlled per-pixel-PRNU test shows the
   equalization genuinely flattens fixed-pattern noise (`forward_radiometric_atbd`,
   `scripts/roundtrip_real_l1a.py`). Implemented from the public L1 ATBD — no external processor.

## 1.2 Purpose of document

Present the L1→L0 reverse data flow and the physical/mathematical treatment at each stage,
with explicit traceability to the `msi-processor` forward function each reverse step conjugates.

## 1.3 Scope

Increment-0 deliverable. Algorithm-theoretical basis only; software design, ICD, and V&V plan
are separate DRDs. Reverse entry level is **L1A/L1B at-sensor radiance** (Issue #17); the L1C-entry
+ geometry-reverse module is **cancelled** (not applicable to an L1A/L1B entry).

## 1.4 References

### 1.4.1 Applicable documents
| | |
|---|---|
| AD 1 | `e2es-coupling-decision.md` — org/interface ADR (two groups; processor pinned wheel; sensor-model ADF bridge) |
| AD 2 | `msi-processor` ICD `<5.3.x>` (L0 RAW container, processor-owned) |
| AD 3 | `msi-processor` ATBD `<5.7>` (forward algorithm definitions, the conjugates) |
| AD 4 | ECSS-E-ST-40C; ECSS-E-ST-10-02C (Verification) |

### 1.4.2 Reference documents
| | |
|---|---|
| RD 2 | ESA Sentinel-2 Spectral Response Functions (S2-SRF), doc COPE-GSEG-EOPG-TN-15-0007 v4.0 (2024) |
| RD 3 | SentiWiki Sentinel-2 MSI — instrument/mission parameters |
| RD 4 | PyRawS — Sentinel-2 raw (L0-like) granule structure & per-detector layout |
| RD 5 | S2 datastrip metadata — `SOLAR_IRRADIANCE` (ESUN) per band |
| RD 6 | Sentinel-2 Products Specification Document (PSD) — L1C/L0 format |

## 1.5 Glossary

### 1.5.1 Acronyms
ADF (Auxiliary Data File), BOA (Bottom Of Atmosphere), DN (Digital Number), DSNU (Dark Signal
Non-Uniformity), E2ES (End-to-End performance Simulator), ESUN (mean exo-atmospheric solar
irradiance), GSD (Ground Sampling Distance), MSI (MultiSpectral Instrument), MTF (Modulation
Transfer Function), NUC (Non-Uniformity Correction), PRNU (Photo-Response Non-Uniformity),
PSF (Point Spread Function), RT (Radiative Transfer), SRF (Spectral Response Function),
TOA (Top Of Atmosphere), TDI (Time-Delay Integration), CSM (Calibration & Shutter
Mechanism), GRI (Global Reference Image), SSO (Sun-Synchronous Orbit), MGRS (Military Grid
Reference System). `[extend as needed]`

### 1.5.2 Definitions
- **Reverse step (R#):** an E2ES operation that undoes one `msi-processor` forward operation.
- **Conjugate:** the processor function a reverse step inverts.
- **Impress (true physics):** apply the *real* instrument effect, distinct from the processor's
  *estimated* correction — the basis of meaningful round-trip residuals (§Risk inverse-crime).

### 1.5.3 Definition of quantities
| Symbol | Name | Units |
|---|---|---|
| L | at-sensor band radiance (**L1B input**) | W·m⁻²·sr⁻¹·µm⁻¹ |
| DN | digital number (L0 RAW output) | none, [0, 2¹²−1] |
| g_phys | per-band physical gain (DN↔radiance, value Annex A.11) | — |
| g_nuc, o_nuc, k_dark | per-detector PRNU gain/offset, dark offset | — |
| PSF_b | per-band point spread function kernel (DC=1) | none |
| ρ_TOA | TOA reflectance (*cancelled L1C-entry module — unused*) | none, [0,1] |
| ESUN_b, θ_s, d | solar irradiance (from SRF), solar zenith, Earth–Sun dist (*cancelled L1C-entry module — unused*) | mixed |

### 1.5.4 Note on coordinates
Three coordinate sets: **detector** (focal-plane pixel, the L0 RAW frame),
**image/granule** (native acquisition grid), **map** (UTM/WGS-84, MGRS-tiled — *cancelled L1C-entry module*).
The v1 reverse operates entirely in **detector geometry** (input L1A/L1B is already there). Detector
array: **2592 px across-track
per module @ 10 m, 1296 px @ 20 m, ≈432 px @ 60 m**; 12 staggered modules per focal plane,
odd/even two-row stagger (Annex A.5). `[TBD: exact per-band sub-window origins / stagger
offsets — from ASGARD/GRI or PyRawS]`.

---

# 2. OVERVIEW

The Sentinel-2 MSI is a solar-reflective push-broom instrument: **13 spectral bands**
(B01 443 nm → B12 2202 nm; **no panchromatic band**), GSDs of **10/20/60 m**, two focal planes
(**VNIR** Si-CMOS + **SWIR** MCT) each with **12 staggered detector modules** across a 20.6° FOV,
on-board **sun-diffuser** (CSM) radiometric calibration, **12-bit** quantization (DN 0–4095).
**TDI:** the product `tdi_configuration_list` shows TDI **APPLIED on B03, B04, B11, B12** (2 VNIR +
2 SWIR); model as a per-band config. The S13 noise model dominates the SNR budget regardless. Full
sourced values in **Annex A**.

**Reverse data-flow figure (Fig-1 analog, to draw) — L1A/L1B → L0 RAW, radiometric-only:**
```
 L1B at-sensor radiance (per-detector geometry)
   → [S1] radiance → DN (÷ physical_gain)
   → [S3] undo framing/round-clamp → [S4] undo radiometric offset → [S5] undo 60 m binning
   → [S6] convolve true optical PSF (re-blur)
   → [S7] undo relative response (impress PRNU) → [S8] re-insert SWIR arrangement
   → [S9] re-apply crosstalk → [S10] re-insert blind/defective pixels
   → [S11] re-apply dark signal → [S12] re-apply onboard equalization
   → [S13] add noise σ=√(a+b·DN) → [S14] quantize 12-bit
   → [S15] format L0 RAW (156 detector/band frames + ISP telemetry + STAC)
```
No geometry inversion (L1A/L1B already sensor geometry). `[TBD: render as a proper block diagram]`

---

# 3. DATA PRODUCTS

| Role | Short name | Description |
|---|---|---|
| **Input** | S2 **L1A/L1B** | At-sensor **radiance** (L1B float32; L1A rawer), **per-detector** geometry (`measurements/d{DD}/b{BB}/img`, e.g. [9216,2552] @10 m), 13 bands. Already sensor-geometry ⇒ **no geometry inversion** (Issue #17). |
| **Output** | L0 RAW | Focal-plane uint16 DN per detector, 12 detectors × 13 bands, native geometry, quality annotations, STAC metadata. |

Output container (EOPF L0 Zarr = the normative **ICD-IF-L0**; Annex A.9): `measurements/d{DD}/b{BB}/band{BB}`
uint16 DN (156 arrays); `conditions/anc_data/s{APID}/isp` (CCSDS ISP/SAD telemetry); `quality/d{DD}/b{BB}/mask`
uint8; root STAC + sensor config (`tdi_configuration_list`, `spectral_band_info` incl. `physical_gains`,
`line_period`, `nuc_table_id`, `active_detectors_list`).

---

# 4. REVERSE PROCESSING FLOW

The processor's forward flow, reversed. Two sub-flows:

**Main reverse chain:** S1→S3→S4→S5→S6→S7→S8→S9→S10→S11→S12→S13→S14→S15 (§5) — radiometric-only.

**Calibration sub-set (`s2_e2es/calibration.py`, Increment 3):** the S2 **two-reference** radiometric
calibration in the reflective domain. The high-signal reference is the on-board **CSM sun-diffuser**
(uniform full-field), the zero reference is
a **dark** (CSM closed / night). The sub-set synthesises both L0 acquisitions by impressing the *true*
ADF, then **derives** the coefficients back (L1 ATBD §4.1.1.2.2):
`D(j)=⟨X_dark⟩_i`, `g(j)=A·⟨L_diff⟩/⟨X_diff−D⟩_i` with `⟨g(j)⟩_j=1` → fixes `A`. The processor then
uses the **derived** coefficients (`estimated_adf`), not the truth impressed in S7/S11 — closing the
loop **breaks inverse crime** (verified: derived dark recovers truth to <0.05 DN, relative response
correlation >0.99, `A≈cal_gain`; the small residual is the calibration uncertainty). `ADF_REQOG`.

---

# 5. PROCESSING-BLOCK DESCRIPTIONS (L1A/L1B → L0 RAW, 14 steps)

Entry = at-sensor **radiance** (L1B), per-detector geometry. Each step: forward action · ADF ·
`msi-processor` conjugate · notes. Real per-band values in **Annex A.6/A.11**.
`[INDEP]` = author from true physics; `[INV]` = closed-form inverse guarded by parameter mismatch.

## 5.S1 Radiance → DN `[INV, Inc 1]`
**Model:** the official L1 ATBD raw equation **`X_k = A_k·G_k(j,L)·L_k + D_k`** (S2-PDGS-MPC-ATBD-L1
§4.1.1): S1 impresses the absolute-calibration term **`DN = A·L`** (A = `Band.cal_gain`), S7 the
relative sensitivity `G`, S11 the dark `D`. **Choice of A:** the product's `physical_gains`
(Annex A.11) are kept for metadata/the round-trip bridge, but they are incoherent with the real
noise model on this synthetic dataset (they mis-scale low-radiance bands by up to ~10×). So `A` is
derived from the **noise α,β + SNR@Lref** (`cal_gain = dn_ref/Lref`, where `dn_ref` is the
12-bit DN at which `σ=√(α²+β·DN)` yields the spec SNR) — anchoring the chain to **reproduce the real
SNR@Lref exactly** (verified end-to-end). **ADF:** `ADF_RABCA`. **Conjugate:** `toa.dn_to_radiance`
(`L = DN/A`).

## 5.S3 Undo framing & round/clamp `[INDEP, Inc 3]`
**Forward:** extend to continuous detector strip; restore sub-pixel precision. **ADF:** `ADF_PRDLO`,
`ADF_RPARA`. **Conjugate:** `l0_decode` framing.

## 5.S4 Undo radiometric offset `[INV, Inc 3]`
**Forward:** `DN −= offset`. **Real value:** `radio_add_offset = −100` (L1B; −1000 for L1C, PB04.00).
**ADF:** `ADF_RPARA`. **Conjugate:** —.

## 5.S5 Undo 60 m binning (B01/B09/B10) `[INV, Inc 3]`
**Forward:** de-bin to detector-level (20 m → 60 m forward bin reversed). **ADF:** `ADF_RBINN`.
**Conjugate:** `georeference.resample_to_grid`.

## 5.S6 PSF re-blur `[INDEP, Inc 1]`
**Forward:** `I = I_sharp ★ PSF_true`, using the **official ESA per-band, per-unit PSF
matrices** (SentiWiki `S2{A,B,C}_PSF`, Annex A.4) integrated from the published 33×33 oversampled
matrix to the detector grid (B10 → identity). **ADF:** `ADF_RDEFI`. **Conjugate:**
`enhancement.mtf_compensate`/`_correlate2d` (an *independent regularized* inverse — must NOT be the
exact inverse). Far-field straylight has no S2 inverse (Risk 4).

## 5.S7 Undo relative response (impress PRNU) `[INDEP, Inc 1]`
**Forward:** impress the **true per-pixel relative response** by inverting the on-ground equalization
`Y = G(Z)` — VNIR cubic `A·Z³+B·Z²+C·Z` / SWIR bilinear (knee at `Zs`). **Real values:** the
per-pixel gains come straight from the **operational S2A GIPP `R2EQOG`** (`COEFF_A/B/C` cubic /
`COEFF_A1/A2/Zs` bilinear; C≈1.0–1.2 dominant), parsed by `s2_e2es.gipp` and applied via the analytic
inverse `G⁻¹` in `forward_radiometric_atbd.inverse_equalize` (`BandADF.from_gipp`). **ADF:** `ADF_REQOG`.
**Conjugate:** the forward radiometric correction `radiometric.apply_nuc`.

## 5.S8 Re-insert SWIR arrangement (B10/B11/B12) `[INDEP, Inc 3]`
**Forward:** restore the staggered SWIR readout layout (the TDI "rearrangement"). **TDI APPLIED on
B03, B04, B11, B12** (`tdi_configuration_list`). **ADF:** `ADF_RSWIR`. **Method:** PyRawS
`shift_lut.csv` deterministic per-(satellite, detector, band-pair) shifts (Annex A.9).

## 5.S9 Re-apply crosstalk `[INDEP, Inc 3]`
**Forward:** `DN_i += Σ xtalk[i,j]·DN_j` (optical + electrical). **Magnitude:** <0.5 % channel-to-channel.
**ADF:** `ADF_RCRCO`. **Conjugate:** *none* (S2-specific; named residual). Real matrix = the GIPP
`R2CRCO` (per-band OPTICAL+ELECTRICAL row; ≈0 for S2A → identity).

## 5.S10 Re-insert blind/defective pixels `[INDEP, Inc 3]`
**Forward:** insert masked blind columns + inject defective pixels (**3 in B11, 1 in B12** per S2C Cal/Val).
**ADF:** `ADF_BLIND` (blind), `ADF_RDEPI` (defective). **Conjugate:** `radiometric.replace_bad_pixels`.

## 5.S11 Re-apply dark signal `[INDEP, Inc 1]`
**Forward:** `DN += dark[pixel]`. **Real values:** the **per-pixel** dark signal `D(j)` comes from the
operational S2A GIPP **`R2EQOG` `COEFF_D`** (`s2_e2es.gipp`, `BandADF.from_gipp`) — mean 440–522 LSB per
band, matching the DQR (OMPC.CS.DQR.01.02-2023) range but now resolved per pixel. (Fallback when no GIPP:
`DARK_PEDESTAL_LSB` 440–520 + per-pixel DSNU `< 0.5/1.0 LSB`, `Band.dark_dsnu`.) Applied *after* S13 so
the noise model sees the dark-subtracted signal. **ADF:** `ADF_REOB2`/`ADF_REQOG`.

## 5.S12 Re-apply onboard equalization `[INDEP, Inc 1]`
**Forward:** invert the R2EQOG equalization — multiplicative (cubic VNIR `Z=ΣGₙ·Yⁿ` / bilinear SWIR)
on the dark-subtracted signal (Clerc et al. 2026, S2C cal/val; `equalization_mode = true`,
`nuc_table_id = 3`). Linearized here as `DN_raw = DN_eq/gain_ob`, with the **per-detector gain
stability 0.05 % 1σ** (paper Table 3, Ra factor; `sensor.EQ_GAIN_STD`) and **no offset** (the dark is
the S11 pedestal). **ADF:** `ADF_REOB2`. **Conjugate:** `radiometric.estimate_nuc`.

## 5.S13 Add sensor noise `[INDEP, Inc 1]`
**Forward:** the **S2-RUT noise model** `σ = √(α² + β·DN)`, with **α, β read verbatim from the
L1A product** (`quality_indicators_info/.../noise_model`, `sensor.NOISE_ALPHA/NOISE_BETA`); `DN +=
N(0,σ)`, seeded. Applied on the **signal DN** (before the S11 dark pedestal), so it reproduces the
 SNR@Lref (verified end-to-end, <1 %). **Acceptance:** σ within ±5 % over ≥10 000 px
(REQ-FUNC-021). **ADF:** `ADF_RNOMO`. **Conjugate:** processor *denoises*.

## 5.S14 Quantize `[INDEP, Inc 1]`
**Forward:** `clip(round(DN), 0, 4095)` → uint16 (12-bit at sensor). **ADF:** `ADF_CONVE`.
**Conjugate:** `radiometric.flag_saturation`. No-data 0; saturated 65535.

## 5.S15 Generate ISP packets & telemetry `[INDEP, Inc 4]`
**Forward:** package into CCSDS ISP; timestamps from `line_period = 1.5658736 ms`; SAD packets per APID.
**ADF:** `ADF_SADMP`, `ADF_DATAT`. **Conjugate:** `l0_decode`. **Output:** the 156-frame L0 (Annex A.9).

**Calibration sub-set (Inc 3, inverse-crime cure — implemented `s2_e2es/calibration.py`):** synthetic
CSM sun-diffuser + dark acquisitions → derive `D`, `g`, `A` (L1 ATBD §4.1.1.2.2) → *estimated* ADF
(`estimated_adf`) handed to the processor, not the truth impressed in S7/S11.

**Cancelled L1C-entry module (Issue #17):** an L1C entry would have required prepending
de-orthorectification (ground→detector via the S2 viewing model — **ASGARD**,
`ADF_VDIRP/SPAMO/GPARA/RESAM/TILEP/DEM`) + reflectance→radiance. This module is **dropped**: the
adopted L1A/L1B entry is already in native detector geometry, so there is nothing to de-orthorectify.
(L1C orthorectification destroys the native detector alignment the radiometric reverse relies on —
the very reason an L1C entry was rejected; PRNU paper.)

---

# 6. SENSOR-MODEL ADF v0 (the conjugate bridge)

Jointly change-controlled with the processor (per AD 1). **Conjugate subset** (both halves read):
- `spectral`: per-band S2 SRF samples (central λ Annex A.1); **ESUN_b derived from the same SRF**,
  **matched to the product's satellite** (S2A/B/C; Risk 2) — per-unit centre/bandwidth/equivalent
  wavelength from the SRF doc are in `sensor.py`.
- `radiometric`: per-band gain — **`physical_gains` from the product metadata** (Annex A.11,
  no credentialed ADF needed); `radio_add_offset = −100` (L1B). Source ADF: `ADF_RABCA`.
- `nuc`/`dark`/`badpixel`: per-detector PRNU (**1D per-detector model**; residuals from Zenodo
  `records/18433006`), DSNU + dark (`ADF_REOB2`, nighttime-ocean), defect/blind (`ADF_BLIND`/`ADF_RDEPI`,
  3×B11 + 1×B12), crosstalk `ADF_RCRCO` (<0.5 %). `nuc_table_id = 3`, equalization on.
- `psf`: per-band, per-unit kernel (DC=1) — the **official ESA PSF matrices** (SentiWiki
  `S2{A,B,C}_PSF`, Annex A.4), integrated from the 33×33 oversampled matrix to the detector grid.
- `viewing_model`: focal length 600 mm / F4 (TMA, 150 mm pupil), pixel pitch 7.5/15 µm, 12-detector
  stagger, per-band GSD (Annex A.2), `line_period` 1.5658736 ms. *(Was only needed by the cancelled L1C-entry module.)*

**E2ES-only block** (processor never reads): noise model (`a,b` for σ=√(a+b·DN), `ADF_RNOMO`),
crosstalk kernel, temporal gain drift (VNIR 0.1–0.35 %/months, SWIR faster).

**ADF access — all now.** Every radiometric ADF the chain needs is real: gain/TDI/timing/offset
from the products; **PSF** = the official ESA matrices (SentiWiki); **spectral** = the **SRF**
(COPE-GSEG-EOPG-TN-15-0007); **noise** = the per-band α, β from the L1A product
(`quality_indicators_info/.../noise_model`), σ=√(α²+β·DN) (S2-RUT, reproduces SNR@Lref). The
previously-modelled **per-pixel PRNU + dark** are now the **operational S2A GIPP**: `R2EQOG`
carries, per detector and per across-track pixel, the dark signal `COEFF_D` (≈440–522 LSB, matching
the DQR) and the relative-response gains (VNIR cubic `A/B/C`, SWIR bilinear `A1/A2/Zs`); `R2DEPI` the
defective/blind columns; `R2PARA` the −100/−1000 offsets; `R2CRCO`≈0. These GIPP **data** files are
parsed by `s2_e2es.gipp` (an original reader) into per-pixel arrays (`BandADF.from_gipp`).

---

# 7. ERROR ANALYSIS

Per-stage error-budget table, **reflective-domain terms**. Populate numerically in Inc 4 via sensitivity sweeps.

| Step | Dominant error term | Driver | Budget |
|---|---|---|---|
| S1 | gain / ESUN-SRF per-unit mismatch | radiometric | abs. <5 % (goal 3 %); per-unit SRF up to ~15 % if mismatched |
| S6 | PSF-restoration residual (forward-true vs inverse-estimate) | optics/MTF | MTF@Nyquist 0.15–0.30 (Annex A.4) |
| S7/S12 | PRNU/DSNU + equalization residual | radiometric | inter-band rel. 3 %; linearity 1 % |
| S9 | crosstalk residual (no processor inverse) | detector | <0.5 % channel-to-channel |
| S13 | SNR floor | noise model `√(a+b·DN)` | SNR@Lref per band (Annex A.6); ±5 % over ≥10⁴ px |
| S14 | quantization | 12-bit (0–4095) | ≈ Lref/SNR LSB |
| end-to-end | round-trip RMSE `L1B′ − L1B` per band | composite | declared radiometric tolerance; multi-temporal rel. ≤1 % |

**Method note:** re-derive the dominant terms for the reflective domain. The end-to-end claim is *round-trip regression*, not absolute verification.

---

# 8. OPEN POINTS

- Reverse entry level — **RESOLVED: L1A/L1B** (Issue #17); the L1C-entry + geometry-reverse module is **cancelled**.
- **L1A vs L1B for MVP:** L1B (radiance) → clean S1 radiance→DN (recommended); L1A is rawer.
- Straylight (S6 far-field): scope out of v0 or book as named residual.
- L0 RAW ICD: adopt the EOPF L0 Zarr structure (Annex A.9) as ICD-IF-L0.
- SRF: **DONE** — per-unit band centre/bandwidth/equivalent wavelength from the official SRF
  doc (COPE-GSEG-EOPG-TN-15-0007) are in `sensor.py`.
- PSF: **DONE** — official ESA per-band, per-unit matrices (`data/psf/`).
- Noise: **DONE** — per-band α, β from the L1A product (S2-RUT σ=√(α²+β·DN)).
- PRNU: derive from the L1B product (`scripts/derive_prnu_dark.py`). Dark: needs a real
  dark-calibration granule (none in this dataset); per-pixel NUC GIPP credentialed (#36).

---

# Annex A — Sentinel-2 MSI parameter data list (sourced)

Externally sourced, verified values. Primary sources: **SentiWiki (Copernicus)**
`sentiwiki.copernicus.eu`, **ESA SP-1322/2**, **S2 L1 ATBD**, **eoPortal**, **S2 User Handbook**;
cross-checked vs the official S2-SRF table (COPE-GSEG-EOPG-TN-15-0007). See A.8 for provenance and
unverified/derived flags. Values to be migrated into the sensor-model ADF v0 (§6).

## A.1 Spectral bands — central wavelength & bandwidth (FWHM), S2A / S2B
(Central λ cross-verified to ~0.3 nm; bandwidths are S2-SRF-version-sensitive — cite a version.)

| Band | S2A λ (nm) | S2A BW (nm) | S2B λ (nm) | S2B BW (nm) | GSD |
|---|---|---|---|---|---|
| B01 | 442.7 | 21 | 442.2 | 21 | 60 m |
| B02 | 492.4 | 66 | 492.1 | 66 | 10 m |
| B03 | 559.8 | 36 | 558.9 | 36 | 10 m |
| B04 | 664.6 | 31 | 664.9 | 31 | 10 m |
| B05 | 704.1 | 15 | 703.8 | 16 | 20 m |
| B06 | 740.5 | 15 | 739.1 | 15 | 20 m |
| B07 | 782.8 | 20 | 779.7 | 20 | 20 m |
| B08 | 832.8 | 106 | 832.9 | 106 | 10 m |
| B8A | 864.7 | 21 | 864.0 | 22 | 20 m |
| B09 | 945.1 | 20 | 943.2 | 21 | 60 m |
| B10 | 1373.5 | 31 | 1376.9 | 30 | 60 m |
| B11 | 1613.7 | 91 | 1610.4 | 94 | 20 m |
| B12 | 2202.4 | 175 | 2185.7 | 185 | 20 m |

**No panchromatic band.** B08 bandwidth has the largest cross-source divergence (106 vs 115/118 nm).

## A.2 GSD per band
- **10 m:** B02, B03, B04, B08
- **20 m:** B05, B06, B07, B8A, B11, B12
- **60 m:** B01, B09, B10

## A.3 ESUN — extraterrestrial solar irradiance (W·m⁻²·µm⁻¹), Thuillier 2003
(= the `SOLAR_IRRADIANCE` stored per band in L1C metadata; S2A ≠ S2B because of distinct SRFs.)

| Band | ESUN S2A | ESUN S2B | Band | ESUN S2A | ESUN S2B |
|---|---|---|---|---|---|
| B01 | 1884.69 | 1874.30 | B08 | 1041.63 | 1041.28 |
| B02 | 1959.66 | 1959.75 | B8A | 955.32 | 953.93 |
| B03 | 1823.24 | 1824.93 | B09 | 812.92 | 817.58 |
| B04 | 1512.06 | 1512.79 | B10 | 367.15 | 365.41 |
| B05 | 1424.64 | 1425.78 | B11 | 245.59 | 247.08 |
| B06 | 1287.61 | 1291.13 | B12 | 85.25 | 87.75 |
| B07 | 1162.08 | 1175.57 | | | |

## A.4 Optics
- Telescope: **Three-Mirror Anastigmat (TMA)**, off-axis, SiC mirrors + structure. Mirror sizes
  M1 442×190, M2 147×118, M3 556×291 mm. Optics identical on S2A/S2B.
- Entrance pupil / aperture: **150 mm**. Focal length: **600 mm (0.60 m)** — now confirmed
  (Languille 2015 "focal length is 0.60 m"), F-number **F/4**. FOV **20.6°** across-track
  (→ 290 km swath @ 786 km); IFOV ≈ 21° × 3.5°.
- Distortion: line-of-sight of edge detector (#12) reaches **2.8° tilt** vs a distortion-free
  telescope; distortion pattern varies with across-track position.
- **MTF at Nyquist** (combined system spec — telescope + detector + smear): 10 m & 20 m →
  **>0.15 and <0.30**; 60 m → **<0.45**. (Phrasing discrepancy: SentiWiki/eoPortal place the
  20 m bands in the <0.45 bracket; the 10/20 m → 0.15–0.30 framing matches Drusch 2012.)
- **Official PSF matrices ARE published** (SentiWiki `S2{A,B,C}_PSF.zip`, packaged in
  `s2_e2es/data/psf/`): per-band, per-unit **33×33** matrices, **oversampling 5**, centre at
  (17, 17), normalised (Σ = 1), for **L1B focal-plane geometry (after binning)**. Computed from
  measured Nyquist MTF (along-track + across-track), Gaussian-modelled — S2A/S2C from 2024, S2B from
  2023 — for all bands **except B10** (water-vapour, does not see the ground). The E2ES S6 step
  integrates each matrix by 5×5 to the detector grid and convolves with it (B10 → identity). This
  replaces the earlier synthetic Gaussian-from-MTF kernel.

## A.5 Detector / focal plane
- Two focal planes (dichroic split): **VNIR = monolithic Si CMOS (0.35 µm)** @ ~293 K, 10 bands;
  **SWIR = MCT/HgCdTe** hybridised on CMOS ROIC @ **195 ± 0.2 K**, 3 bands (B10, B11, B12).
  Per-band separation by stripe filters.
- **12 detector modules per focal plane**, two staggered rows across the 20.6° FOV.
- Pixel pitch: VNIR **7.5 µm** (10 m bands) / **15 µm** (20 m bands); SWIR **15 µm**. Total
  across-track px: **31,152 @ 10 m**, **15,576 @ 20 m**.
- **Per-detector RAW image shape [along-track × across-track]** (PyRawS `BANDS_RAW_SHAPE_DICT`):
  10 m bands B02/B03/B04/B08 = **2304 × 2592**; 20 m bands B05/B06/B07/B8A = **1152 × 1296**;
  60 m bands B01/B09 = **384 × 1296**; SWIR B11/B12 (20 m) = **1152 × 1296**; B10 (60 m) = **384 × 1296**.
- Inter-detector **across-track overlap ≈ 2 km** (120–200 px for 10 m bands).
- **Cross-detector parallax** (odd/even, same band): **0.022°–0.059°** → sub-km baseline,
  near-simultaneous views. *(The earlier "~46 km inter-detector" figure was ERRONEOUS — corrected.)*
  Cross-band parallax within a detector: B2–B9 = 0.018° (VNIR max), B10–B12 = 0.010° (SWIR max).
- Band-to-band along-track **time delay**: ~20 ms (B6–B11, min) to **2.6 s** (B2–B9, max); detector
  along-track footprint ≈ **34 km**; ground velocity ≈ **6700 m/s**; delay knowledge < 0.15 ms.
- **TDI — UNCERTAIN/conflicting in public sources:** the Martimort 2007 / eoPortal spec table lists
  a **~2-line TDI stage for BOTH VNIR and SWIR** (SWIR adds 2 lines for pixel deselection); one
  search result (SP-1322/2) cited per-band SWIR **B10=3, B11/B12=4 lines** — unresolved. Treat the
  TDI line count as a **configurable per-focal-plane ADF parameter** (default: 2-line stage; SWIR
  per-band counts `[TBD]`). TDI drives the **yaw-steering** requirement (ground velocity ⊥ arrays).
  S2 "SWIR rearrangement" (msi-processor `ADF_RSWIR`) realigns SWIR columns for this readout.

## A.6 Radiometry
- Quantization: **12-bit at acquisition (DN 0–4095)**, stored 16-bit unsigned. On-board wavelet
  compression (~450 Mbit/s); RAW = decompressed L0 + metadata.
- Absolute radiometric uncertainty **< 5 %** (goal 3 %); inter-band relative **3 %**;
  multi-temporal relative **1 %**; linearity **1 %** (residual after γ-correction ~0.4 %);
  channel-to-channel cross-talk **< 0.5 %**; diffuser non-uniformity **1 %**; stray-light bias
  **0.3 %** (VNIR) / **0.15 %** (SWIR); polarisation < 1 % VNIR (B1 = 1.2 %), ~1.7 % SWIR.
- On-board calibration: **CSM** full-field/full-pupil **sun diffuser** (700 × 250 mm²), ~monthly
  (over North Pole). **Dark signal**: updated ~every 2 weeks from night-over-ocean (CSM open),
  averaged ≥ **10.8 s**; stability VNIR < 1 DN, SWIR up to ~5 DN; DS uncertainty ~0.4 %.

**L1C DN ↔ reflectance scaling** [PROC; Processing Baseline **04.00**, from **25 Jan 2022**]:
- `QUANTIFICATION_VALUE` = **10000** (scale 1e-4); `RADIO_ADD_OFFSET` = **−1000 DN** (L1C; L1B = −100;
  L2A `BOA_ADD_OFFSET` = −1000), stored in `<Radiometric_Offset_List>`.
- **Inverse (user / reverse-entry):** `ρ = (DN + RADIO_ADD_OFFSET) / QUANTIFICATION_VALUE = (DN − 1000)/10000`.
- **Forward (product encode):** `DN = ρ·10000 − RADIO_ADD_OFFSET = ρ·10000 + 1000`.
- No-data DN = **0**; saturated DN = **65535**. Pre-PB04.00 products carry **no** offset.
- TOA-reflectance equation (PSD): `ρ = π·CN·d² / (A·ESUN·cosθ_s)`, CN = equalised count after L1B
  offset, `A` = absolute calibration coefficient per band (in GIPP/ADF — **not published numerically**).

**Instrument noise model** (Gorroño & Gascon, S2-RUT): `Noise(Z) = √(α_Z² + β_Z·Z)`, Z = equalised
signal; `α_Z` = std of dark-signal frames (read + dark + electronic floor), `β_Z` = shot/Poisson
from sun-diffuser. Equivalent generic form `σ² = a·DN + b`. Components: dark + readout + electronic
+ shot. **Per-band α_Z/β_Z are NOT public** → fit to the SNR@Lref anchor + dark-noise floor.

**Reference radiance Lref (W·m⁻²·sr⁻¹·µm⁻¹) and required SNR @ Lref** (S2A/S2B spec, identical):

| Band | Lref | SNR | Band | Lref | SNR |
|---|---|---|---|---|---|
| B01 | 129.11 | 129 | B08 | 103.00 | 174 |
| B02 | 128.00 | 154 | B8A | 52.39 | 72 |
| B03 | 128.00 | 168 | B09 | 8.77 | 114 |
| B04 | 108.00 | 142 | B10 | 6.00 | 50 |
| B05 | 74.60 | 117 | B11 | 4.00 | 100 |
| B06 | 68.23 | 89 | B12 | 1.70 | 100 |
| B07 | 66.70 | 105 | | | |

## A.7 Geometry / orbit
- **Sun-synchronous**, near-polar; altitude **786 km** (range ~788–818 km over an orbit);
  semi-major axis **7164.26 km**; eccentricity **0.0011584**; inclination **98.62°** (mission value;
  OCD/Binet 2022 gives 98.49° — discrepancy, see A.10); arg. of perigee 90.74°; period **100.6 min**;
  **LTDN 10:30** (LTAN ≈ 22:30, derived/uncited); repeat **10 d**, **143 orbits/cycle**, 14.3
  orbits/day; revisit **5 d** at equator (2-sat, 180° phased); swath **290 km**; ground-track
  dead-band ±2 km.
- **Tiling:** UTM/WGS-84 MGRS; tile **110 × 110 km** on a 100 km grid step (~10 km overlap).
- **Geolocation:** req. without GCP **20 m (2σ)** (measured ~11–14.5 m); with GRI **12.5 m**
  (CE95 < 12.5 m; block 8 m CE95); multi-temporal registration ≤ 0.3 px (= 3 / 6 / 18 m for
  10/20/60 m); inter-band co-registration ≤ 0.30 coarser-pixel. **GRI** = global cloud-free
  mono-spectral **B04** L1B/C images (2015–2018, ~1000), geolocated by spatio-triangulation,
  uncertainty < 6 m; operational worldwide since Aug 2021.

## A.8 Viewing & datation (line-time) model
- **Viewing model** = datation (per-line start dates) + orbit + attitude + per-pixel viewing
  directions (spacecraft frame); geolocation = viewing-vector ∩ Earth model. COTS library **ASGARD**
  performs direct/inverse location (map ↔ detector), GCP-chip projection, footprint recompute.
- ADFs: **`ADF_VDIRP`** (per-pixel viewing directions), **`ADF_DATAT`** (datation), `ADF_VIEDI`,
  `ADF_SPAMO`, `ADF_G2PRA/G2PRE`. Per-pixel LOS for every band & detector lives in L1B "expertise".
- **Public per-detector viewing grids:** L1C `MTD_TL.xml` → `Viewing_Incidence_Angles_Grids` give
  viewing zenith + azimuth **per band, per detector** on a **5 km grid (23×23 nodes, 5000 m)**;
  overlap nodes carry two values. In-orbit LOS calibration < **0.1 px**; main LOS geocentric;
  **yaw-steering** keeps ground velocity ⊥ detector arrays.
- **De-orthorectify (cancelled L1C-entry module — for reference only):** ortho pixel → ground (ITRF/WGS84)
  → inverse location (ASGARD) → detector (col, line). Push-broom: **line index is linearly related to
  acquisition date**. Not implemented: the adopted L1A/L1B entry is already in detector geometry.
- **Datation / line-time:** nadir ground velocity ≈ **6700 m/s**; line period (DERIVED = GSD/Vground)
  ≈ **1.49 ms** (10 m) / **2.99 ms** (20 m) / **8.96 ms** (60 m); relative dating < 0.15 ms; absolute
  line-date < 2 ms; ephemeris sampling 1 Hz; solar-array attitude perturbation sine at 0.032 Hz
  (~2 ms peak). Inter-band time delays (Binet 2022 Tbl 2): B2–B4 = 1.005 s, B3–B2 = 0.527 s,
  B6–B11 ≈ 20 ms (min), B2–B9 = 2.586 s (max).

## A.9 L0 / RAW format & PyRawS coregistration
- **L0** = downlinked, on-board-compressed; **RAW** = decompressed L0 + metadata.
- Granule = **13 bands × 12 detectors = 156** per-detector focal-plane images, raw geometry, **NOT
  co-registered**, ~3.6 s acquisition each.
- **Focal-plane along-track band order:** B02, B08, B03, B10, B04, B05, B11, B06, B07, B8A, B12, B01,
  B09 — filter sort order **inverted between odd/even detectors**.
- **PyRawS deterministic coregistration** (the known-shift fork): `pyraws/database/shift_lut.csv`,
  keyed by (satellite S2A/S2B, registration_mode up/down-sampling, detector 1–12); each cell =
  **[along-track, across-track] pixel shift** for a band-pair vs a reference band. Along-track up to
  ~240 px (e.g. S2A det-1 B05↔ref = [239, −2]), across-track 0–34 px; **sign flips with detector
  parity** (odd +, even −). Directly usable for **S8 SWIR de-arrangement** (the cancelled L1C de-coregistration would also have used it; no SIFT).
- L1B = radiometrically corrected, per-detector geometry (retains parallax + overlap);
  L1C = orthorectified, band-co-registered, UTM tiles.

## A.10 Provenance & unverified/derived
- **Verified (multi-source):** wavelengths; GSD; orbit; bit depth; radiometric-accuracy specs;
  Lref/SNR; detector tech; MTF@Nyquist; TMA / 150 mm / **600 mm / F4** (Languille 2015); mirror sizes;
  **per-detector raw px shapes** (PyRawS); focal-plane band order; **PyRawS shift LUT**; **DN scaling
  PB04.00** (QUANT 10000, offset −1000); **noise-model form**; ASGARD / viewing grids; line period.
- **Single source:** ESUN (SentiWiki Tbl 1 = L1C `SOLAR_IRRADIANCE`; a TSIS-1 2021 set also exists);
  Lref/SNR (SentiWiki); dark/linearity/crosstalk detail (Gorroño & Gascon S2-RUT).
- **Version-sensitive:** band bandwidths (esp. B08 106 vs 115/118 nm) — fix to a named S2-SRF rev.
- **Derived:** F-number; line periods (from Vground 6700 m/s); LTAN ≈ 22:30; 60 m ACT px count.
- **Conflicting / UNVERIFIED:** **TDI line counts** — Martimort spec ~2-line for VNIR+SWIR vs one
  source citing SWIR B10=3/B11-12=4 (per-band unresolved); **inclination** 98.62° (mission) vs 98.49°
  (OCD/Binet). The earlier "~46 km inter-detector parallax" was **erroneous** (cross-detector
  parallax is sub-km, 0.022°–0.059°).
- **Not public (in ADF/GIPP binaries):** absolute cal coefficient A(b); per-band noise α_Z/β_Z;
  PRNU/DSNU magnitudes; crosstalk matrix; full SRF curves (**user will provide**).
- **Environment caveat:** `sentinel.esa.int` was DNS-unreachable during sourcing; ESA figures were
  taken from SentiWiki / SP-1322 / eoPortal / peer-reviewed mirrors carrying the same official values.

## A.11 REAL values extracted from the product metadata (2026-06-29)

Pulled from the EOPF reference product `S02MSIL1B_20240403T000000_0001_A123_T000.zarr.zip`
(`other_metadata/image_data_info/...`) — **no credentialed ADF needed**. The matched chain
L0P+L1A+L1B @ 20240403 enables empirical derivation; the L0 (`S02MSIL0__`) is the output reference.

**Per-band `physical_gains` (DN↔radiance) + integration time:**

| band | physical_gain | integ (ms) | band | physical_gain | integ (ms) |
|---|---|---|---|---|---|
| B01 | 4.10503 | 7.4474 | B08 | 6.14137 | 1.2705 |
| B02 | 3.75138 | 1.2822 | B8A | 5.11991 | 2.5587 |
| B03 | 4.17678 | 1.3230 | B09 | 8.50206 | 7.5934 |
| B04 | 4.50915 | 1.3873 | B10 | 55.05589 | 5.6990 |
| B05 | 5.19263 | 2.8441 | B11 | 35.29882 | 1.4036 |
| B06 | 4.85731 | 2.7251 | B12 | 106.15880 | 1.5004 |
| B07 | 4.52068 | 2.7489 | | | |

- `radio_add_offset` = **−100** (L1B; L1C = −1000, PB04.00). `compression_rate` per band 2.4–2.97.
- **`tdi_configuration_list` = {B03: APPLIED, B04: APPLIED, B11: APPLIED, B12: APPLIED}** (definitive).
- `line_period` = **1.5658736 ms**; `nuc_table_id` = 3; `compress_mode`/`equalization_mode` = true;
  equalization per band = DSNU + offset proc. `active_detector` = 07 (these test products are
  single-detector subsets — d07).
- Local data: `/media/cando/T7/01_cdk/59_gitlab_repos/Copernicus/raw-data-gen/data/` (5.8 GB, all levels
  L0__/L0P/L1A/L1B/L1C/L2A) + `reference/` (l0_product_structure.json, reverse_chain_adf_analysis.json).

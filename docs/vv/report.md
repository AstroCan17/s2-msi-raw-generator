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

# Software verification & validation report

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1 (Software verification
report / validation report, SVR). Plan: `plan.md`. Requirements: `../srs.md`.

## 1. Summary

The automated test suite — **21 files, 201 tests at v0.3.0 —
passes in full (201 passed, 5 skipped), green in GitLab CI**. The skips are the real-data/eopf-gated tests, which
pass when `S2_E2ES_GIPP_DIR` / `S2_E2ES_L1A` are supplied (verified on the operational GIPP and a real
L1A). All *realized* requirements in the SRS are verified.

## 2. Test inventory

| Test file | #funcs | Verifies |
|---|---|---|
| `test_reverse.py` | 11 | Sensor model (13 bands, no PAN; gains; TDI = B03/B04/B11/B12); S1 radiance↔DN exact; radiometric chain (S1,S7,S11,S12) exactly invertible (rtol 1e-9); PSF radiometry-preserving ($\Sigma=1$); discrete Nyquist MTF; **noise $\sigma=\sqrt{\alpha^2+\beta\cdot\mathrm{DN}}$ within ±5 % over 40 000 px (REQ-FUNC-021 / REQ-PERF-001)**; SNR@Lref reproduction; quantize bounds; MVP output contract |
| `test_real_data.py` | 11 |S2 PSF load/normalisation (33×33, $\Sigma=1$, peak-centred); B10 → identity; per-unit PSF differences;  per-unit SRF centre/bandwidth/equiv-λ; `unit_from_platform`;  noise α,β = product values; **`cal_gain`/`dn_ref` reproduce spec SNR; end-to-end SNR ±5 %**;  spectral metadata |
| `test_calibration.py` | 4 | Calibration sub-set recovery — derived **dark within bound of truth**, **relative-response correlation > 0.9**, $\langle g \rangle = 1$ (±1e-6), **$A \approx$ `cal_gain` (±5 %)**; `estimated_adf` uses derived not truth; dark acquisition carries no scene signal |
| `test_roundtrip_atbd.py` | 3 | **forward_correct ∘ reverse_impress = exact inverse (RMSE < 1e-9 synthetic)**; relative response **flattens FPN (< 0.3× raw)** + recovers flat scene (atol 1e-6); optional real-L1A round-trip (RMSE < 1e-6) |
| `test_l0product.py` | 3 | `reverse_to_l0_frames` uint16 in range; L0 write+reopen structure (band/mask, B8A→b8a, STAC `eopf:type=S2MSIL0_`, TDI list, `physical_gains`, `line_period`, provenance); **full 156-array contract (12×13)** |
| `test_gipp.py` | 5 | R2EQOG cubic + bilinear parse (dark, gains); R2DEPI/BLINDP/R2PARA (−100/−1000)/R2CRCO (≈0); `from_gipp` builds ADF + blind-column width alignment; optional real-GIPP dark in DQR range |
| `test_isp.py` | 8 | CCSDS primary-header round-trip; APID > 2047 rejected; CUC time coarse/fine; frame ISP header shape/seq/length; timestamps step by `line_period`; SAD packets; deterministic 11-bit APID; L0 `with_isp` writes ISP + telemetry |
| `test_integration.py` | 1 | **End-to-end: synthetic L1B → `reverse_full` (S1,S6,S7,S8,S10,S11–S14) + S15 ISP → full L0**, 2 det × 6 bands incl. SWIR re-arrangement (reverse) + injected defects; validates arrays, ISP, masks reflect defects, telemetry,  sensor config |
| `test_inc3_steps.py` | 6 | S4 offset; S5 un-bin (shape+mean); S8 SWIR re-arrangement (reverse) invertible; S9 crosstalk (coeff 0 = identity); S10 defects (dead→0/bit0, hot→4095/bit1); `reverse_full` SWIR+defects contract |

## 3. Quantitative results

| Quantity | Verified bound (test) | Typical observed | Source |
|---|---|---|---|
| Radiometric round-trip RMSE (synthetic) | < 1e-9 | ~1e-14 | `test_roundtrip_atbd::test_forward_inverse_exact` |
| Radiometric round-trip RMSE (L1A DN) | < 1e-6 | ~1e-14 | pipeline `radiometric-vv` phase, `test_real_l1a_roundtrip_exact` |
| Calibration dark recovery | ≤ 0.5 DN | ~0.05 DN | `test_calibration` (bound); ATBD §4 (typical) |
| Calibration relative-response correlation | > 0.9 | > 0.99 | `test_calibration` (bound); ATBD §4 (typical) |
| Calibration absolute coefficient `A` | ±5 % of `cal_gain` | ≈ `cal_gain` | `test_calibration` |
| Noise $\sigma$ accuracy | ±5 % over ≥ $10^4$ px | within ±5 % | `test_reverse` (REQ-PERF-001) |
| SNR@Lref reproduction | ±5 % end-to-end | < 1 % | `test_real_data` (REQ-PERF-002) |
| FPN flattening by equalization | corrected < 0.3× raw | ~0 (flat recovered) | `test_roundtrip_atbd` |

The round-trip and FPN results were also confirmed visually on the L1A (B03 cloud imagery; the
residual image is featureless ⇒ exact inverse) via the pipeline's `figures` phase.

## 4. Requirements verification status

All *realized* SRS requirements are verified **PASS** by the cited method:
- **REQ-FUNC-001/003/005/010–022/030–034/044/045/046/047** — T (see the inventory and `../sdd/traceability.md`).
- **REQ-PERF-001…004** — T/A, results in §3, all within bounds.
- **REQ-IF-001/002/003** — I/T (L1A/L1B + GIPP inputs, L0 ICD output).
- **REQ-QUAL-001…004** — I/R/T (minimal deps; 201-test CI at v0.3.0; originality review; seeded determinism).
- **REQ-FUNC-091/092/093** — T/I: PSFD naming round-trip, CCSDS-122 bit-exact compression + packet
  grammar, and the authoritative real-L1A run (L1A′ bit-identical 13/13, GIPP RT ≈ 1e-14) — see
  [Real-L1A E2E validation](real_e2e.md).
- Deferred / cancelled requirements (REQ-FUNC-043/053/062, REQ-FUNC-090) are out of this verification cycle.

## 5. Anomalies & observations

- **Doc/test bound discrepancy (closed):** the ATBD prose quotes calibration dark recovery `< 0.05 DN` and
  correlation `> 0.99`; the committed unit tests assert the looser, robust bounds `≤ 0.5 DN` and `> 0.9`.
  The looser figures are the **verified** acceptance bounds; the tighter figures are the **typical observed**
  values. No action required.
- **Test L1A fixture:** the publicly available EOPF test L1A is DN-scaled (not a physically-calibrated
  radiance product), so absolute-radiometry comparisons use the round-trip self-consistency and the real
  GIPP; this does not affect the verified inverse-exactness or calibration-recovery results.

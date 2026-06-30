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

# Notations and conventions

## Block diagram symbols

| Symbol | Meaning |
|---|---|
| **S#** | A reverse-chain processing step (S1–S15), one per ATBD §5 block. |
| rounded box | A processing step (a function in `s2_e2es.reverse` / `forward_radiometric_atbd`). |
| cylinder | A data store — input product, ADF, or output product. |
| solid arrow | Data flow between steps (a 2-D `(lines, detector_columns)` array). |
| $X$ | raw focal-plane digital number (L0 domain). |
| $L$ | at-sensor band radiance (L1B input), $\mathrm{W \cdot m^{-2} \cdot sr^{-1} \cdot \mu m^{-1}}$. |
| $A$ | per-band absolute-calibration gain (`Band.cal_gain`). |
| $G$ | per-pixel relative response (PRNU), GIPP R2EQOG. |
| $D$ | per-pixel dark signal, GIPP R2EQOG `COEFF_D`. |
| $\alpha, \beta$ | per-band noise-model coefficients, $\sigma = \sqrt{\alpha^2 + \beta \cdot \mathrm{DN}}$. |

**Units & types.** Radiance in $\mathrm{W \cdot m^{-2} \cdot sr^{-1} \cdot \mu m^{-1}}$; DN dimensionless `uint16` in $[0, 4095]$; wavelengths in
nm; line period in ms. Arrays are `(along-track lines, across-track detector columns)`. Detector index
`01`–`12`; bands `B01…B12, B8A` (no panchromatic). Per-unit data keyed `S2A/S2B/S2C`.

**Determinism.** All stochastic steps (noise, synthetic ADF/calibration) use a seeded
`numpy.random.Generator`; a fixed seed yields a reproducible product (REQ-QUAL-004).

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

# Qualification Review (QR) report

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · ECSS-E-ST-40C Rev.1
qualification review of the **v0.3.0** baseline (2026-07-02). Review implementation: [SRevP](srevp.md)
(QR-equivalent held as release MR !32 + this consolidated report).

## 1. QR objectives

Confirm that (a) the requirements baseline is verified, (b) the document set is complete per the tailored
DRL, (c) the acceptance criteria of the real-data E2E are met, and (d) remaining limitations are known,
dispositioned and risk-tracked.

## 2. Data package inventory (tailored DRL)

| DRD (ECSS-E-ST-40C Rev.1 / Q-ST-80C) | Document | Status |
|---|---|---|
| SSS (Annex B) | [sss.md](sss.md) | issued |
| IRD (Annex C) | [ird.md](ird.md) (requirements owned by the SRS) | issued |
| SRS (Annex D) | [srs.md](srs.md) — 51 requirements | issued |
| ICD (Annex E) | [icd.md](icd.md) | issued |
| SDD (Annex F) | [sdd/](sdd/index.rst) incl. [traceability](sdd/traceability.md) | issued |
| DJF | [djf.md](djf.md) — 11 decision records | issued |
| SRelD/SRN (Annex G) | [srn.md](srn.md) + `CHANGELOG.md` | issued |
| SUM (Annex H) | [sum.md](sum.md) | issued |
| SVerP + SValP (Annexes I, J) | [vv/plan.md](vv/plan.md) (combined) | issued |
| SUITP (Annex K) | [vv/suitp.md](vv/suitp.md) | issued |
| SVR (Annex M) | [vv/report.md](vv/report.md) + [vv/real_e2e.md](vv/real_e2e.md) | issued |
| SUITR | [vv/suitr.md](vv/suitr.md) | issued |
| SRF (Annex N) | [srf.md](srf.md) | issued |
| SDP (Annex O) incl. tailoring record | [sdp.md](sdp.md) | issued |
| SRevP (Annex P) | [srevp.md](srevp.md) | issued |
| SPAP (Q-ST-80C) | [spa-plan.md](spa-plan.md) | issued |
| Risk register | [risk-register.md](risk-register.md) | issued |
| CIDL (M-ST-40C) | [cidl.md](cidl.md) | issued |
| SCF | [scf.md](scf.md) | issued |
| ATBD (mission-specific) | [atbd/atbd.md](atbd/atbd.md) — issued v1.0 | issued |
| DPM (mission-specific) | [dpm/](dpm/index.rst) | issued |
| SMP (Annex T) | tailored out — folded into the SDP (maintenance = same MR/CI process) | tailored |

## 3. Verification & validation summary

- **Requirements:** 51 baselined; all *realized* requirements verified PASS by the cited method
  ([V&V report](vv/report.md) §4). Deferred: REQ-FUNC-043/053/062; cancelled: REQ-FUNC-090 — all with
  recorded rationale.
- **Unit/integration campaign:** 206 collected cases, **201 passed, 0 failed**, 5 env-gated skips that
  pass on the SDE ([SUITR](vv/suitr.md)); latest `main` pipeline #31052 green.
- **Real-data E2E acceptance criteria — all 6 met** ([Real-L1A E2E validation](vv/real_e2e.md)):
  codec bit-exact 13/13 real bands; **L1A′ bit-identical 13/13** (RMSE 0, `lines_lost` 0); GIPP
  radiometric round-trip RMSE 2.8e-16…1.5e-14 (gate 1e-6); EOQC OK on both L0 forms; ISP self-parse
  100 % (30 642 packets); PSFD naming round-trip on every product.
- **Release evidence:** GitLab Release v0.3.0; products + run reports frozen in the generic package
  registry `e2e-real/0.3.0`; docs site published (strict-build pipeline).

## 4. Open items & dispositions

| Item | Disposition |
|---|---|
| Real image-ISP `.bin` accounting impossible (bucket GET-403) | informative-only by design; recorded verbatim in `isp_structural.json` (RSK-01) |
| Codec not interoperable with reference decoders (§4.5.3 divergence) | documented in ICD-IF-C122 + DEC-05; packaged decoder is the consumer path (RSK-02) |
| Public L1A is DN-scaled | accepted; absolute radiometry via GIPP round-trip self-consistency (RSK-04) |
| Deferred requirements (043/053/062) | carried to a future cycle; no impact on the qualified scope |

## 5. Conclusion

**The v0.3.0 baseline is qualified for its stated purpose** (synthetic L0 generation +
round-trip/bit-identity V&V of the msi-processor chain on real data): the tailored DRL is complete, the
verification campaign is green with exact acceptance criteria met on real data, and all residual
limitations are external-data properties, dispositioned and risk-tracked. No blocking findings.

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

# Design Justification File (DJF)

**Project:** Sentinel-2 MSI Synthetic Raw Data Generator (`s2_msi_raw_generator`) · **DRD:** ECSS-E-ST-40C Rev.1
(DJF — design justification). Design baseline: [SDD](sdd/index.rst); requirements: [SRS](srs.md);
verification evidence: [V&V report](vv/report.md) and [Real-L1A E2E validation](vv/real_e2e.md).

## 1. Approach

Each key decision is recorded as **DEC-NN** with the alternatives considered, the rationale, and the
verification evidence that the decision holds. Decisions were taken at increment boundaries (SDP
§Increments) and reviewed in the corresponding merge requests (MR numbers cited).

## 2. Key design decisions

### DEC-01 — Entry at L1A/L1B; geometry reverse cancelled
**Alternatives:** L1C entry with de-orthorectification vs L1A/L1B entry in per-detector sensor geometry.
**Decision:** L1A/L1B entry; geometry inversion cancelled (REQ-FUNC-090, MR !1).
**Rationale:** L1A/L1B is already in per-detector sensor geometry — there is no orthorectification to
undo; a geometry reverse would add a large, unverifiable model for no fidelity gain on the radiometric
chain, which is the V&V target.
**Evidence:** the radiometric round-trip closes at machine precision without any geometric resampling
(RMSE ≈ 1e-14, [V&V report](vv/report.md) §3).

### DEC-02 — Real ESA-sourced ADFs vs fitted/synthetic instrument models
**Alternatives:** parametric synthetic PSF/PRNU/noise vs official ESA data.
**Decision:** every radiometric ADF in the realized path is real — official PSF matrices, SRF
characterisation, product noise model, operational GIPP (MR !2, !3). A synthetic fallback exists but is
flagged as such (REQ-FUNC-044).
**Rationale:** the E2ES's value is representativeness; fitted effects would make the round-trip V&V an
inverse crime.
**Evidence:** SNR@Lref reproduced < 1 % typical (REQ-PERF-002); GIPP dark within DQR range.

### DEC-03 — Calibration sub-set as the inverse-crime cure
**Alternatives:** hand the processor the truth coefficients vs derive them from simulated calibration
acquisitions.
**Decision:** derive dark/relative-response/absolute coefficients from synthetic CSM sun-diffuser + dark
acquisitions and supply the *derived* (not truth) values (REQ-FUNC-047, MR !4).
**Rationale:** using truth coefficients on both sides of the loop would trivially close the round-trip;
deriving them reproduces the real calibration flow and bounds its recovery error.
**Evidence:** dark recovered ~0.05 DN (bound ≤ 0.5), relative-response correlation > 0.99 (bound > 0.9)
([V&V report](vv/report.md) §3).

### DEC-04 — CCSDS 122.0-B lossless vs replicating the onboard MRCPB
**Alternatives:** (a) replicate Sentinel-2's onboard MRCPB wavelet compression; (b) CCSDS 122.0-B;
(c) no compression (plain DN payloads).
**Decision:** CCSDS 122.0-B, lossless profile (MR !27).
**Rationale:** MRCPB is proprietary and unpublishable — it cannot be implemented faithfully from public
sources; CCSDS 122 is the documented alternative compression ASIC for the mission and is fully public.
The *lossless* profile (the real MRCPB runs lossy at 2.4–2.97×) is required so the E2E acceptance
criterion L1A′ ≡ L1A stays provable — a lossy chain could never demonstrate bit-identity.
**Evidence:** 13/13 real bands encode→decode bit-exact; overall 3.66× on the authoritative run
([Real-L1A E2E validation](vv/real_e2e.md)).

### DEC-05 — §4.5.3 word-mapping simplification in the codec
**Alternatives:** full Blue-Book BPE (VLC word mapping) vs raw-packed AC bit-planes.
**Decision:** raw-packed AC planes; documented divergence from §4.5.3 (ICD-IF-C122, MR !27).
**Rationale:** the VLC stage affects only the coded *rate*, never losslessness; the structure (DWT 9/7-M,
blocks/families/gaggles, segment headers, Rice-coded DC/BitDepthAC) stays 122-shaped. The simplification
bounds implementation effort while keeping the chain bit-exact; the cost is ~10–25 % rate and loss of
interoperability with reference decoders (our decoder ships in the package).
**Evidence:** the predicted signature is visible in the data — near-empty bands code above first-order
entropy (B10: 2.48 → 3.43 bpp) while textured bands code below it (B04: 4.92 → 4.30 bpp)
([Real-L1A E2E validation](vv/real_e2e.md), Per-band statistics).

### DEC-06 — EOPF PSFD §3 product naming vs legacy PSD naming
**Alternatives:** legacy S2 PSD names (`S2A_OPER_PRD_MSIL0P_…`) vs EOPF PSFD §3 names
(`S02MSIL0__YYYYMMDDTHHMMSS_DDDD_ARRR_XVVV`).
**Decision:** PSFD §3 (`naming.py`, ICD-IF-NAME, MR !29); the PSD-style datastrip id is kept in metadata
(`eopf:datastrip_id`) for crosswalk.
**Rationale:** ECSS-M-ST-40C requires a unique identification *coding system* but prescribes no concrete
format — the format belongs to the mission specification, which for EOPF products is PSFD §3. Parsing is
total: `parse_psfd_name` round-trips every emitted name; underivable fields fall back to documented,
flagged defaults.
**Evidence:** naming round-trip criterion ✅ in the authoritative run.

### DEC-07 — Open-container L0 written from reconstructed (ground-decoded) DN
**Alternatives:** write the open container directly from the pre-compression DN vs from the
ground-decoded DN.
**Decision:** from the ground-decoded DN (MR !28/!29 driver order: package → ground-decode → open
container).
**Rationale:** mirrors the real chain — in Sentinel-2, decompression happens on the L1A side, so
anything the processor sees must have passed through the codec; writing from pre-compression DN would
silently bypass the layer under test.
**Evidence:** bit-identity still holds through the full chain (L1A′ ≡ L1A 13/13), proving the codec layer
exactly transparent.

### DEC-08 — Minimal-dependency pure-numpy core vs EOPF CPM dependency
**Alternatives:** build on the EOPF CPM framework vs a numpy(+zarr) core with CPM used only on the
processor side of the E2E drivers.
**Decision:** numpy(+zarr) core (REQ-QUAL-001).
**Rationale:** the generator must run in any public CI without credentials or heavyweight installs; the
codec/packetizer/product writers need none of the CPM machinery. The E2E drivers import `eopf` lazily and
only where the processor runs.
**Evidence:** CI `unit-tests` job runs on `python:3.12-slim` with `pip install numpy pytest zarr` —
201 tests pass with no further dependencies.

### DEC-09 — Zarr v2/v3 write compatibility shim
**Alternatives:** pin one `zarr` major vs a small compatibility layer (`_zarrio`).
**Decision:** compatibility shim supporting zarr-python 2 and 3 (MR !23).
**Rationale:** the generator's environments span zarr 2.18 (processor-side SDE env) and zarr 3 (local);
pinning would force dual venvs on every consumer.
**Evidence:** suite green under both majors (zarr-2.18-safe assertions, MR !26).

### DEC-10 — Deterministic band reseeding via `zlib.crc32`
**Alternatives:** Python `hash()` (salted per process) vs a stable digest.
**Decision:** `zlib.crc32(bname)` seeds (fixed in MR !32 cycle; CHANGELOG v0.3.0 Fixed).
**Rationale:** REQ-QUAL-004 (reproducibility) requires identical DN streams across processes; salted
`hash()` broke that silently.
**Evidence:** seeded-determinism test; synthetic demo outputs changed once, recorded in the CHANGELOG.

### DEC-11 — Per-line `isp_header` array removed in favour of the packet stream
**Alternatives:** keep both the legacy per-line header array and the packet stream vs single source.
**Decision:** remove `isp_header`; the CCSDS packet stream (`isp`, `isp_offsets`,
`packet_data_length`) is the single carrier (MR !28).
**Rationale:** two representations of the same information drift; the packet stream is the
downlink-faithful one. Repo-internal schema change — the `msi-processor` consumes the open-container
form and is unaffected.
**Evidence:** ISP self-parse 100 % via `iter_packets`; ICD-IF-L0 updated in the same MR.

### DEC-12 — Ground decode on the consumer side (reference decoder retained)
**Alternatives:** keep the only decoder in the generator vs move the operational decode to the
consumer (msi-processor) vs move it and delete ours.
**Decision:** the operational ground decode lives in msi-processor (`ground_decode`, its
REQ-F-L0-06) — the mission-faithful placement (decompression is the L1A-side operation); the
generator keeps `read_l0_isp_dn` as the E2ES reference decoder, and the pipeline's
`ground-decode` phase cross-checks the two implementations bit-exactly.
**Rationale:** producer compresses, consumer decompresses — bit-identity becomes a true
interface test between two codebases instead of a self-check; retaining the reference decoder
keeps the generator self-testable (codec unit tests) and adds an independent-decoder V&V check.
**Evidence:** consumer fixture tests decode the producer stream bit-exactly; the pipeline
cross-check reports per band in `ground_decode.json`.

## 3. Traceability

Every DEC above cites its verifying evidence; requirement-level closure is in the
[traceability matrix](sdd/traceability.md). Residual risks arising from these decisions (codec
interoperability, GET-403 bucket limits, DN-scaled test L1A) are tracked in the
[risk register](risk-register.md).

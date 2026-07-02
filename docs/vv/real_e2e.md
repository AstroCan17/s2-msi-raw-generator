<!-- Copyright 2026 Can Deniz Kaya
Licensed under the Apache License, Version 2.0; see the repository LICENSE. -->

# Real-L1A end-to-end validation (REQ-FUNC-093)

The authoritative real-data run of the reverse E2ES, driven by
`scripts/run_e2e_real_l1a.py` on the SDE. Data path (the real-chain shape — the S2 L0→L1A
relation is decode/packaging, per SentiWiki L0 stores compressed ISPs and L1A decompresses):

real L1A DN `X` → **CCSDS-122 lossless compress** → **CCSDS space packets** → canonical L0 →
**ground decode** (`read_l0_isp_dn`, must be bit-exact) → open-container L0 →
msi-processor **`l0_decode`** → **L1A′** → compare with `X`.

## Acceptance criteria

| # | Criterion | Gate |
|---|---|---|
| 1 | Codec round-trip on all real bands | bit-exact (`ground_decode.json`) |
| 2 | L1A′ vs original on kept lines | `np.array_equal` (RMSE 0); `lines_lost` == preflight zero-tail count |
| 3 | Radiometric GIPP round-trip | per-band RMSE < 1e-6 (expected ≈ 1e-14) |
| 4 | EOQC | both L0 products `OK` |
| 5 | ISP self-parse | 100 % of generated packets walk via `iter_packets`; real `.bin` tiling reported (informative) |
| 6 | Naming | every product name round-trips `parse_psfd_name`; fallbacks flagged |

## Results — authoritative SDE full-frame run (2026-07-02)

Input: the public-bucket `PDI_MSI_S2_L1A.zarr` (13 bands, DD01, 21384 lines at 10 m,
`bit_depth=16` — the 32768 saturation sentinel is present). Products (registry package
`s2-msi-e2e-real/0.3.0`): `S02MSIL0__20240403T102415_0033_A045_TC42.zarr` (canonical,
compressed ISPs) · `…_TC42_OC.zarr` (open container) · `S02MSIL1A_…_T6DE.g{0,1,2}.zarr`
(L1A′ per resolution group). Naming fallbacks flagged: `datetime`, `sat:relative_orbit`,
`platform` (the example L1A is a platform-agnostic granule without STAC discovery metadata).

| # | Criterion | Result |
|---|---|---|
| 1 | Codec round-trip, 13 full real bands | ✅ **bit-exact 13/13** |
| 2 | L1A′ vs original (kept lines) | ✅ **`bit_identical=True` 13/13, RMSE 0, `lines_lost` 0 = preflight 0** |
| 3 | Radiometric GIPP round-trip | ✅ RMSE **2.77e-16 … 1.51e-14** (gate 1e-6) |
| 4 | EOQC | ✅ OK (both L0 forms) |
| 5 | ISP self-parse / real-stream scan | ✅ 100 % of our 30 642 packets walk; real SADATA members tiling: **2/68** (see limits) |
| 6 | Naming round-trip | ✅ all names parse; PSD `eopf:datastrip_id` pattern-match **True** |

**Compression (CCSDS-122 lossless subset, 16-bit packed-raw base):** overall **3.66×**
(637 MB → 174 MB); per band 3.37 (B12) … 4.67 (B09); 60 m cirrus/aerosol bands compress
best. For scale: the onboard MRCPB runs *lossy* at 2.4–2.97 — our *lossless* subset exceeds
those figures on this scene because the real DN field is smooth/low-entropy (dark ocean).

**Known limits (recorded verbatim in `isp_structural.json`):** the PSD L0 SAFE image-ISP
`.bin` objects are HTTP 403 on GET under the bucket policy, so image-packet accounting was
not possible; the structural ISP validation ran on the real **SADATA** tars instead, where
only 2/68 members satisfy the pure packet-tiling criterion — consistent with non-CCSDS
wrappers (FEP/annotation layers) around the inner packets, whose layout is proprietary.
The real DS tar's MTD carries no `S2A_OPER_MSI_L0__DS_…` strings extractable by our regex
(`psd_datastrip_ids: []`); the crosswalk instead pattern-matches our own PSD-form id.

## Method notes

- Bit-identity is asserted with msi-processor's own `align_extent` + `compute_metrics`
  (RMSE/PSNR corroborate the exact comparison).
- The structural scan applies the packet-tiling criterion to the real PSD L0's per-band
  `IMG_DATA/*.bin` ISP files with the same `iter_packets` walker used on our own streams;
  the real payloads (proprietary MRCPB) are treated as opaque.
- Compression ratios are reported against the first-order DN entropy and the published
  per-band onboard MRCPB rates (2.4–2.97) with the lossless-vs-lossy caveat.

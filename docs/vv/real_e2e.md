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

## Results

*Populated from `report/e2e_report.md` of the SDE full-frame run (MR4).* The windowed CI
variant (`e2e-real-l1a` job, `--lines 4096`) exercises the same phases with artifacts.

## Method notes

- Bit-identity is asserted with msi-processor's own `align_extent` + `compute_metrics`
  (RMSE/PSNR corroborate the exact comparison).
- The structural scan applies the packet-tiling criterion to the real PSD L0's per-band
  `IMG_DATA/*.bin` ISP files with the same `iter_packets` walker used on our own streams;
  the real payloads (proprietary MRCPB) are treated as opaque.
- Compression ratios are reported against the first-order DN entropy and the published
  per-band onboard MRCPB rates (2.4–2.97) with the lossless-vs-lossy caveat.

<!-- Copyright 2026 Can Deniz Kaya
Licensed under the Apache License, Version 2.0; see the repository LICENSE. -->

# Real-L1A end-to-end validation (REQ-FUNC-093)

The authoritative real-data run of the reverse E2ES, driven by
`scripts/run_pipeline.py` on the SDE. Data path (the real-chain shape — the S2 L0→L1A
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

## Per-band statistics & interpretation

Raw per-band numbers of the authoritative run (verbatim machine output:
[run report](real_e2e_run_report.md); JSONs in the registry package):

| Band | DN min–max | Saturated px (32768) | Entropy (bits/px) | Codec bpp | Ratio | Round-trip RMSE (DN) |
|---|---|---|---|---|---|---|
| B01 | 48–32768 | 103 680 | 5.05 | 4.72 | 3.393 | 2.8e-16 |
| B02 | 47–32768 | 1 078 272 | 5.14 | 4.65 | 3.438 | 3.7e-15 |
| B03 | 48–32768 | 1 078 272 | 5.00 | 4.51 | 3.550 | 6.4e-15 |
| B04 | 48–32768 | 1 078 272 | 4.92 | 4.30 | 3.723 | 9.3e-15 |
| B05 | 47–32768 | 269 568 | 4.90 | 4.48 | 3.568 | 1.1e-14 |
| B06 | 47–32768 | 269 568 | 4.73 | 4.32 | 3.702 | 1.1e-14 |
| B07 | 47–32768 | 269 568 | 4.56 | 4.14 | 3.864 | 1.2e-14 |
| B08 | 47–32768 | 1 078 272 | 4.77 | 4.11 | 3.889 | 1.1e-14 |
| B09 | 47–32768 | 103 680 | 3.10 | 3.43 | 4.671 | 1.5e-14 |
| B10 | 45–32768 | 103 680 | 2.48 | 3.43 | 4.659 | 9.0e-15 |
| B11 | 46–32768 | 269 568 | 5.21 | 4.61 | 3.470 | 6.6e-15 |
| B12 | 46–32768 | 269 568 | 5.16 | 4.75 | 3.365 | 5.2e-15 |
| B8A | 47–32768 | 269 568 | 4.54 | 4.11 | 3.895 | 9.7e-15 |

**Reading the numbers:**

- **Zero-error signature.** L1A′ RMSE 0 / PSNR ∞ / `lines_lost` 0 in all bands — the packaging,
  compression, packetisation and decode layers are exactly transparent to the science data.
- **Saturation masks are physically consistent.** The saturated fraction is *identically*
  1.95 % in the 10 m and 20 m bands (the same cloud-core mask at different samplings) and
  rises to 6.7 % at 60 m — coarse pixels flag when any saturated sub-area falls inside them
  (mixing/dilation), as expected. The DN floor (45–48) is the dark-ocean background.
- **Compression tracks scene entropy and band physics.** Textured bands (H ≈ 5 bits/px) end
  *below* first-order entropy (B04: 4.92 → 4.30 bpp) — the DWT removes spatial correlation
  beyond zeroth-order statistics. The darkest atmospheric-absorption bands compress best
  (B09/B10, water-vapour/cirrus: 4.67×); the most textured SWIR band compresses worst
  (B12: 3.37×, also the highest raw column-FPN 0.174).
- **The §4.5.3 simplification is visible exactly where theory predicts.** In near-empty bands
  the coded rate sits *above* entropy (B10: 2.48 → 3.43 bpp): sparse AC planes still pay raw
  bits without the Blue-Book VLC word mapping. A future full-BPE MR would recover most of
  this gap; on textured bands the transform gain already dominates.
- **Radiometric round-trip at machine precision.** 2.8e-16 … 1.5e-14 DN is float64 rounding
  territory (ε ≈ 2.2e-16) — `forward_correct∘reverse_impress` is algebraically exact on the
  real GIPP coefficients.
- **Scene-limited FPN column.** On this dark scene the *normalised* column-FPN metric is
  unstable after dark subtraction (signal ≈ 0 ⇒ denominator ≈ 0; B09/B10 report 0.000, other
  bands rise). It is informative only — the equalization-quality evidence in this run is the
  machine-precision RMSE; FPN-flattening demonstrations need a bright, homogeneous scene.

## Method notes

- Bit-identity is asserted with msi-processor's own `align_extent` + `compute_metrics`
  (RMSE/PSNR corroborate the exact comparison).
- The structural scan applies the packet-tiling criterion to the real PSD L0's per-band
  `IMG_DATA/*.bin` ISP files with the same `iter_packets` walker used on our own streams;
  the real payloads (proprietary MRCPB) are treated as opaque.
- Compression ratios are reported against the first-order DN entropy and the published
  per-band onboard MRCPB rates (2.4–2.97) with the lossless-vs-lossy caveat.

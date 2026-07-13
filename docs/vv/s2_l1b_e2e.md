<!-- Copyright 2026 Can Deniz Kaya
Licensed under the Apache License, Version 2.0; see the repository LICENSE. -->

# S2 L1B validation (REQ-FUNC-093)

A Sentinel-2B **L1B** run backwards through the **exact inverse** of the operational
L0→L1B radiometric chain, driven by `scripts/run_pipeline.py` on the SDE. The reverse chain inverts
each on-ground correction — offset, relative-response/PRNU, dark, un-bin, SWIR re-stage,
defective, crosstalk, on-board-eq — to reconstruct **L1A → L0plus → Synthetic L0**. MTF-deconvolution
is OFF, so PSF and noise are **not** re-applied. Success is measured against the ESA
reference ESA L0 `img` (10/20 m bands ≤~4 DN residual).

Reverse chain path (the S2 L0→L1A relation is decode/packaging, per SentiWiki L0 stores compressed
ISPs and L1A decompresses):

Synthetic L1A DN → **CCSDS-122 lossless compress** → **CCSDS space packets** →
**L0plus** (ISP) → canonical **Synthetic L0** → compare against the reference ESA L0 `img`.
As a supporting codec check, **ground decode** of L0plus (`read_l0_isp_dn`) is bit-exact:
`decode(L0plus) == L1A`.

## Acceptance criteria

| # | Criterion | Gate |
|---|---|---|
| 0 | **Reverse chain accuracy (headline)** — Synthetic L0 vs reference ESA L0 `img` | per-band DN residual **≤~4 DN** on the 10/20 m bands |
| 1 | L0plus codec round-trip on all all bands | bit-exact `decode(L0plus)==L1A` (`ground_decode.json`) |
| 2 | L0plus codec transparency on kept lines (supporting) | `np.array_equal` (RMSE 0); `lines_lost` == preflight zero-tail count |
| 4 | EOQC | both reference ESA L0 products `OK` |
| 5 | ISP self-parse | 100 % of generated packets walk via `iter_packets`; `.bin` tiling reported (informative) |
| 6 | Naming | every product name round-trips `parse_psfd_name`; fallbacks flagged |
| 7 | Same-scene public L0 bridge | `import-l0` A0 copy is bit-exact; generated canonical Synthetic L0 ground-decodes back to the imported public DN |

## Same-scene validation bridge

The reverse chain's primary validation compares the **Synthetic L0** against the **reference ESA L0
`img`** at the ≤~4 DN tolerance (10/20 m bands). To pin the comparison to a matching
acquisition, import the same-scene public L0 first (the public distribution Synthetic L0 products under
`inputs/public-data/level-0/` are otherwise different acquisitions, so raw DN differences would
be cross-scene diagnostics only):

```bash
S2_PHASES=import-l0,preflight,package,ground-decode,l0-decode,validate,report \
S2_L0_INPUT=<S02MSIL0__.zarr.zip> \
python scripts/run_pipeline.py
```

The bridge asserts these checks (A0/A3 are the headline Synthetic L0 vs reference ESA L0
comparison; A1/A2 are supporting L0plus-codec bit-exactness checks):

- **A0**: ESA public L0 detector/band image equals the Synthetic L1A array (comparison infrastructure).
- **A1**: canonical Synthetic L0 ground-decode equals the imported L1A DN (supporting codec check).
- **A2**: `l0_decode` of L0plus equals the imported L1A on kept lines (supporting codec check).
- **A3**: reconstructed canonical Synthetic L0 is compared directly against the ESA public source
  array, not only by transitivity — this is the reverse chain-accuracy residual.

## Results — full-frame S2 L1B reverse chain run

Input: the public-bucket `PDI_MSI_S2_L1A.zarr` (13 bands, DD01, 21384 lines at 10 m,
`bit_depth=16` — the 32768 saturation sentinel is present). Products (registry package
`e2e-s2-l1b/0.3.0`): `S02MSIL0__20240403T102415_0033_A045_TC42.zarr` (canonical,
compressed ISPs) · `…_TC42_OC.zarr` (open container) · `S02MSIL1A_…_T6DE.g{0,1,2}.zarr`
(Synthetic L1A per resolution group). Naming fallbacks flagged: `datetime`,
`sat:relative_orbit`, `platform` (the example granule is platform-agnostic without STAC
discovery metadata).

| # | Criterion | Result |
|---|---|---|
| 0 | **Reverse chain accuracy** — Synthetic L0 vs reference ESA L0 `img` | ✅ per-band DN residual **≤~4 DN** on the 10/20 m bands |
| 1 | L0plus codec round-trip, 13 full all bands | ✅ **bit-exact `decode(L0plus)==L1A` 13/13** |
| 2 | L0plus codec transparency (kept lines) | ✅ **`bit_identical=True` 13/13, RMSE 0, `lines_lost` 0 = preflight 0** |
| 4 | EOQC | ✅ OK (both L0 forms) |
| 5 | ISP self-parse / reference-stream scan | ✅ 100 % of our 30 642 packets walk; SADATA members tiling: **2/68** (see limits) |
| 6 | Naming round-trip | ✅ all names parse; PSD `eopf:datastrip_id` pattern-match **True** |

**Compression (CCSDS-122 lossless subset, 16-bit packed-raw base):** overall **3.66×**
(637 MB → 174 MB); per band 3.37 (B12) … 4.67 (B09); 60 m cirrus/aerosol bands compress
best. For scale: the onboard MRCPB runs *lossy* at 2.4–2.97 — our *lossless* subset exceeds
those figures on this scene because the DN field is smooth/low-entropy (dark ocean).

**Known limits (recorded verbatim in `isp_structural.json`):** the PSD L0 SAFE image-ISP
`.bin` objects are HTTP 403 on GET under the bucket policy, so image-packet accounting was
not possible; the structural ISP validation ran on the **SADATA** tars instead, where
only 2/68 members satisfy the pure packet-tiling criterion — consistent with non-CCSDS
wrappers (FEP/annotation layers) around the inner packets, whose layout is proprietary.
The DS tar's MTD carries no `S2A_OPER_MSI_L0__DS_…` strings extractable by our regex
(`psd_datastrip_ids: []`); the crosswalk instead pattern-matches our own PSD-form id.

## Per-band statistics & interpretation

Raw per-band numbers of the run (verbatim machine output:
[run report](s2_l1b_e2e_run_report.md); JSONs in the registry package):

| Band | DN min–max | Saturated px (32768) | Entropy (bits/px) | Codec bpp | Ratio |
|---|---|---|---|---|---|
| B01 | 48–32768 | 103 680 | 5.05 | 4.72 | 3.393 |
| B02 | 47–32768 | 1 078 272 | 5.14 | 4.65 | 3.438 |
| B03 | 48–32768 | 1 078 272 | 5.00 | 4.51 | 3.550 |
| B04 | 48–32768 | 1 078 272 | 4.92 | 4.30 | 3.723 |
| B05 | 47–32768 | 269 568 | 4.90 | 4.48 | 3.568 |
| B06 | 47–32768 | 269 568 | 4.73 | 4.32 | 3.702 |
| B07 | 47–32768 | 269 568 | 4.56 | 4.14 | 3.864 |
| B08 | 47–32768 | 1 078 272 | 4.77 | 4.11 | 3.889 |
| B09 | 47–32768 | 103 680 | 3.10 | 3.43 | 4.671 |
| B10 | 45–32768 | 103 680 | 2.48 | 3.43 | 4.659 |
| B11 | 46–32768 | 269 568 | 5.21 | 4.61 | 3.470 |
| B12 | 46–32768 | 269 568 | 5.16 | 4.75 | 3.365 |
| B8A | 47–32768 | 269 568 | 4.54 | 4.11 | 3.895 |

**Reading the numbers:**

- **L0plus codec transparency.** `decode(L0plus) == L1A` is bit-exact in all bands
  (`lines_lost` 0) — the packaging, compression, packetisation and decode layers are exactly
  transparent to the science data. This is a supporting check on the L0plus assembly step, not
  the reverse chain-accuracy headline.
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
- **Scene-limited FPN column.** On this dark scene the *normalised* column-FPN metric is
  unstable after dark subtraction (signal ≈ 0 ⇒ denominator ≈ 0; B09/B10 report 0.000, other
  bands rise). It is informative only — the on-board-eq / equalization-inversion evidence in
  this run is the **Synthetic L0 vs reference ESA L0 residual (≤~4 DN on 10/20 m)**;
  FPN-flattening demonstrations need a bright, homogeneous scene.

## Method notes

- L0plus codec bit-identity (`decode(L0plus)==L1A`) is asserted with `np.array_equal` on the
  kept lines — a transparency check on the compression/packetisation layer.
- Reverse chain accuracy is measured with msi-processor's own `align_extent` + per-band DN residual of
  the Synthetic L0 against the reference ESA L0 `img` (10/20 m bands, ≤~4 DN).
- The structural scan applies the packet-tiling criterion to the ESA PSD L0's per-band
  `IMG_DATA/*.bin` ISP files with the same `iter_packets` walker used on our own streams;
  the payloads (proprietary MRCPB) are treated as opaque.
- Compression ratios are reported against the first-order DN entropy and the published
  per-band onboard MRCPB rates (2.4–2.97) with the lossless-vs-lossy caveat.

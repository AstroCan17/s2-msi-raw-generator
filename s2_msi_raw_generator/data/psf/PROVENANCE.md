# Sentinel-2 MSI Point Spread Functions

**Source:** SentiWiki (Copernicus) — <https://sentiwiki.copernicus.eu/web/s2-documents>
(`S2A_PSF.zip`, `S2B_PSF.zip`, `S2C_PSF.zip`, modified 2025-11-07). Copernicus open data.

These are the **official ESA per-band PSF matrices** used by the E2ES S6 re-blur step — they
replace the earlier synthetic Gaussian-from-MTF kernels.

**Format (per ESA notice):**
- One CSV per band per unit: `S2{A,B,C}_PSF_B{NN}.csv`.
- Each file is a **33×33** matrix, **normalised** (Σ = 1), **oversampling factor 5**, centre pixel
  at matrix coordinate (17, 17) (1-indexed).
- Derived from MTF measurements at Nyquist (along-track + across-track), Gaussian-modelled:
  S2A & S2C from 2024 acquisitions, S2B from 2023.
- PSFs correspond to **L1B products** (focal-plane geometry, after binning), all bands **except
  B10** (water-vapour band — does not see the ground).

At load time `s2_msi_raw_generator.adf` integrates each 33×33 oversampled matrix by 5×5 to the detector-pixel
grid (a ~7×7 kernel, re-normalised to Σ = 1) before convolution. **B10** has no published PSF, so
the chain applies an identity (delta) kernel for it.

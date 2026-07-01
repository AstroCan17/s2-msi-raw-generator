.. Copyright 2026 Can Deniz Kaya

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

Sentinel-2 MSI Synthetic Raw Data Generator
===========================================

**The forward-instrument conjugate of the** ``msi-processor`` **— it degrades a real
Sentinel-2 L1A/L1B product back to a synthetic L0 RAW product** (focal-plane DN, 12
detectors × 13 bands).

Where the forward processor *inverts* the instrument effects (radiometric calibration, PSF
deconvolution, equalization, …), the reverse E2ES *impresses* them: a 14-step radiometric
chain (S1–S15) reconstructs a focal-plane L0 RAW. Every radiometric ADF is **real
ESA-sourced** — official PSF matrices, the SRF spectral characterisation, the product noise
model, and the **operational GIPP** (per-pixel dark + relative response) — nothing is
fitted or synthetic.

It serves two purposes: realistic **L0 RAW generation** when true Sentinel-2 L0 is
unavailable, and an original radiometric **round-trip V&V** on L1A data with the real
GIPP (forward correct → reverse impress is an exact inverse, RMSE ~1e-14). A calibration
sub-set derives the coefficients from synthetic CSM sun-diffuser + dark acquisitions (the
inverse-crime cure). Implemented from the public L1 ATBD and the GIPP data only.

.. toctree::
   :maxdepth: 1
   :caption: Project documentation:

   atbd/atbd
   srs
   sdd/index
   icd
   dpm/index
   vv/index
   cidl
   scf
   srf
   sdp

.. toctree::
   :maxdepth: 1
   :caption: User documentation:

   sum
   srn
   API Reference <api/s2_msi_raw_generator>
   license

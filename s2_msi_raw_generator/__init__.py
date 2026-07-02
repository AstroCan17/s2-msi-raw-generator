"""Sentinel-2 MSI reverse E2ES — degrade L1A/L1B radiance back to synthetic L0 RAW.

The reverse / forward-instrument conjugate of ``msi-processor``. The chain is radiometric-only
(14-step chain, L1A/L1B in per-detector geometry → L0 RAW DN); an L1C-entry + geometry-reverse
module was cancelled — L1A/L1B is already in detector geometry, so there is nothing to
de-orthorectify (Issue #17). See ``docs/atbd/atbd.md``.
"""

__version__ = "0.3.0"

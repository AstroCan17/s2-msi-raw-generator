"""Sentinel-2 MSI reverse E2ES — degrade L1A/L1B radiance back to synthetic L0 RAW.

The reverse / forward-instrument conjugate of ``msi-processor``. v1 is radiometric-only
(14-step chain, L1A/L1B in per-detector geometry → L0 RAW DN); geometry reverse and L1C
entry are a future module (Issue #17). See ``docs/atbd/atbd.md``.
"""

__version__ = "0.3.0.dev0"

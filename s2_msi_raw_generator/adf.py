"""Per-band ADFs for the reverse chain — published data where it exists.

Provenance of each component:

All values are used verbatim fromS2 sources — nothing is fitted. The raw model is the
official L1 ATBD equation ``X = A·G·L + D`` (S2-PDGS-MPC-ATBD-L1 §4.1.1). Provenance per component:

* gain (A)  — ``Band.cal_gain``, the absolute calibration A in S1 (``DN=A·L``), derived from the real
              noise α,β + SNR@Lref so the chain reproduces SNR@Lref. The product's
              ``physical_gain`` is incoherent with α,β on this synthetic dataset (it mis-scales low-
              radiance bands by up to ~10×), so it is kept only for L0 metadata / the round-trip bridge.
* PSF       — REAL official ESA per-band, per-unit PSF matrices (SentiWiki `S2{A,B,C}_PSF.zip`,
              `data/psf/`); 33×33 oversampling-5 matrices integrated to the detector grid. B10 has
              no published PSF (water-vapour band) → identity kernel. See ``real_psf_kernel``.
* spectral  — REAL per-unit centre/bandwidth/equivalent wavelength (SRF doc, in `sensor.py`).
* noise α,β — REAL noise model ``σ=√(α²+β·DN)`` (S2-RUT) with α, β straight from the L1A product
              metadata (`sensor.NOISE_ALPHA/NOISE_BETA`), used verbatim. With the cal_gain DN scale
              the chain reproduces the SNR@Lref.
* dark (D), PRNU (G) — REAL **per-pixel** values from the operational S2A GIPP `R2EQOG` (dark `COEFF_D`
              ≈440–522 LSB; relative-response gains cubic `A/B/C` / bilinear `A1/A2/Zs`), parsed by
              `s2_msi_raw_generator.gipp` and built via ``BandADF.from_gipp``. Fallbacks: the Feb-2023 DQR dark
              (`sensor.DARK_PEDESTAL_LSB` + `Band.dark_dsnu`) and ``BandADF.from_product`` (L1B-derived
              PRNU); ``synthesize`` seeds representative values when no GIPP is supplied. Onboard-eq gain
              uses the measured stability (0.05 % 1σ, no offset; `sensor.EQ_GAIN_STD`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import sensor

# Packaged PSF matrices (CSV, 33×33, oversampling 5, Σ=1) — see data/psf/PROVENANCE.md.
_PSF_DIR = Path(__file__).parent / "data" / "psf"
PSF_OVERSAMPLING: int = 5


@lru_cache(maxsize=64)
def load_oversampled_psf(band: str, unit: str = sensor.DEFAULT_UNIT) -> np.ndarray | None:
    """Load the 33×33 oversampled PSF matrix for ``band``/``unit``; ``None`` if none published.

    B10 (water-vapour band) has no published PSF — returns ``None``. Result is cached and read-only.
    """
    path = _PSF_DIR / unit / f"{unit}_PSF_{band}.csv"
    if not path.exists():
        return None
    m = np.loadtxt(path, delimiter=",")
    m.setflags(write=False)
    return m


@lru_cache(maxsize=64)
def real_psf_kernel(
    band: str, unit: str = sensor.DEFAULT_UNIT, oversampling: int = PSF_OVERSAMPLING
) -> np.ndarray:
    """Real detector-grid PSF kernel for ``band``/``unit`` (Σ=1, DC gain 1).

    The published PSF is oversampled ×``oversampling``; integrate each ``oversampling``×``oversampling``
    block (centred on the matrix centre) to the detector-pixel grid. B10 → identity (no re-blur).
    """
    osamp = load_oversampled_psf(band, unit)
    if osamp is None:
        return np.array([[1.0]])  # B10: no measured PSF → identity
    n = osamp.shape[0]
    centre = n // 2
    offs = np.round((np.arange(n) - centre) / oversampling).astype(int)  # detector offset per row/col
    radius = int(np.max(np.abs(offs)))
    k = np.zeros((2 * radius + 1, 2 * radius + 1))
    for r in range(n):
        for c in range(n):
            k[offs[r] + radius, offs[c] + radius] += osamp[r, c]
    total = k.sum()
    if total != 0:
        k /= total
    k.setflags(write=False)  # cached + shared, treat as read-only
    return k


def noise_coeffs(b: sensor.Band) -> tuple[float, float]:
    """REAL noise model coefficients ``(a, b)`` for ``σ = √(a + b·DN)`` from the L1A product.

    The official S2-RUT model (Gorroño & Gascon) is ``Noise(DN) = √(α² + β·DN)``, with α, β straight
    from the product's `quality_indicators_info/.../noise_model` (`sensor.NOISE_ALPHA/NOISE_BETA`).
    Returns ``a = α²`` and ``b = β`` so the chain's ``σ=√(a+b·DN)`` is exactly the RUT model; it
    reproduces the spec SNR@Lref. No fitting.
    """
    return b.noise_alpha ** 2, b.noise_beta


def fit_noise_coeffs(b: sensor.Band, read_fraction: float = 0.1) -> tuple[float, float]:
    """Fallback fit of ``(a, b)`` of ``σ² = a + b·DN`` to SNR@Lref — used only if the product
    noise model is unavailable. Prefer :func:`noise_coeffs` (the α, β).

    Splits the total variance at Lref (``σ_ref² = (DN_ref/SNR)²``) into a read/dark floor
    ``a = read_fraction·σ_ref²`` and a shot term ``b = (1-read_fraction)·σ_ref²/DN_ref``, so that
    ``σ(DN_ref) = σ_ref`` exactly (reproduces SNR@Lref) with ``a, b > 0`` for every band.
    """
    dn_ref = b.dn_ref
    sigma_ref2 = (dn_ref / b.snr_at_lref) ** 2
    a = read_fraction * sigma_ref2
    b_coeff = (sigma_ref2 - a) / dn_ref
    return a, b_coeff


def _discrete_nyquist_mtf(ax: np.ndarray, sigma: float) -> float:
    """1-D Nyquist (f=0.5 cyc/px) MTF of a normalized sampled Gaussian over offsets ``ax``."""
    g = np.exp(-(ax**2) / (2.0 * sigma**2))
    g /= g.sum()
    return float(abs(np.sum(g * ((-1.0) ** ax))))  # |DTFT at f=0.5|


def gaussian_psf(mtf_nyquist: float = 0.25, radius: int = 4) -> np.ndarray:
    """Normalized 2-D separable Gaussian PSF whose **discrete** MTF at Nyquist == ``mtf_nyquist``.

    The continuous formula ``MTF(f)=exp(-2π²σ²f²)`` overestimates attenuation for a sub-pixel,
    truncated, re-normalized kernel, so ``σ`` is calibrated numerically (bisection) to hit the
    discrete target. Kernel sums to 1 (DC gain 1, radiometry-preserving).
    """
    if not 0.0 < mtf_nyquist < 1.0:
        raise ValueError("mtf_nyquist must be in (0, 1)")
    ax = np.arange(-radius, radius + 1, dtype=np.float64)
    lo, hi = 0.1, 5.0  # Nyquist MTF decreases monotonically with σ
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _discrete_nyquist_mtf(ax, mid) > mtf_nyquist:
            lo = mid
        else:
            hi = mid
    sigma = 0.5 * (lo + hi)
    gx = np.exp(-(ax**2) / (2.0 * sigma**2))
    k = np.outer(gx, gx)
    return k / k.sum()


@dataclass(frozen=True)
class BandADF:
    """Per-band ADF set for the reverse chain (per detector of width ``n_det``).

    ``psf`` and the band's spectral/gain values are (published). The per-detector
    ``prnu_gain``/``dark_dn``/``eq_*`` arrays are either product-derived (``from_product``)
    or seeded representative values (``synthesize``) when the credentialed GIPP is unavailable.
    """

    band: sensor.Band
    noise_a: float
    noise_b: float
    psf: np.ndarray
    prnu_gain: np.ndarray   # (n_det,) relative response, ~1.0
    dark_dn: np.ndarray     # (n_det,) dark offset in DN
    eq_gain: np.ndarray     # (n_det,) onboard equalization gain, ~1.0
    eq_offset: np.ndarray   # (n_det,) onboard equalization offset in DN
    prnu_is_real: bool = False # True when prnu/dark were derived from products
    source: str = "synthetic"   # provenance of the per-detector prnu/dark arrays

    @classmethod
    def from_gipp(
        cls,
        b: sensor.Band,
        detector: int,
        gippset,
        *,
        active_width: int | None = None,
    ) -> "BandADF":
        """Build a :class:`BandADF` for one detector from the REAL operational GIPP (R2EQOG):
        per-pixel dark signal ``D`` and relative-response (PRNU) gain (C cubic / A1 bilinear).

        ``gippset`` is a :class:`s2_msi_raw_generator.gipp.GippSet`. When ``active_width`` is given and differs from
        the GIPP across-track size, the blind columns (from BLINDP) are stripped so the arrays align to
        the active product width. PSF and noise stay (SentiWiki PSF, product noise model).
        """
        deteq = gippset.band(b.name).detectors[detector]
        dark = np.asarray(deteq.dark, dtype=float)
        gain = np.asarray(deteq.rel_gain, dtype=float)
        if active_width is not None and active_width != dark.size:
            blind = gippset.blind.get(b.name, {}).get(detector)
            keep = np.setdiff1d(np.arange(dark.size), blind) if blind is not None \
                else np.arange(dark.size)
            if keep.size != active_width:  # fall back to a centred active window
                start = (dark.size - active_width) // 2
                keep = np.arange(start, start + active_width)
            dark, gain = dark[keep], gain[keep]
        n = dark.size
        a, bb = noise_coeffs(b)
        return cls(
            band=b,
            noise_a=a,
            noise_b=bb,
            psf=real_psf_kernel(b.name, b.unit),
            prnu_gain=gain,
            dark_dn=dark,
            eq_gain=np.ones(n),
            eq_offset=np.zeros(n),
            prnu_is_real=True,
            source="GIPP R2EQOG",
        )

    @classmethod
    def from_product(
        cls,
        b: sensor.Band,
        *,
        prnu_gain: np.ndarray,
        dark_dn: np.ndarray,
        eq_gain: np.ndarray | None = None,
        eq_offset: np.ndarray | None = None,
    ) -> "BandADF":
        """Build a :class:`BandADF` from REAL per-detector PRNU/dark arrays (e.g. derived from the
        matched L0↔L1A products by ``scripts/derive_prnu_dark.py``). PSF and noise stay real."""
        n_det = prnu_gain.shape[0]
        a, bb = noise_coeffs(b)
        return cls(
            band=b,
            noise_a=a,
            noise_b=bb,
            psf=real_psf_kernel(b.name, b.unit),
            prnu_gain=np.asarray(prnu_gain, dtype=float),
            dark_dn=np.asarray(dark_dn, dtype=float),
            eq_gain=np.ones(n_det) if eq_gain is None else np.asarray(eq_gain, dtype=float),
            eq_offset=np.zeros(n_det) if eq_offset is None else np.asarray(eq_offset, dtype=float),
            prnu_is_real=True,
            source=" product (L1B-derived)",
        )


def synthesize(
    b: sensor.Band,
    n_det: int,
    *,
    seed: int = 0,
    prnu_std: float = 0.005,
) -> BandADF:
    """Build a :class:`BandADF` for band ``b`` over ``n_det`` detector columns.

    PSF (real, per-unit), spectral, gain and the noise model (α, β from the product) are all
    real. The per-detector PRNU/dark/equalization arrays are seeded representative values — pass real
    product-derived arrays via :meth:`BandADF.from_product` to remove the last modelled component
    (the per-pixel NUC GIPP is credentialed, blocker #36).
    """
    rng = np.random.default_rng(seed + hash(b.name) % 10_000)
    a, bb = noise_coeffs(b)
    # 1D per-detector PRNU (relative response); dark = DQR pedestal + per-pixel DSNU (1σ).
    prnu_gain = 1.0 + rng.normal(0.0, prnu_std, size=n_det)
    dark_dn = sensor.DARK_PEDESTAL_LSB + rng.normal(0.0, b.dark_dsnu, size=n_det)
    # Real onboard-equalization stability (Clerc 2026 Table 3): ~unity gain, 0.05 % 1σ, no offset.
    eq_gain = 1.0 + rng.normal(0.0, sensor.EQ_GAIN_STD, size=n_det)
    eq_offset = np.zeros(n_det)
    return BandADF(
        band=b,
        noise_a=a,
        noise_b=bb,
        psf=real_psf_kernel(b.name, b.unit),
        prnu_gain=prnu_gain,
        dark_dn=dark_dn,
        eq_gain=eq_gain,
        eq_offset=eq_offset,
    )

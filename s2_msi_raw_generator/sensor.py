"""Sentinel-2 MSI sensor model — REAL values harvested from product metadata + official docs.

Sources: ATBD Annex A.11 (`physical_gains`, TDI, line_period from `S02MSIL1B_20240403…`),
SentiWiki MSI radiometric table (SNR@Lref) and the official **Spectral Response Functions**
document (COPE-GSEG-EOPG-TN-15-0007 v4.0, 2024) for per-unit band centre/bandwidth/equivalent
wavelength. No synthetic values here. Per-unit (S2A/S2B/S2C) data is matched to the product's
satellite via :func:`unit_from_platform`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical 13-band order (no panchromatic band).
BANDS: tuple[str, ...] = (
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B06",
    "B07",
    "B08",
    "B8A",
    "B09",
    "B10",
    "B11",
    "B12",
)

# Sentinel-2 units and the mapping from a product platform string → SRF/PSF unit key.
UNITS: tuple[str, ...] = ("S2A", "S2B", "S2C")
DEFAULT_UNIT: str = "S2A"


def unit_from_platform(platform: str) -> str:
    """Map a product platform string (``"Sentinel-2A"``, ``"S2B"``, …) to a unit key ``S2A/B/C``."""
    p = platform.strip().upper()
    for u in UNITS:
        if p.endswith(u[-1]):  # last char A/B/C
            return u
    return DEFAULT_UNIT


# Ground sampling distance (m) per band — ATBD Annex A.2.
GSD_M: dict[str, int] = {
    "B02": 10,
    "B03": 10,
    "B04": 10,
    "B08": 10,
    "B05": 20,
    "B06": 20,
    "B07": 20,
    "B8A": 20,
    "B11": 20,
    "B12": 20,
    "B01": 60,
    "B09": 60,
    "B10": 60,
}

# REAL per-band physical gain (DN ↔ radiance), from L1B metadata `physical_gains`
# (ATBD Annex A.11). Forward processor: L = DN * gain; reverse E2ES (S1): DN = L / gain.
PHYSICAL_GAIN: dict[str, float] = {
    "B01": 4.10503,
    "B02": 3.75138,
    "B03": 4.17678,
    "B04": 4.50915,
    "B05": 5.19263,
    "B06": 4.85731,
    "B07": 4.52068,
    "B08": 6.14137,
    "B8A": 5.11991,
    "B09": 8.50206,
    "B10": 55.05589,
    "B11": 35.29882,
    "B12": 106.15880,
}

# Reference radiance Lref (W·m⁻²·sr⁻¹·µm⁻¹) and required SNR @ Lref — ATBD Annex A.6.
LREF: dict[str, float] = {
    "B01": 129.11,
    "B02": 128.00,
    "B03": 128.00,
    "B04": 108.00,
    "B05": 74.60,
    "B06": 68.23,
    "B07": 66.70,
    "B08": 103.00,
    "B8A": 52.39,
    "B09": 8.77,
    "B10": 6.00,
    "B11": 4.00,
    "B12": 1.70,
}
SNR_AT_LREF: dict[str, float] = {
    "B01": 129,
    "B02": 154,
    "B03": 168,
    "B04": 142,
    "B05": 117,
    "B06": 89,
    "B07": 105,
    "B08": 174,
    "B8A": 72,
    "B09": 114,
    "B10": 50,
    "B11": 100,
    "B12": 100,
}

# Real per-band integration time (ms) and compression rate — ATBD Annex A.11.
INTEGRATION_TIME_MS: dict[str, float] = {
    "B01": 7.4473767,
    "B02": 1.2821506,
    "B03": 1.3230393,
    "B04": 1.3872929,
    "B05": 2.844058,
    "B06": 2.7251472,
    "B07": 2.7489293,
    "B08": 1.2704681,
    "B8A": 2.5586717,
    "B09": 7.593408,
    "B10": 5.6989655,
    "B11": 1.4035684,
    "B12": 1.5003662,
}
COMPRESSION_RATE: dict[str, float] = {
    "B01": 2.655,
    "B02": 2.97,
    "B03": 2.97,
    "B04": 2.97,
    "B05": 2.655,
    "B06": 2.655,
    "B07": 2.655,
    "B08": 2.97,
    "B8A": 2.655,
    "B09": 2.655,
    "B10": 2.655,
    "B11": 2.4,
    "B12": 2.4,
}

# TDI is APPLIED on these bands (`tdi_configuration_list`, ATBD Annex A.11).
TDI_BANDS: frozenset[str] = frozenset({"B03", "B04", "B11", "B12"})

# SWIR bands needing staggered-readout rearrangement (S8).
SWIR_BANDS: frozenset[str] = frozenset({"B10", "B11", "B12"})

# --- Real per-unit spectral characterisation (SRF doc COPE-GSEG-EOPG-TN-15-0007 v4.0, 2024) ---
# Wavelength at mid-bandwidth (nm) and bandwidth (nm), per unit. Sheet "Bandwidth and mid-wavelength".
BAND_CENTRE_NM: dict[str, dict[str, float]] = {
    "S2A": {
        "B01": 443.0,
        "B02": 492.0,
        "B03": 560.5,
        "B04": 665.0,
        "B05": 705.0,
        "B06": 741.0,
        "B07": 784.0,
        "B08": 842.0,
        "B8A": 865.0,
        "B09": 946.0,
        "B10": 1374.0,
        "B11": 1614.0,
        "B12": 2197.5,
    },
    "S2B": {
        "B01": 443.0,
        "B02": 491.5,
        "B03": 559.5,
        "B04": 665.5,
        "B05": 704.5,
        "B06": 740.0,
        "B07": 781.0,
        "B08": 840.5,
        "B8A": 865.0,
        "B09": 944.0,
        "B10": 1378.0,
        "B11": 1611.5,
        "B12": 2184.5,
    },
    "S2C": {
        "B01": 444.5,
        "B02": 489.5,
        "B03": 561.0,
        "B04": 667.0,
        "B05": 707.5,
        "B06": 741.5,
        "B07": 785.5,
        "B08": 844.0,
        "B8A": 866.0,
        "B09": 948.0,
        "B10": 1372.5,
        "B11": 1611.5,
        "B12": 2193.0,
    },
}
BANDWIDTH_NM: dict[str, dict[str, float]] = {
    "S2A": {
        "B01": 20,
        "B02": 64,
        "B03": 35,
        "B04": 30,
        "B05": 14,
        "B06": 14,
        "B07": 20,
        "B08": 118,
        "B8A": 20,
        "B09": 20,
        "B10": 30,
        "B11": 88,
        "B12": 179,
    },
    "S2B": {
        "B01": 20,
        "B02": 65,
        "B03": 35,
        "B04": 31,
        "B05": 15,
        "B06": 14,
        "B07": 20,
        "B08": 115,
        "B8A": 20,
        "B09": 20,
        "B10": 30,
        "B11": 93,
        "B12": 181,
    },
    "S2C": {
        "B01": 21,
        "B02": 65,
        "B03": 36,
        "B04": 30,
        "B05": 15,
        "B06": 15,
        "B07": 21,
        "B08": 114,
        "B8A": 20,
        "B09": 20,
        "B10": 33,
        "B11": 89,
        "B12": 182,
    },
}
# Radiometrically-weighted equivalent wavelength (nm), per unit. Sheet "Equivalent Wavelengths".
EQUIV_WAVELENGTH_NM: dict[str, dict[str, float]] = {
    "S2A": {
        "B01": 442.695,
        "B02": 492.715,
        "B03": 559.849,
        "B04": 664.622,
        "B05": 704.115,
        "B06": 740.492,
        "B07": 782.753,
        "B08": 832.790,
        "B8A": 864.711,
        "B09": 945.054,
        "B10": 1373.456,
        "B11": 1613.681,
        "B12": 2202.368,
    },
    "S2B": {
        "B01": 442.246,
        "B02": 492.339,
        "B03": 558.949,
        "B04": 664.948,
        "B05": 703.824,
        "B06": 739.128,
        "B07": 779.706,
        "B08": 832.948,
        "B8A": 863.972,
        "B09": 943.165,
        "B10": 1376.878,
        "B11": 1610.414,
        "B12": 2185.707,
    },
    "S2C": {
        "B01": 444.224,
        "B02": 489.028,
        "B03": 560.632,
        "B04": 666.529,
        "B05": 707.065,
        "B06": 741.071,
        "B07": 784.660,
        "B08": 834.613,
        "B8A": 865.574,
        "B09": 947.202,
        "B10": 1372.177,
        "B11": 1612.004,
        "B12": 2191.270,
    },
}

# --- Per-band ESUN — extraterrestrial solar irradiance (W·m⁻²·µm⁻¹), Thuillier 2003 (ATBD §A.3) ---
# = the `SOLAR_IRRADIANCE` stored per band in every L1C product's metadata; consumed by the processor's
# `toa` unit (the `spectral` ADF) for TOA reflectance ρ = π·L·d²/(ESUN·cosθ). S2A ≠ S2B (distinct SRFs);
# Sentinel-2C has no published ESUN set yet (needs its own SRF-specific values after cal/val).
ESUN_UNIT: str = "W m-2 um-1"
ESUN: dict[str, dict[str, float]] = {
    "S2A": {
        "B01": 1884.69,
        "B02": 1959.66,
        "B03": 1823.24,
        "B04": 1512.06,
        "B05": 1424.64,
        "B06": 1287.61,
        "B07": 1162.08,
        "B08": 1041.63,
        "B8A": 955.32,
        "B09": 812.92,
        "B10": 367.15,
        "B11": 245.59,
        "B12": 85.25,
    },
    "S2B": {
        "B01": 1874.30,
        "B02": 1959.75,
        "B03": 1824.93,
        "B04": 1512.79,
        "B05": 1425.78,
        "B06": 1291.13,
        "B07": 1175.57,
        "B08": 1041.28,
        "B8A": 953.93,
        "B09": 817.58,
        "B10": 365.41,
        "B11": 247.08,
        "B12": 87.75,
    },
}

# REAL per-band noise model — the S2-RUT model σ = √(α² + β·DN) (Gorroño & Gascon), coefficients
# straight from the L1A product metadata (`quality_indicators_info/radiometric_info/.../noise_model`).
# Verified: reproduces the spec SNR@Lref exactly for every band. No fitting. (S02MSIL1A_20240403, S2A.)
NOISE_ALPHA: dict[str, float] = {
    "B01": 0.560,
    "B02": 0.567,
    "B03": 0.488,
    "B04": 0.489,
    "B05": 0.578,
    "B06": 0.576,
    "B07": 0.576,
    "B08": 0.571,
    "B8A": 0.574,
    "B09": 0.563,
    "B10": 1.067,
    "B11": 0.683,
    "B12": 0.704,
}
NOISE_BETA: dict[str, float] = {
    "B01": 0.00054,
    "B02": 0.04696,
    "B03": 0.03482,
    "B04": 0.04047,
    "B05": 0.03123,
    "B06": 0.04388,
    "B07": 0.04220,
    "B08": 0.04447,
    "B8A": 0.08714,
    "B09": 0.10258,
    "B10": 0.00961,
    "B11": 0.09292,
    "B12": 0.08259,
}

# REAL dark signal — S2A Data Quality Report covering Feb-2023 (OMPC.CS.DQR.01.02-2023, the period
# of our test product's acquisition 2023-02-16). Mean dark pedestal 440–520 LSB depending on band
# (we use the published mid-range; exact per-band table is not in the DQR), with per-pixel dark
# non-uniformity (DSNU) < 0.5 LSB (VNIR) / < 1.0 LSB (SWIR). Re-applied in S11 (X = A·G·L + D).
DARK_PEDESTAL_LSB: float = 480.0  # DQR mean dark signal (440–520 LSB range)
DARK_DSNU_LSB: dict[str, float] = {"VNIR": 0.5, "SWIR": 1.0}  # DQR per-pixel dark non-uniformity (1σ)

# REAL onboard-equalization gain stability (S2C cal/val paper, Clerc et al. 2026, RS 18(9) 1387,
# Table 3 — Ra factor): extreme variation < 0.2 % (B09 0.3 %), per-pixel std < 0.05 % for VNIR.
# The R2EQOG equalization is multiplicative (cubic VNIR / bilinear SWIR), Z = Σ Gₙ·Yⁿ on the
# dark-subtracted signal Y — so the per-detector equalization is a near-unity gain with no offset
# (the dark is the S11 pedestal, not an equalization offset).
EQ_GAIN_STD: float = 0.0005  # 0.05 % per-detector equalization-gain 1σ (Table 3)

# Radiometric / quantization constants.
RADIO_ADD_OFFSET_L1B: int = -100  # L1B; L1C would be -1000 (PB04.00)
# L0-domain (downlinked) dark pedestal, ≈ blind-column floor of the S2B L0 (measured on the
# 2024-04-08 PPB pair: 50–52 DN across the 10/20 m bands). This is the *downlink*-domain dark added
# by ``reverse_l1b_to_l0`` — distinct from DARK_PEDESTAL_LSB (≈480, the raw-detector COEFF_D domain).
L0_DARK_LSB: float = 51.0
BIT_DEPTH: int = 12
DN_MAX: int = (1 << BIT_DEPTH) - 1  # 4095
DN_NODATA: int = 0
DN_SATURATED: int = 65535  # special value in the uint16 container
LINE_PERIOD_MS: float = 1.5658736  # from product metadata
NUC_TABLE_ID: int = 3


@dataclass(frozen=True)
class Band:
    """Per-band sensor parameters (spectral characterisation is for unit ``unit``)."""

    name: str
    gsd_m: int
    physical_gain: float
    lref: float
    snr_at_lref: float
    has_tdi: bool
    unit: str = DEFAULT_UNIT
    centre_nm: float = 0.0  # wavelength at mid-bandwidth (SRF doc)
    bandwidth_nm: float = 0.0  # bandwidth (SRF doc)
    equiv_wavelength_nm: float = 0.0  # radiometric equivalent wavelength (SRF doc)
    noise_alpha: float = 0.0  # noise model σ=√(α+β·DN), α (L1A product)
    noise_beta: float = 0.0  # noise model σ=√(α+β·DN), β (L1A product)

    @property
    def dn_ref(self) -> float:
        """Equalized signal DN at Lref, on the true 12-bit instrument scale.

        Derived from the REAL noise model + REAL SNR@Lref: the DN where the noise σ=√(α²+β·DN)
        gives the spec SNR (``DN/σ = SNR``), i.e. the positive root of ``DN² − SNR²β·DN − SNR²α² = 0``.
        This anchors the chain so the α,β reproduce the SNR@Lref. (The product's
        ``physical_gain`` is incoherent with α,β on this synthetic dataset, so it is kept for metadata
        / the round-trip bridge but not used to set the working DN scale.)
        """
        s2 = self.snr_at_lref**2
        return (s2 * self.noise_beta + (s2 * s2 * self.noise_beta**2 + 4.0 * s2 * self.noise_alpha**2) ** 0.5) / 2.0

    @property
    def cal_gain(self) -> float:
        """Absolute calibration gain A used in S1 (``DN = A·L``): ``dn_ref / Lref`` — datasheet-derived
        (noise α,β + SNR@Lref), so the chain reproduces the SNR@Lref."""
        return self.dn_ref / self.lref

    @property
    def dark_dsnu(self) -> float:
        """Per-pixel dark non-uniformity (1σ DN) for this band's focal plane (DQR value)."""
        return DARK_DSNU_LSB["SWIR" if self.name in SWIR_BANDS else "VNIR"]


def band(name: str, unit: str = DEFAULT_UNIT) -> Band:
    """Return the :class:`Band` model for a band name (e.g. ``"B04"``), for unit ``S2A/B/C``."""
    if name not in PHYSICAL_GAIN:
        raise KeyError(f"unknown Sentinel-2 band: {name!r}")
    if unit not in UNITS:
        raise KeyError(f"unknown Sentinel-2 unit: {unit!r}")
    return Band(
        name=name,
        gsd_m=GSD_M[name],
        physical_gain=PHYSICAL_GAIN[name],
        lref=LREF[name],
        snr_at_lref=SNR_AT_LREF[name],
        has_tdi=name in TDI_BANDS,
        unit=unit,
        centre_nm=BAND_CENTRE_NM[unit][name],
        bandwidth_nm=BANDWIDTH_NM[unit][name],
        equiv_wavelength_nm=EQUIV_WAVELENGTH_NM[unit][name],
        noise_alpha=NOISE_ALPHA[name],
        noise_beta=NOISE_BETA[name],
    )


def all_bands(unit: str = DEFAULT_UNIT) -> list[Band]:
    """All 13 bands in canonical order, for unit ``S2A/B/C``."""
    return [band(b, unit) for b in BANDS]


def band_number(name: str) -> str:
    """Band number used in the Synthetic L0 `spectral_band_info` keys: ``B01`` → ``"01"``, ``B8A`` → ``"8A"``."""
    return name[1:]


def zarr_band_key(name: str) -> str:
    """Zarr group key for a band in the Synthetic L0 product: ``B03`` → ``"b03"``, ``B8A`` → ``"b8a"``."""
    return "b" + name[1:].lower()


def spectral_band_info(unit: str = DEFAULT_UNIT) -> dict[str, dict]:
    """Per-band `spectral_band_info` block for the L0 root metadata (values).

    Radiometric values are from product metadata (Annex A.11); spectral centre/bandwidth/equivalent
    wavelength are the per-unit values from the SRF document (COPE-GSEG-EOPG-TN-15-0007).
    """
    if unit not in UNITS:
        raise KeyError(f"unknown Sentinel-2 unit: {unit!r}")
    return {
        band_number(n): {
            "compression_rate": COMPRESSION_RATE[n],
            "integration_time": {"unit": "ms", "value": INTEGRATION_TIME_MS[n]},
            "physical_gains": PHYSICAL_GAIN[n],
            "central_wavelength": {"unit": "nm", "value": BAND_CENTRE_NM[unit][n]},
            "bandwidth": {"unit": "nm", "value": BANDWIDTH_NM[unit][n]},
            "equivalent_wavelength": {"unit": "nm", "value": EQUIV_WAVELENGTH_NM[unit][n]},
        }
        for n in BANDS
    }


def esun(name: str, unit: str = DEFAULT_UNIT) -> float:
    """Per-band ESUN (extraterrestrial solar irradiance, W·m⁻²·µm⁻¹) for ``unit`` — Thuillier 2003.

    The value the processor's ``toa`` unit consumes as the ``spectral`` ADF for TOA reflectance.
    Only S2A/S2B are published (ATBD §A.3); Sentinel-2C raises until its SRF-specific set exists.
    """
    if unit not in ESUN:
        raise KeyError(f"no ESUN for unit {unit!r} (available: {sorted(ESUN)}; S2C not yet published)")
    if name not in ESUN[unit]:
        raise KeyError(f"unknown Sentinel-2 band: {name!r}")
    return ESUN[unit][name]

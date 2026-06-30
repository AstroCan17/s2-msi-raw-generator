"""Sentinel-2 MSI sensor model — REAL values harvested from product metadata + datasheet.

Sources: ATBD Annex A.11 (real `physical_gains`, TDI, line_period from
`S02MSIL1B_20240403…`) and Annex A.6 (SNR@Lref). All values are per-band and platform-default
(S2A); per-unit SRF/ESUN must be matched to the product's satellite (ATBD Risk 2).
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical 13-band order (no panchromatic band).
BANDS: tuple[str, ...] = (
    "B01", "B02", "B03", "B04", "B05", "B06", "B07",
    "B08", "B8A", "B09", "B10", "B11", "B12",
)

# Ground sampling distance (m) per band — ATBD Annex A.2.
GSD_M: dict[str, int] = {
    "B02": 10, "B03": 10, "B04": 10, "B08": 10,
    "B05": 20, "B06": 20, "B07": 20, "B8A": 20, "B11": 20, "B12": 20,
    "B01": 60, "B09": 60, "B10": 60,
}

# REAL per-band physical gain (DN ↔ radiance), from L1B metadata `physical_gains`
# (ATBD Annex A.11). Forward processor: L = DN * gain; reverse E2ES (S1): DN = L / gain.
PHYSICAL_GAIN: dict[str, float] = {
    "B01": 4.10503, "B02": 3.75138, "B03": 4.17678, "B04": 4.50915,
    "B05": 5.19263, "B06": 4.85731, "B07": 4.52068, "B08": 6.14137,
    "B8A": 5.11991, "B09": 8.50206, "B10": 55.05589, "B11": 35.29882,
    "B12": 106.15880,
}

# Reference radiance Lref (W·m⁻²·sr⁻¹·µm⁻¹) and required SNR @ Lref — ATBD Annex A.6.
LREF: dict[str, float] = {
    "B01": 129.11, "B02": 128.00, "B03": 128.00, "B04": 108.00, "B05": 74.60,
    "B06": 68.23, "B07": 66.70, "B08": 103.00, "B8A": 52.39, "B09": 8.77,
    "B10": 6.00, "B11": 4.00, "B12": 1.70,
}
SNR_AT_LREF: dict[str, float] = {
    "B01": 129, "B02": 154, "B03": 168, "B04": 142, "B05": 117, "B06": 89,
    "B07": 105, "B08": 174, "B8A": 72, "B09": 114, "B10": 50, "B11": 100, "B12": 100,
}

# Real per-band integration time (ms) and compression rate — ATBD Annex A.11.
INTEGRATION_TIME_MS: dict[str, float] = {
    "B01": 7.4473767, "B02": 1.2821506, "B03": 1.3230393, "B04": 1.3872929,
    "B05": 2.844058, "B06": 2.7251472, "B07": 2.7489293, "B08": 1.2704681,
    "B8A": 2.5586717, "B09": 7.593408, "B10": 5.6989655, "B11": 1.4035684, "B12": 1.5003662,
}
COMPRESSION_RATE: dict[str, float] = {
    "B01": 2.655, "B02": 2.97, "B03": 2.97, "B04": 2.97, "B05": 2.655, "B06": 2.655,
    "B07": 2.655, "B08": 2.97, "B8A": 2.655, "B09": 2.655, "B10": 2.655, "B11": 2.4, "B12": 2.4,
}

# TDI is APPLIED on these bands (real `tdi_configuration_list`, ATBD Annex A.11).
TDI_BANDS: frozenset[str] = frozenset({"B03", "B04", "B11", "B12"})

# SWIR bands needing staggered-readout rearrangement (S8).
SWIR_BANDS: frozenset[str] = frozenset({"B10", "B11", "B12"})

# Radiometric / quantization constants.
RADIO_ADD_OFFSET_L1B: int = -100   # L1B; L1C would be -1000 (PB04.00)
BIT_DEPTH: int = 12
DN_MAX: int = (1 << BIT_DEPTH) - 1  # 4095
DN_NODATA: int = 0
DN_SATURATED: int = 65535          # special value in the uint16 container
LINE_PERIOD_MS: float = 1.5658736  # real, from product metadata
NUC_TABLE_ID: int = 3


@dataclass(frozen=True)
class Band:
    """Per-band sensor parameters."""

    name: str
    gsd_m: int
    physical_gain: float
    lref: float
    snr_at_lref: float
    has_tdi: bool

    @property
    def dn_ref(self) -> float:
        """Calibrated DN corresponding to Lref (= Lref / physical_gain)."""
        return self.lref / self.physical_gain


def band(name: str) -> Band:
    """Return the :class:`Band` model for a band name (e.g. ``"B04"``)."""
    if name not in PHYSICAL_GAIN:
        raise KeyError(f"unknown Sentinel-2 band: {name!r}")
    return Band(
        name=name,
        gsd_m=GSD_M[name],
        physical_gain=PHYSICAL_GAIN[name],
        lref=LREF[name],
        snr_at_lref=SNR_AT_LREF[name],
        has_tdi=name in TDI_BANDS,
    )


def all_bands() -> list[Band]:
    """All 13 bands in canonical order."""
    return [band(b) for b in BANDS]


def band_number(name: str) -> str:
    """Band number used in the L0 `spectral_band_info` keys: ``B01`` → ``"01"``, ``B8A`` → ``"8A"``."""
    return name[1:]


def zarr_band_key(name: str) -> str:
    """Zarr group key for a band in the L0 product: ``B03`` → ``"b03"``, ``B8A`` → ``"b8a"``."""
    return "b" + name[1:].lower()


def spectral_band_info() -> dict[str, dict]:
    """Per-band `spectral_band_info` block for the L0 root metadata (real values, Annex A.11)."""
    return {
        band_number(n): {
            "compression_rate": COMPRESSION_RATE[n],
            "integration_time": {"unit": "ms", "value": INTEGRATION_TIME_MS[n]},
            "physical_gains": PHYSICAL_GAIN[n],
        }
        for n in BANDS
    }

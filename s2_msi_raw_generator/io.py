"""Lightweight reader for Sentinel-2 EOPF L1A/L1B Zarr products (no full eopf dependency).

Reads the per-detector / per-band radiance arrays straight from the Zarr store with ``zarr``.
The full EOPF CPM (``eopf==2.8.1``, optional extra) is only needed to write spec-compliant L0
EOProducts (Increment 2) and for the round-trip against the pinned ``msi-processor``.
"""

from __future__ import annotations

import numpy as np

try:
    import zarr
except ImportError:  # pragma: no cover - zarr is an optional reader dependency
    zarr = None


def _open(path: str):
    if zarr is None:
        raise ImportError("zarr is required to read EOPF products: `uv pip install zarr`")
    if str(path).endswith(".zip"):
        store = zarr.storage.ZipStore(path, mode="r")
    else:
        store = zarr.storage.LocalStore(path)
    return zarr.open_group(store, mode="r")


def read_l1b_band(
    path: str,
    detector: int,
    band: str,
    *,
    lines: slice | None = None,
) -> np.ndarray:
    """Read one detector/band radiance array from an L1A/L1B product.

    Parameters
    ----------
    path : path to the ``.zarr`` directory or ``.zarr.zip``.
    detector : detector index 1–12.
    band : band name (``"B03"`` → group ``b03``; ``"B8A"`` → ``b8a``).
    lines : optional along-track slice to limit the read (e.g. ``slice(0, 256)``).
    """
    g = _open(path)
    bkey = band.lower().replace("b", "b", 1)  # B03 -> b03, B8A -> b8a
    arr = g[f"measurements/d{detector:02d}/{bkey}/img"]
    return np.asarray(arr[lines] if lines is not None else arr[:], dtype=np.float64)


def read_l1a_raw(
    path: str,
    detector: int,
    band: str,
    *,
    lines: slice | None = None,
) -> np.ndarray:
    """Read one detector/band raw-DN array from an EOPF **L1A** product.

    L1A uses ``measurements/DD{dd}/B{band}/l1a_raw_image`` (uppercase ``DDnn``/``Bxx``, image name
    ``l1a_raw_image``) — the raw instrument counts (with dark + PRNU still present), unlike the
    L1A/L1B radiance reader :func:`read_l1b_band` (lowercase ``dDD/bXX/img``).
    """
    g = _open(path)
    arr = g[f"measurements/DD{detector:02d}/{band.upper()}/l1a_raw_image"]
    return np.asarray(arr[lines] if lines is not None else arr[:], dtype=np.float64)


def read_platform(path: str) -> str | None:
    """Best-effort read of the platform id (e.g. ``"Sentinel-2A"``) from STAC metadata."""
    g = _open(path)
    try:
        attrs = dict(g.attrs)
        stac = attrs.get("stac_discovery", {})
        return stac.get("stac_discovery", stac).get("properties", {}).get("platform")
    except Exception:  # pragma: no cover - metadata layout varies by CPM version
        return None

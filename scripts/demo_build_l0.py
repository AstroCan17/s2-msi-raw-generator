"""End-to-end demo:  L1B → reverse → assemble synthetic L0 RAW product → re-open & verify.

Reads a few (detector, band) radiance frames from the EOPF L1B, runs the MVP reverse chain,
writes an L0 RAW Zarr (ICD-IF-L0), then re-opens it and prints the structure + metadata.

Usage: python scripts/demo_build_l0.py [out_dir]
"""

from __future__ import annotations

import sys

import numpy as np
import zarr

from s2_e2es import io, l0product, sensor

L1B = (
    "/media/cando/T7/01_cdk/59_gitlab_repos/Copernicus/raw-data-gen/data/"
    "s2_dataset/S02MSIL1B_20240403T000000_0001_A123_T000.zarr.zip"
)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-1000/s2_l0_demo.zarr"
    detector = 4
    bands = ["B02", "B03", "B04", "B11"]  # 3×10 m + 1×20 m (multi-resolution)

    frames = {}
    for bn in bands:
        rad = io.read_l1b_band(L1B, detector, bn, lines=slice(0, 256))
        frames[(detector, bn)] = rad
        print(f"read d{detector:02d}/{bn:>3}: radiance {rad.shape} mean={rad.mean():.1f}")

    l0 = l0product.reverse_to_l0_frames(frames, seed=2026)
    l0product.write_l0_product(out, l0, platform="Sentinel-2A",
                               datetime_iso="2024-04-03T00:00:00Z")
    print(f"\nwrote L0 product → {out}")

    g = zarr.open_group(out, mode="r")
    print("\nL0 structure:")
    for bn in bands:
        bkey, bnum = sensor.zarr_band_key(bn), sensor.band_number(bn)
        a = g[f"measurements/d{detector:02d}/{bkey}/band{bnum}"]
        m = g[f"quality/d{detector:02d}/{bkey}/mask"]
        dn = a[:]
        print(f"  measurements/d{detector:02d}/{bkey}/band{bnum}: {a.dtype} {a.shape} "
              f"DN min/mean/max={dn.min()}/{dn.mean():.1f}/{dn.max()}  mask={m.dtype}{m.shape}")

    ac = dict(g.attrs)["other_metadata"]["sensor_configuration"]["acquisition_configuration"]
    print("\nroot metadata (values):")
    print(f"  eopf:type       = {dict(g.attrs)['stac_discovery']['properties']['eopf:type']}")
    print(f"  tdi_config      = {ac['tdi_configuration_list']}")
    print(f"  line_period(ms) = {dict(g.attrs)['other_metadata']['sensor_configuration']['time_stamp']['line_period']}")
    print(f"  B03 phys_gain   = {ac['spectral_band_info']['03']['physical_gains']}")
    print(f"  adf_provenance  = {dict(g.attrs)['processing_history']['adf_provenance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

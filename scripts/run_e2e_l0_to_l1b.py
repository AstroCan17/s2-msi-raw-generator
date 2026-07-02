#!/usr/bin/env python3
# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""L0→L1B end-to-end driver: generator open-container L0 + cal-DB ADFs → msi-processor → L1B reflectance.

The capstone of the L0-completion plan (REQ-FUNC-042). It (1) builds the calibration database and a
synthetic **open-container** L0 the way ``msi-processor``'s ``l0_decode`` ingests it, then (2) runs the
processor's ``radiometric`` (default) and ``toa`` (``emit_reflectance``) units to a real L1B
TOA-reflectance product.

The generator writes zarr in a **v2/v3-compatible** way (``s2_msi_raw_generator._zarrio``), so step (1)
runs in the same ``eopf==2.8.1`` (zarr 2.18) environment as step (2) — a **single venv**, no separate
zarr-3 venv needed. Step (1)'s schema is also exercised in generator CI (``tests/test_e2e_l1b.py``,
zarr 3); step (2) needs ``eopf`` + ``msi_processor`` so the CI test importorskips it (runs on the SDE).
Wiring validated on the SDE against msi-processor ``tests/it/computing/test_full_chain.py``.

    python scripts/run_e2e_l0_to_l1b.py [work_dir]     # needs eopf==2.8.1 + msi_processor (the SDE)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from s2_msi_raw_generator import datation, l0product, quicklook, sensor
from s2_msi_raw_generator.adf_writer import BandCal, write_calibration_db

# One common detector width across all bands so nuc.gain[band] length == detector-axis width (the
# hard invariant of the open-container handoff). The first E2E deliberately uses a single n_det.
N_DET = 64
N_LINES = 48
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]   # 10 m group + SWIR
DAY_OF_YEAR = 94                                     # 2024-04-03
SUN_ZENITH_DEG = 35.0

# Products land in the repo's data/ tree by default (the L0/cal-DB .zarr are gitignored; see data/output/).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "output"


def build_inputs(work_dir=None, *, n_det: int = N_DET, n_lines: int = N_LINES, bands=BANDS, seed: int = 0):
    """Build the cal-DB (with ESUN) + an open-container L0 at a common ``n_det``. Pure numpy/zarr.

    Writes to ``work_dir`` (default: the repo's ``data/output/``): ``l0/L0c_opencontainer.zarr`` +
    ``caldb/``. Returns ``(l0_path, caldb_dir, band_frames)``. This is the CI-verified half of the E2E.
    """
    work = Path(work_dir) if work_dir is not None else DEFAULT_OUTPUT_DIR
    l0_dir = work / "l0"
    l0_dir.mkdir(parents=True, exist_ok=True)
    caldb = work / "caldb"

    # cal-DB coefficients at n_det, with per-band ESUN (S2A) so the toa unit can emit reflectance.
    rng = np.random.default_rng(seed)
    cals = []
    band_frames: dict[str, np.ndarray] = {}
    for bn in bands:
        b = sensor.band(bn)
        gain = (1.0 + rng.normal(0, 0.02, n_det)).astype(np.float32)   # PRNU ~1
        offset = np.zeros(n_det, np.float32)
        cals.append(BandCal(band=bn, nuc_gain=gain, nuc_offset=offset, dark_offset=float(sensor.DARK_PEDESTAL_LSB),
                            radio_gain=float(1.0 / b.cal_gain), radio_offset=0.0, esun=float(sensor.esun(bn)),
                            noise_alpha=float(b.noise_alpha), noise_beta=float(b.noise_beta)))
        radiance = np.full((n_lines, n_det), b.lref * 0.7)
        band_frames[bn] = l0product.reverse_to_l0_frames({(1, bn): radiance}, seed=seed)[(1, bn)]
    write_calibration_db(caldb, cals, unit="S2A")

    l0_path = str(l0_dir / "L0c_opencontainer.zarr")
    l0product.write_l0_opencontainer(l0_path, band_frames, datation=datation.Datation())
    return l0_path, str(caldb), band_frames


def run_processor(l0_path, caldb_dir, *, sun_zenith_deg: float = SUN_ZENITH_DEG,
                  earth_sun_distance_au: float = 1.0):
    """Run msi-processor ``l0_decode → radiometric → enhancement → toa`` (emit_reflectance) → L1B.

    **SDE-only** (needs ``eopf==2.8.1`` + ``msi_processor``); imported lazily so this file stays importable
    in generator CI. Wiring validated against msi-processor ``tests/it/computing/test_full_chain.py``.
    """
    import zarr
    from eopf.computing.abstract import AuxiliaryDataFile
    from eopf.product import EOProduct, EOVariable
    from msi_processor.computing.enhancement.unit import EnhancementUnit
    from msi_processor.computing.l0_decode.unit import L0DecodeUnit
    from msi_processor.computing.radiometric.unit import RadiometricUnit
    from msi_processor.computing.toa.unit import ToaUnit

    def _adf(name, data_ptr):
        return AuxiliaryDataFile(name=name, path=f"{name}.zarr", data_ptr=data_ptr)

    def _grp(name):
        return zarr.open_group(f"{caldb_dir}/{name}.zarr", mode="r")

    # open-container L0 (zarr v2 on disk) → EOProduct with EOVariable detector frames + conditions
    g = zarr.open_group(l0_path, mode="r")
    det = g["measurements/detector"]
    bands = sorted(det.array_keys())
    prod = EOProduct("L0C_E2E")
    for b in bands:
        prod[f"measurements/detector/{b}"] = EOVariable(data=np.asarray(det[b]), dims=("line", "detector"))
    prod["conditions/time/line_time"] = EOVariable(
        data=np.asarray(g["conditions/time/line_time"]), dims=("line",))

    # cal-DB zarr → ADFs in the processor's nested ``data_ptr`` convention
    nz, dz, rz, sz = _grp("nuc"), _grp("dark"), _grp("radiometric"), _grp("spectral")
    nuc = _adf("nuc", {"gain": {b: np.asarray(nz[f"gain/{b}"]) for b in bands},
                       "offset": {b: np.asarray(nz[f"offset/{b}"]) for b in bands}})
    dark = _adf("dark", {"dark_offset": {b: float(np.asarray(dz[f"dark_offset/{b}"])) for b in bands}})
    radiom = _adf("radiometric", {"gain": {b: float(np.asarray(rz[f"gain/{b}"])) for b in bands},
                                  "offset": {b: float(np.asarray(rz[f"offset/{b}"])) for b in bands}})
    spec = _adf("spectral", {"esun": {b: float(np.asarray(sz[f"esun/{b}"])) for b in bands}})
    psf = _adf("psf", {"kernel": {b: np.array([[1.0]], dtype=np.float32) for b in bands}})

    # l0_decode → radiometric → enhancement (identity MTFC, no denoise) → toa (emit_reflectance)
    l1a = L0DecodeUnit("l0").run({"l0c": prod})["l1a"]
    rad = RadiometricUnit("rad").run({"l1a": l1a}, adfs={"dark": dark, "nuc": nuc})["rad"]
    enh = EnhancementUnit("enh").run({"rad": rad}, adfs={"psf": psf}, denoise_method="none")["enh"]
    l1b = ToaUnit("toa").run(
        {"enh": enh},
        adfs={"radiometric": radiom, "spectral": spec},
        emit_reflectance=True, sun_zenith_deg=sun_zenith_deg, earth_sun_distance_au=earth_sun_distance_au,
    )["l1b"]
    return l1b


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    work = args[0] if args else None            # default → the repo's data/output/
    l0_path, caldb, band_frames = build_inputs(work)
    print(f"built open-container L0 → {l0_path}")
    print(f"      cal-DB (incl. spectral/ESUN) → {caldb}")
    print(f"bands={list(band_frames)}  n_det={N_DET}  n_lines={N_LINES}")
    l0_ql = quicklook.save_rgb(band_frames, Path(l0_path).resolve().parents[1] / "quicklook" / "l0_rgb.png",
                               upscale=4)
    print(f"      L0 quicklook (RGB=B04/B03/B02 DN) → {l0_ql}")
    try:
        l1b = run_processor(l0_path, caldb)
    except ImportError as e:
        print(f"\n[processor step skipped] eopf / msi_processor not available here: {e}")
        print("Install eopf==2.8.1 + msi_processor (the SDE) to produce the real L1B reflectance.")
        return 0
    print("\n=== L1B TOA reflectance ===")
    for b in sorted(band_frames):
        r = np.asarray(l1b[f"measurements/reflectance/{b}"].data)
        print(f"  {b}: shape={r.shape} min={float(np.nanmin(r)):.4f} "
              f"max={float(np.nanmax(r)):.4f} mean={float(np.nanmean(r)):.4f}")
    print("L1B reflectance product produced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

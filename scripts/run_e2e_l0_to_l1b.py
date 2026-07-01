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

Step (1) is pure ``numpy``/``zarr`` and is exercised in generator CI (``tests/test_e2e_l1b.py``). Step
(2) needs ``eopf==2.8.1`` + ``msi_processor`` on the path and therefore runs on the **SDE** runner, not
in generator CI.

    python scripts/run_e2e_l0_to_l1b.py [work_dir]     # requires eopf + msi_processor
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from s2_msi_raw_generator import datation, l0product, sensor
from s2_msi_raw_generator.adf_writer import BandCal, write_calibration_db

# One common detector width across all bands so nuc.gain[band] length == detector-axis width (the
# hard invariant of the open-container handoff). The first E2E deliberately uses a single n_det.
N_DET = 64
N_LINES = 48
BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]   # 10 m group + SWIR
DAY_OF_YEAR = 94                                     # 2024-04-03
SUN_ZENITH_DEG = 35.0


def build_inputs(work_dir, *, n_det: int = N_DET, n_lines: int = N_LINES, bands=BANDS, seed: int = 0):
    """Build the cal-DB (with ESUN) + an open-container L0 at a common ``n_det``. Pure numpy/zarr.

    Returns ``(l0_path, caldb_dir, band_frames)``. This is the CI-verified half of the E2E.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
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

    l0_path = str(work / "L0c_opencontainer.zarr")
    l0product.write_l0_opencontainer(l0_path, band_frames, datation=datation.Datation())
    return l0_path, str(caldb), band_frames


def run_processor(l0_path, caldb_dir, *, day_of_year: int = DAY_OF_YEAR, sun_zenith_deg: float = SUN_ZENITH_DEG):
    """Run msi-processor ``l0_decode → radiometric → toa`` (emit_reflectance) → L1B. **SDE-only.**

    Imports ``eopf`` + ``msi_processor`` lazily so this file stays importable in generator CI.
    """
    import zarr
    from eopf.product import EOProduct, EOVariable  # noqa: F401  (SDE)
    from eopf.product.conveyor.auxiliary_data_file import AuxiliaryDataFile  # noqa: F401  (SDE)
    from msi_processor.computing.l0_decode.unit import L0DecodeUnit
    from msi_processor.computing.radiometric.unit import RadiometricUnit
    from msi_processor.computing.toa.unit import ToaUnit

    def _adf(name):
        grp = zarr.open_group(f"{caldb_dir}/{name}.zarr", mode="r")

        def _flatten(g, prefix=""):
            out = {}
            for k in g.array_keys():
                out[f"{prefix}{k}"] = np.asarray(g[k])
            for k in g.group_keys():
                out.update(_flatten(g[k], f"{prefix}{k}/"))
            return out

        return AuxiliaryDataFile(data_ptr=_flatten(grp))

    l0c = EOProduct.open(l0_path)   # SDE eopf reads the open-container zarr
    l1a = L0DecodeUnit().run({"l0c": l0c})["l1a"]
    rad = RadiometricUnit().run({"l1a": l1a}, adfs={"dark": _adf("dark"), "nuc": _adf("nuc")})["rad"]
    l1b = ToaUnit().run({"enh": rad}, adfs={"radiometric": _adf("radiometric"), "spectral": _adf("spectral")},
                        emit_reflectance=True, sun_zenith_deg=sun_zenith_deg, day_of_year=day_of_year)["l1b"]
    return l1b


def main(argv=None) -> int:
    work = (argv or sys.argv[1:] or ["/tmp/claude-1000/s2_e2e_l1b"])[0]
    l0_path, caldb, band_frames = build_inputs(work)
    print(f"built open-container L0 → {l0_path}\n      cal-DB (incl. spectral/ESUN) → {caldb}")
    print(f"bands={list(band_frames)}  n_det={N_DET}  n_lines={N_LINES}")
    try:
        l1b = run_processor(l0_path, caldb)
    except ImportError as e:
        print(f"\n[SDE step skipped] msi-processor / eopf not available here: {e}")
        print("Run on the SDE (eopf==2.8.1 + msi_processor) to produce the real L1B reflectance.")
        return 0
    print(f"\nL1B reflectance product produced: {l1b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

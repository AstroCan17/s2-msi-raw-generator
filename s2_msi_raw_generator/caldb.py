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

"""Build the calibration database (EOPF ADF set) for the downstream L1PP processor.

Derives the radiometric calibration coefficients for all 13 bands via the two-reference
(CSM sun-diffuser + dark) inverse-crime cure — in the ``msi-processor`` NUC convention — and writes
them as EOPF zarr ADFs (``nuc`` / ``dark`` / ``radiometric`` [+ ``noise``]) with a ``PROVENANCE.md``.
This is Option Y of the generator ⇄ processor coupling: the generator *produces* the ADF; the
processor keeps calibration internal. See :mod:`s2_msi_raw_generator.adf_writer`.

Driven by the ``build-caldb`` phase of ``scripts/run_pipeline.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from s2_msi_raw_generator import adf as adfmod, adf_writer, calibration, sensor


def derive_band_cal(
    band_name: str,
    *,
    unit: str = sensor.DEFAULT_UNIT,
    n_det: int = 400,
    n_frames: int = 256,
    seed: int = 0,
) -> adf_writer.BandCal:
    """Derive one band's cal-DB coefficients from synthetic dark + diffuser acquisitions.

    Impresses the truth ADF to synthesise a dark and a sun-diffuser (flat) L0 acquisition, then
    derives the NUC ``(gain, offset)`` in the processor's two-point convention plus the per-band dark
    and the absolute ``radiometric.gain = 1/cal_gain``. Coefficients are *derived*, not the truth.
    """
    b = sensor.band(band_name, unit)
    truth = adfmod.synthesize(b, n_det=n_det, seed=seed)
    rng = np.random.default_rng(seed + sensor.BANDS.index(band_name))
    l_diff = 1.5 * b.lref
    dark = calibration.synth_dark_acquisition(truth, n_frames, rng)
    flat = calibration.synth_diffuser_acquisition(truth, l_diff, n_frames, rng)
    gain, offset, dark_offset = adf_writer.nuc_two_point(dark, flat)
    # Absolute DN->radiance gain, *derived from the diffuser*: the NUC maps the flat to the uniform
    # signal (muF - muD), which corresponds to the known diffuser radiance l_diff. This is
    # self-consistent with the NUC (unlike the truth 1/cal_gain) and stays ~1/cal_gain when <G>~1.
    signal = float(np.mean(flat) - np.mean(dark))
    radio_gain = float(l_diff / signal) if signal > 0 else float("nan")
    return adf_writer.BandCal(
        band=band_name,
        nuc_gain=gain,
        nuc_offset=offset,
        dark_offset=float(dark_offset),
        radio_gain=radio_gain,
        radio_offset=0.0,
        esun=float(sensor.esun(band_name, unit)),
        noise_alpha=float(b.noise_alpha),
        noise_beta=float(b.noise_beta),
    )


def build(
    out_dir,
    *,
    unit: str = sensor.DEFAULT_UNIT,
    n_det: int = 400,
    seed: int = 0,
    include_noise: bool = True,
) -> list[Path]:
    """Derive all 13 bands and write the cal-DB to ``out_dir``. Returns the written ADF paths."""
    cals = [derive_band_cal(bn, unit=unit, n_det=n_det, seed=seed) for bn in sensor.BANDS]
    return adf_writer.write_calibration_db(out_dir, cals, unit=unit, include_noise=include_noise)



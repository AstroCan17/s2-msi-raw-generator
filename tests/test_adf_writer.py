"""Tests for the cal-DB writer (EOPF ADF set consumed by msi-processor / L1PP).

Covers (1) the NUC two-point convention + diffuser-derived absolute gain recovering radiance
through the processor's own formulas (correctness + non-tautology), (2) the on-disk ADF schema,
and (3) the full 13-band build round-tripped back through the processor formulas.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import adf, adf_writer, reverse, sensor

from s2_msi_raw_generator import caldb as build_cal_db


# --- the processor's consuming formulas, replicated (no eopf dependency) -----------------------
def _apply_nuc(dn, gain, offset, dark_offset):
    """msi_processor.computing.radiometric.core.apply_nuc: DN*g + o - k."""
    return dn.astype(np.float32) * gain + offset - np.float32(dark_offset)


def _dn_to_radiance(dn, gain, offset):
    """msi_processor.computing.toa.core.dn_to_radiance: (DN - o) * g."""
    return (dn.astype(np.float32) - np.float32(offset)) * np.float32(gain)


def test_nuc_two_point_round_trip_recovers_radiance():
    """Noiseless: NUC + diffuser-derived gain recover the input radiance exactly."""
    rng = np.random.default_rng(0)
    n_det, n_lines = 64, 32
    A = 3.0
    G = 1.0 + rng.normal(0.0, 0.02, n_det)     # per-detector relative response ~1
    D = 480.0 + rng.normal(0.0, 0.5, n_det)    # per-detector dark
    l_diff = 150.0
    dark = np.tile(D, (n_lines, 1))                        # noiseless reference frames
    flat = np.tile(A * G * l_diff + D, (n_lines, 1))

    gain, offset, k = adf_writer.nuc_two_point(dark, flat)
    radio_gain = l_diff / float(flat.mean() - dark.mean())

    # a scene at a known radiance L, forward-modelled X = A*G*L + D
    L = 90.0
    X = (A * G * L + D).astype(np.float32)
    corrected = _apply_nuc(X, gain, offset, k)             # -> ~ A*L (dark removed, PRNU equalised)
    radiance = _dn_to_radiance(corrected, radio_gain, 0.0)  # -> ~ L
    assert np.allclose(radiance, L, rtol=1e-3)

    # the NUC gain is DERIVED from the frames, not the truth response G (non-tautology)
    assert not np.allclose(gain, G)


def test_write_calibration_db_schema(tmp_path):
    """The writer emits the exact EOPF ADF layout msi-processor expects (zarr v2)."""
    cals = [
        adf_writer.BandCal(
            "B03",
            nuc_gain=np.array([1.0, 0.99, 1.01], np.float32),
            nuc_offset=np.array([0.0, 0.1, -0.1], np.float32),
            dark_offset=480.0, radio_gain=0.25, radio_offset=0.0, esun=1823.24,
            noise_alpha=0.488, noise_beta=0.03482,
        ),
        adf_writer.BandCal(
            "B8A",
            nuc_gain=np.ones(4, np.float32), nuc_offset=np.zeros(4, np.float32),
            dark_offset=481.0, radio_gain=0.20, esun=955.32, noise_alpha=0.574, noise_beta=0.08714,
        ),
    ]
    paths = adf_writer.write_calibration_db(tmp_path, cals, unit="S2A")
    assert {p.name for p in paths} == {"nuc.zarr", "dark.zarr", "radiometric.zarr", "spectral.zarr", "noise.zarr"}
    assert (tmp_path / "PROVENANCE.md").exists()

    nuc = zarr.open_group(str(tmp_path / "nuc.zarr"), mode="r")
    # EOPF/msi-processor interop: v2 on disk — asserted from the .zgroup file itself so the test
    # passes under both zarr 3 (CI) and zarr 2.18 (the eopf env; Group.metadata does not exist there).
    assert json.loads((tmp_path / "nuc.zarr" / ".zgroup").read_text())["zarr_format"] == 2
    g = np.asarray(nuc["gain/B03"])
    assert g.dtype == np.float32 and g.shape == (3,)
    assert np.asarray(nuc["offset/B8A"]).shape == (4,)
    assert nuc.attrs["processor"] == "s2_msi_raw_generator"
    assert nuc.attrs["adf_type"] == "ADF_REQOG"

    # scalars are 0-d and float()-able (as the processor reads them)
    dark = zarr.open_group(str(tmp_path / "dark.zarr"), mode="r")
    assert float(np.asarray(dark["dark_offset/B03"])) == pytest.approx(480.0)
    rad = zarr.open_group(str(tmp_path / "radiometric.zarr"), mode="r")
    assert float(np.asarray(rad["gain/B03"])) == pytest.approx(0.25)
    assert float(np.asarray(rad["offset/B03"])) == pytest.approx(0.0)
    noise = zarr.open_group(str(tmp_path / "noise.zarr"), mode="r")
    assert float(np.asarray(noise["beta/B03"])) == pytest.approx(0.03482)

    # spectral.zarr — per-band ESUN 0-d float32 scalar, exactly what toa/_resolve_esun reads
    spec = zarr.open_group(str(tmp_path / "spectral.zarr"), mode="r")
    e = np.asarray(spec["esun/B03"])
    assert e.dtype == np.float32 and e.shape == ()
    assert float(e) == pytest.approx(1823.24)
    assert spec.attrs["adf_type"] == "ADF_SPECT"


def test_write_calibration_db_can_omit_spectral_and_noise(tmp_path):
    cals = [adf_writer.BandCal("B02", np.ones(3, np.float32), np.zeros(3, np.float32),
                               dark_offset=480.0, radio_gain=0.3)]
    paths = adf_writer.write_calibration_db(tmp_path, cals, include_spectral=False, include_noise=False)
    assert {p.name for p in paths} == {"nuc.zarr", "dark.zarr", "radiometric.zarr"}
    assert not (tmp_path / "noise.zarr").exists()
    assert not (tmp_path / "spectral.zarr").exists()


def test_spectral_esun_matches_thuillier_all_bands(tmp_path):
    """The 13-band build writes ESUN /esun/<band> scalars equal to the S2A Thuillier set (ATBD §A.3)."""
    out = tmp_path / "caldb"
    build_cal_db.build(out, n_det=32, seed=1)
    spec = zarr.open_group(str(out / "spectral.zarr"), mode="r")
    assert set(spec["esun"].array_keys()) == set(sensor.BANDS)          # 13 bands
    for bn in sensor.BANDS:
        v = np.asarray(spec[f"esun/{bn}"])
        assert v.dtype == np.float32 and v.shape == ()
        assert float(v) == pytest.approx(sensor.ESUN["S2A"][bn], rel=1e-6)


def test_build_all_bands_and_consume(tmp_path):
    """Full 13-band build; feed the ADFs back through the processor formulas -> recover radiance."""
    out = tmp_path / "caldb"
    paths = build_cal_db.build(out, n_det=64, seed=3)
    assert len(paths) == 5

    nuc = zarr.open_group(str(out / "nuc.zarr"), mode="r")
    assert set(nuc["gain"].array_keys()) == set(sensor.BANDS)   # 13 bands
    dark = zarr.open_group(str(out / "dark.zarr"), mode="r")
    rad = zarr.open_group(str(out / "radiometric.zarr"), mode="r")

    # consume one band exactly as the processor would (nuc + dark -> radiometric)
    bn = "B04"
    b = sensor.band(bn)
    g = np.asarray(nuc[f"gain/{bn}"])
    o = np.asarray(nuc[f"offset/{bn}"])
    k = float(np.asarray(dark[f"dark_offset/{bn}"]))
    rg = float(np.asarray(rad[f"gain/{bn}"]))
    n_det = g.shape[0]

    # synthetic L0 DN for a uniform scene through the *same* truth basis (seed 3, n_det 64)
    truth = adf.synthesize(b, n_det=n_det, seed=3)
    scene = np.full((8, n_det), b.lref * 0.7)
    dn = reverse.reverse_mvp(scene, truth, np.random.default_rng(0)).astype(np.float32)

    corrected = _apply_nuc(dn, g, o, k)
    radiance = _dn_to_radiance(corrected, rg, 0.0)
    # derived coefficients + sensor noise -> realistic (non-zero) residual, mean recovers the input
    assert float(np.nanmean(radiance)) == pytest.approx(float(scene.mean()), rel=0.1)


"""Tests for the S2 calibration sub-set (synthetic CSM diffuser + dark → derived coefficients).

The loop impresses the true ADF, then derives the dark + relative response back. The estimates must
recover the truth (the inverse-crime cure: residuals are small calibration uncertainty, not 0).
"""

from __future__ import annotations

import numpy as np
import pytest

from s2_e2es import adf, calibration as cal, sensor


@pytest.mark.parametrize("bn", ["B03", "B08", "B11"])
def test_calibration_recovers_dark_and_relative_response(bn):
    a = adf.synthesize(sensor.band(bn), n_det=256, seed=7)
    c = cal.calibrate(a, n_dark=256, n_diffuser=256, seed=1)

    # dark recovered to sub-DN accuracy (averaging over lines beats the read noise)
    assert np.abs(c.dark.mean() - a.dark_dn.mean()) < 0.5
    assert (c.dark - a.dark_dn).std() < 0.5

    # relative response recovers the impressed PRNU pattern (normalised), high correlation
    truth_g = a.prnu_gain / a.prnu_gain.mean()
    assert np.corrcoef(c.relative_response, truth_g)[0, 1] > 0.9
    assert c.relative_response.mean() == pytest.approx(1.0, abs=1e-6)   # ⟨g⟩ = 1


def test_absolute_coefficient_matches_cal_gain():
    b = sensor.band("B04")
    a = adf.synthesize(b, n_det=128, seed=3)
    c = cal.calibrate(a, l_diff=1.4 * b.lref, n_dark=200, n_diffuser=200, seed=2)
    # A·L_diff = ⟨X_diff − D⟩ and X_diff ≈ cal_gain·L_diff ⇒ A ≈ cal_gain
    assert c.abs_coeff == pytest.approx(b.cal_gain, rel=0.05)


def test_estimated_adf_uses_derived_not_truth():
    a = adf.synthesize(sensor.band("B05"), n_det=64, seed=4)
    c = cal.calibrate(a, n_dark=128, n_diffuser=128, seed=5)
    est = cal.estimated_adf(a, c)
    assert est.source.startswith("derived")
    assert np.array_equal(est.dark_dn, c.dark)
    assert np.array_equal(est.prnu_gain, c.relative_response)
    # estimate differs from the truth ADF (calibration residual, not a tautology)
    assert not np.array_equal(est.dark_dn, a.dark_dn)
    assert est.psf is a.psf and est.noise_a == a.noise_a   # PSF + noise unchanged


def test_dark_acquisition_has_no_scene_signal():
    a = adf.synthesize(sensor.band("B02"), n_det=64, seed=6)
    rng = np.random.default_rng(0)
    dark = cal.synth_dark_acquisition(a, 128, rng)
    # a dark frame sits at the dark pedestal (± noise), well below a diffuser frame
    diff = cal.synth_diffuser_acquisition(a, 1.5 * a.band.lref, 128, rng)
    assert dark.mean() < diff.mean()
    assert abs(dark.mean() - a.dark_dn.mean()) < 2.0

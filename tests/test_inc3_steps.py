"""Increment-3 tests: remaining reverse steps S3, S4, S5, S8, S9, S10 + extended chain."""

from __future__ import annotations

import numpy as np
import pytest

from s2_msi_raw_generator import adf, reverse, sensor


def test_s4_undo_offset_exact():
    dn = np.arange(20, dtype=float).reshape(4, 5)
    np.testing.assert_array_equal(reverse.s4_undo_radiometric_offset(dn, -100.0), dn + 100.0)
    np.testing.assert_array_equal(reverse.s4_undo_radiometric_offset(dn), dn)  # default no-op


def test_s5_unbin_shape_and_mean_preserved():
    img = np.array([[1.0, 2.0], [3.0, 4.0]])
    un = reverse.s5_unbin(img, factor=3, axis=1)
    assert un.shape == (2, 6)
    # binning back (mean over each group of 3) recovers the original
    back = un.reshape(2, 2, 3).mean(axis=2)
    np.testing.assert_allclose(back, img)


def test_s8_restage_swir_is_invertible():
    rng = np.random.default_rng(0)
    img = rng.uniform(0, 100, size=(64, 8))
    shifts = np.array([0, 1, -1, 2, -2, 1, 0, -1])
    staged = reverse.s8_restage_swir(img, shifts)
    unstaged = reverse.s8_restage_swir(staged, -shifts)
    np.testing.assert_allclose(unstaged, img)
    assert not np.allclose(staged, img)  # actually shifts columns


def test_s9_crosstalk_adds_neighbours_and_is_small():
    rng = np.random.default_rng(1)
    bands = {b: rng.uniform(10, 100, size=(20, 20)) for b in ("B02", "B03", "B04")}
    # zero coeff = identity
    out0 = reverse.s9_apply_crosstalk(bands, coeff=0.0)
    for b in bands:
        np.testing.assert_allclose(out0[b], bands[b])
    # small coeff: each band += coeff*(sum of others), bounded by <0.5 %-ish at these levels
    c = 0.002
    out = reverse.s9_apply_crosstalk(bands, coeff=c)
    expect_b02 = bands["B02"] + c * (bands["B03"] + bands["B04"])
    np.testing.assert_allclose(out["B02"], expect_b02)
    # mismatched shapes rejected
    with pytest.raises(ValueError):
        reverse.s9_apply_crosstalk({"B02": np.zeros((4, 4)), "B11": np.zeros((4, 2))})


def test_s10_inject_defects_dead_and_hot():
    img = np.full((10, 6), 50.0)
    out, qa = reverse.s10_inject_defects(img, dead_cols=(2,), hot_pixels=((3, 4),), dn_max=4095)
    assert np.all(out[:, 2] == 0.0) and np.all(qa[:, 2] & 1)
    assert out[3, 4] == 4095.0 and (qa[3, 4] & 2)
    # untouched pixel unchanged, no flag
    assert out[0, 0] == 50.0 and qa[0, 0] == 0


def test_reverse_full_contract_with_swir_and_defects():
    b = sensor.band("B11")  # SWIR
    a = adf.synthesize(b, n_det=32, seed=9)
    rng = np.random.default_rng(7)
    L = np.clip(rng.normal(b.lref, b.lref * 0.3, size=(48, 32)), 0, None)
    shifts = np.zeros(32, dtype=int)
    shifts[::2] = 1  # odd/even stagger
    l0, qa = reverse.reverse_full(L, a, rng, swir_shifts=shifts,
                                  dead_cols=(5,), hot_pixels=((10, 7),))
    assert l0.shape == L.shape and l0.dtype == np.uint16
    assert l0.min() >= 0 and l0.max() <= sensor.DN_MAX
    assert np.all(qa[:, 5] & 1)          # dead column flagged
    assert qa[10, 7] & 2                  # hot pixel flagged

"""Tests for the real line-datation model (REQ-FUNC-035)."""

from __future__ import annotations

import pytest

from s2_msi_raw_generator import datation, sensor


def test_line_time_is_monotone_by_line_period():
    d = datation.Datation(epoch_utc="2024-04-03T10:24:15Z")
    assert d.line_period_s == sensor.LINE_PERIOD_MS / 1000.0
    # absolute GPS seconds (~1.39e9) so a line-to-line difference is only float64-accurate to the ULP
    # (~2.4e-7 s) — finer than the CUC fine field (1/65536 s), so the encoded timestamp stays exact.
    step = d.line_time_gps(1) - d.line_time_gps(0)
    assert step == pytest.approx(d.line_period_s, abs=1e-6)
    assert d.line_time_gps(100) > d.line_time_gps(0)


def test_gps_epoch_is_a_real_positive_second_of_epoch():
    # 2024-04-03 is ~44 y after the GPS epoch (1980-01-06): ~1.39e9 s, well within the 32-bit CUC coarse.
    g = datation.Datation(epoch_utc="2024-04-03T10:24:15Z").gps_epoch_s
    assert 1.30e9 < g < 1.50e9
    assert g < (1 << 32)  # fits the CUC coarse field


def test_per_band_time_shift_applied():
    d = datation.Datation(time_shift_s={"B05": 0.5})
    assert d.line_time_gps(0, "B05") - d.line_time_gps(0, "B02") == 0.5


def test_span_utc_is_ordered_and_zulu():
    d = datation.Datation(epoch_utc="2024-04-03T10:24:15Z")
    start, end = d.span_utc(n_lines=1000)
    assert start.endswith("Z") and end.endswith("Z")
    assert start <= end and start.startswith("2024-04-03T10:24:15")


def test_band_time_stamp_covers_13_bands():
    bts = datation.Datation().band_time_stamp()
    assert set(bts) == {sensor.band_number(b) for b in sensor.BANDS}
    assert all(v["unit"] == "s (GPS)" and v["value"] > 1.30e9 for v in bts.values())

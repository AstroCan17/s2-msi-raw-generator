"""Tests for the PSFD §3 product file naming (naming.py)."""

from __future__ import annotations

from datetime import datetime

import pytest

from s2_msi_raw_generator import naming


def test_l0_name_has_double_underscore_and_expected_layout():
    # The L0 type code ends in the pad '_', so the field separator produces the doubled underscore.
    name = naming.psfd_name(
        "S02MSIL0_", datetime(2024, 4, 3, 10, 24, 15), 33.0,
        relative_orbit=45, discriminator="1A2")
    assert name == "S02MSIL0__20240403T102415_0033_A045_T1A2.zarr"


@pytest.mark.parametrize(
    "product_type, unit, orbit, consolidation, z_suffix, ext",
    [
        ("S02MSIL0_", "A", 45, "T", None, ".zarr"),
        ("S02MSIL1A", "B", 143, "_", None, ".zarr.zip"),
        ("S02MSIL1B", "A", 1, "S", "DS_00", ".zarr"),
        ("S02MSIISP", "C", 64, "T", "T3A5_r2", ""),
        ("S02SADISP", "A", 122, "T", None, ".zarr.zip"),
    ],
)
def test_round_trip(product_type, unit, orbit, consolidation, z_suffix, ext):
    start = datetime(2023, 6, 29, 6, 35, 59)
    name = naming.psfd_name(
        product_type, start, 120.0, unit=unit, relative_orbit=orbit,
        consolidation=consolidation, z_suffix=z_suffix, ext=ext)
    parsed = naming.parse_psfd_name(name)
    assert parsed["product_type"] == product_type
    assert parsed["start_utc"] == start
    assert parsed["duration_s"] == 120
    assert parsed["unit"] == unit
    assert parsed["relative_orbit"] == orbit
    assert parsed["consolidation"] == consolidation
    assert parsed["z_suffix"] == z_suffix
    assert parsed["ext"] == ext
    # Re-emitting the parsed fields (with the recovered discriminator) reproduces the name exactly.
    assert naming.psfd_name(
        parsed["product_type"], parsed["start_utc"], parsed["duration_s"],
        unit=parsed["unit"], relative_orbit=parsed["relative_orbit"],
        consolidation=parsed["consolidation"], discriminator=parsed["discriminator"],
        z_suffix=parsed["z_suffix"], ext=parsed["ext"]) == name


def test_parse_accepts_name_without_ext():
    parsed = naming.parse_psfd_name("S02MSIL0__20240403T102415_0033_A045_T1A2")
    assert parsed["ext"] == ""
    assert parsed["z_suffix"] is None
    assert parsed["discriminator"] == "1A2"


@pytest.mark.parametrize("bad_name", [
    "not-a-product",
    "S02MSIL0__20240403T102415_0033_A045",        # missing XVVV
    "S02MSIL0__20240403T102415_33_A045_T1A2",     # duration not 4 digits
    "S02MSIL0__20240403T102415_0033_A045_TXYZ.zarr",  # non-hex discriminator
    "S02XXXXXX_20240403T102415_0033_A045_T1A2",   # 9 chars but unknown type code
])
def test_parse_rejects_bad_names(bad_name):
    with pytest.raises(ValueError):
        naming.parse_psfd_name(bad_name)


@pytest.mark.parametrize("kwargs", [
    {"product_type": "FOO", "relative_orbit": 45},                                   # wrong length
    {"product_type": "S02MSIL9_", "relative_orbit": 45},                             # unknown code
    {"product_type": "S02MSIL0_", "relative_orbit": 0},                              # orbit too low
    {"product_type": "S02MSIL0_", "relative_orbit": 144},                            # orbit too high
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "consolidation": "X"},       # bad flag
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "unit": "1"},                # unit not letter
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "unit": "AA"},               # unit not 1 char
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "discriminator": "xyz"},     # not upper hex
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "ext": ".tif"},              # bad extension
    {"product_type": "S02MSIL0_", "relative_orbit": 45, "z_suffix": "bad token"},    # space in token
])
def test_validation_errors(kwargs):
    with pytest.raises(ValueError):
        naming.psfd_name(start_utc=datetime(2024, 4, 3, 10, 24, 15), duration_s=10.0, **kwargs)


def test_duration_min_clamps_to_one():
    name = naming.psfd_name("S02MSIL0_", datetime(2024, 1, 1), 0.4, relative_orbit=45)
    assert naming.parse_psfd_name(name)["duration_s"] == 1  # 0.4 rounds to 0, clamped up to 1


def test_duration_rounds_half_up_to_four_digits():
    name = naming.psfd_name("S02MSIL0_", datetime(2024, 1, 1), 33.48, relative_orbit=45)
    assert "_0033_" in name
    assert naming.parse_psfd_name(name)["duration_s"] == 33
    # An exact half rounds up (distinguishes half-up from banker's rounding).
    assert naming.parse_psfd_name(
        naming.psfd_name("S02MSIL0_", datetime(2024, 1, 1), 2.5, relative_orbit=45))["duration_s"] == 3


def test_duration_above_field_maximum_raises():
    with pytest.raises(ValueError):
        naming.psfd_name("S02MSIL0_", datetime(2024, 1, 1), 12000.0, relative_orbit=45)


def test_discriminator_is_deterministic_and_overridable():
    args = ("S02MSIL0_", datetime(2024, 4, 3, 10, 24, 15), 33.0)
    a = naming.psfd_name(*args, relative_orbit=45)
    b = naming.psfd_name(*args, relative_orbit=45)
    assert a == b  # same inputs derive the same VVV
    disc = naming.parse_psfd_name(a)["discriminator"]
    assert len(disc) == 3 and set(disc) <= set("0123456789ABCDEF")
    explicit = naming.psfd_name(*args, relative_orbit=45, discriminator="ABC")
    assert naming.parse_psfd_name(explicit)["discriminator"] == "ABC"


def test_from_l1a_context_full_attrs_no_fallbacks():
    attrs = {
        "stac_discovery": {
            "properties": {
                "datetime": "2023-06-29T06:35:59Z",
                "sat:relative_orbit": 64,
                "platform": "sentinel-2b",
            }
        }
    }
    name, info = naming.from_l1a_context(
        attrs, n_lines=1000, line_period_s=0.12, product_type="S02MSIL0_")
    assert info["derived_from_defaults"] == []
    parsed = naming.parse_psfd_name(name)
    assert parsed["product_type"] == "S02MSIL0_"
    assert parsed["unit"] == "B"
    assert parsed["relative_orbit"] == 64
    assert parsed["start_utc"] == datetime(2023, 6, 29, 6, 35, 59)
    assert parsed["duration_s"] == 120  # 1000 * 0.12 s


def test_from_l1a_context_uses_start_datetime_when_datetime_absent():
    attrs = {"stac_discovery": {"properties": {
        "start_datetime": "2024-04-03T10:24:15Z",
        "sat:relative_orbit": 45,
        "platform": "sentinel-2a",
    }}}
    name, info = naming.from_l1a_context(
        attrs, n_lines=10, line_period_s=1.0, product_type="S02MSIL1B")
    assert "datetime" not in info["derived_from_defaults"]
    assert naming.parse_psfd_name(name)["start_utc"] == datetime(2024, 4, 3, 10, 24, 15)


def test_from_l1a_context_empty_attrs_flags_all_defaults():
    name, info = naming.from_l1a_context(
        {}, n_lines=500, line_period_s=0.1, product_type="S02MSIL0_")
    assert set(info["derived_from_defaults"]) == {"datetime", "sat:relative_orbit", "platform"}
    parsed = naming.parse_psfd_name(name)
    assert parsed["unit"] == naming.DEFAULT_UNIT
    assert parsed["relative_orbit"] == naming.DEFAULT_RELATIVE_ORBIT
    assert parsed["start_utc"] == naming.DEFAULT_START.replace(tzinfo=None)

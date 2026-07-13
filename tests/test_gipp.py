"""Tests for the GIPP parser (``s2_msi_raw_generator.gipp``) and ``BandADF.from_gipp``.

Structurally-faithful but tiny GIPP XML/JSON fixtures are generated inline (no large vendored files). An
optional test runs against the operational GIPP when ``S2_GIPP_DIR`` points at it.
"""

from __future__ import annotations

import json
import os

import numpy as np
import pytest

from s2_msi_raw_generator import adf, gipp, sensor


# --- tiny inline GIPP fixtures -----------------------------------------------

def _vals(v, n):
    return " ".join(f"{v:.5f}" for _ in range(n))


def _r2eqog_cubic(band="B03", npix=8, ndet=2, tdi="APPLIED", dark=440.0, c=0.99):
    dets = ""
    for d in range(1, ndet + 1):
        lines = "".join(f"<LINE{k}>{_vals(dark + d + 0.1 * k, npix)}</LINE{k}>" for k in range(1, 7))
        dets += f"""<COEFFICIENTS detector_id="{d:02d}"><NB_OF_PIXELS>{npix}</NB_OF_PIXELS>
          <GROUND_EQUALIZATION><CUBIC>
            <COEFF_A>{_vals(0.0, npix)}</COEFF_A><COEFF_B>{_vals(0.0, npix)}</COEFF_B>
            <COEFF_C>{_vals(c, npix)}</COEFF_C>
            <COEFF_D><A_10M_BAND>{lines}</A_10M_BAND></COEFF_D>
          </CUBIC></GROUND_EQUALIZATION></COEFFICIENTS>"""
    return (f'<?xml version="1.0"?><GS2_RADIOS2_EQUALIZATION_ONGROUND><DATA><BAND_ID>2</BAND_ID>'
            f'<COEFFICIENTS_LIST tdi_config="{tdi}">{dets}</COEFFICIENTS_LIST></DATA>'
            f'</GS2_RADIOS2_EQUALIZATION_ONGROUND>')


def _r2eqog_bilinear(band="B11", npix=4, ndet=2, dark=495.0, a1=0.95, a2=0.96, zs=600.0):
    dets = ""
    for d in range(1, ndet + 1):
        lines = "".join(f"<LINE{k}>{_vals(dark + d, npix)}</LINE{k}>" for k in range(1, 4))
        dets += f"""<COEFFICIENTS detector_id="{d:02d}"><NB_OF_PIXELS>{npix}</NB_OF_PIXELS>
          <GROUND_EQUALIZATION><BI-LINEAR>
            <COEFF_A1>{_vals(a1, npix)}</COEFF_A1><COEFF_A2>{_vals(a2, npix)}</COEFF_A2>
            <COEFF_Zs>{_vals(zs, npix)}</COEFF_Zs>
            <COEFF_D><A_20M_BAND>{lines}</A_20M_BAND></COEFF_D>
          </BI-LINEAR></GROUND_EQUALIZATION></COEFFICIENTS>"""
    return (f'<?xml version="1.0"?><GS2_RADIOS2_EQUALIZATION_ONGROUND><DATA><BAND_ID>11</BAND_ID>'
            f'<COEFFICIENTS_LIST tdi_config="APPLIED">{dets}</COEFFICIENTS_LIST></DATA>'
            f'</GS2_RADIOS2_EQUALIZATION_ONGROUND>')


def _r2depi():
    bands = ""
    for bid in range(13):
        cols = "<COLUMNS>2 5</COLUMNS>" if bid == 11 else "<COLUMNS/>"
        bands += (f'<BAND band_id="{bid}"><SINGULARITY_LIST>'
                  f'<SINGULARITY type="SATURATED_RESPONSE"><POSITION detector_id="01">{cols}'
                  f'</POSITION></SINGULARITY></SINGULARITY_LIST></BAND>')
    return f'<?xml version="1.0"?><GS2_DEFECTIVE_PIXELS><DATA>{bands}</DATA></GS2_DEFECTIVE_PIXELS>'


def _blindp():
    bands = ""
    for bid in range(13):
        bands += (f'<BAND band_id="{bid}"><DETECTOR detector_id="01">'
                  f'<SIDE side_id="LEFT"><VALID_BLIND_PIXELS>0 1</VALID_BLIND_PIXELS>'
                  f'<NON_VALID_BLIND_PIXELS>2 3</NON_VALID_BLIND_PIXELS></SIDE></DETECTOR></BAND>')
    return f'<?xml version="1.0"?><GS2_BLIND_PIXELS><DATA>{bands}</DATA></GS2_BLIND_PIXELS>'


def _r2para():
    l1b = "".join(f'<RADIO_ADD_OFFSET band_id="{i}">-100</RADIO_ADD_OFFSET>' for i in range(13))
    l1c = "".join(f'<RADIO_ADD_OFFSET band_id="{i}">-1000</RADIO_ADD_OFFSET>' for i in range(13))
    eqs = "".join(f'<BAND_EQUALIZATION band_id="{i}"><EQUALIZATION_FLAG>true</EQUALIZATION_FLAG>'
                  f'<OFFSET>true</OFFSET><DARK_SIGNAL_NON_UNIFORMITY>true</DARK_SIGNAL_NON_UNIFORMITY>'
                  f'</BAND_EQUALIZATION>' for i in range(13))
    return (f'<?xml version="1.0"?><GS2_RADIOS2_PARAMETERS><DATA>'
            f'<NOMINAL_SCENARIO><EQUALIZATION>{eqs}</EQUALIZATION></NOMINAL_SCENARIO>'
            f'<RADIOMETRIC_SHIFT><RADIANCE_OFFSET_L1B>{l1b}</RADIANCE_OFFSET_L1B>'
            f'<REFLECTANCE_OFFSET_L1C>{l1c}</REFLECTANCE_OFFSET_L1C></RADIOMETRIC_SHIFT>'
            f'</DATA></GS2_RADIOS2_PARAMETERS>')


def _r2crco():
    rows = "".join(f'<CROSSTALK_COEFF band_id_k="{i}"><OPTICAL>{_vals(0.0, 13)}</OPTICAL>'
                   f'<ELECTRICAL>{_vals(0.0, 13)}</ELECTRICAL></CROSSTALK_COEFF>' for i in range(13))
    return (f'<?xml version="1.0"?><GS2_RADIOS2_CROSSTALK_CORRECTION><DATA>'
            f'<CROSSTALK_COEFF_LIST>{rows}</CROSSTALK_COEFF_LIST></DATA>'
            f'</GS2_RADIOS2_CROSSTALK_CORRECTION>')


@pytest.fixture
def tiny_gipp(tmp_path):
    d = tmp_path / "gipp"
    d.mkdir()
    pref = "S2A_OPER_GIP"
    (d / f"{pref}_R2EQOG_MPC__x_V_x_B03.xml").write_text(_r2eqog_cubic("B03"))
    (d / f"{pref}_R2EQOG_MPC__x_V_x_B11.xml").write_text(_r2eqog_bilinear("B11"))
    (d / f"{pref}_R2DEPI_MPC__x_V_x_B00.xml").write_text(_r2depi())
    (d / f"{pref}_BLINDP_MPC__x_V_x_B00.xml").write_text(_blindp())
    (d / f"{pref}_R2PARA_MPC__x_V_x_B00.xml").write_text(_r2para())
    (d / f"{pref}_R2CRCO_MPC__x_V_x_B00.xml").write_text(_r2crco())
    return str(d)


def _json_eqog_cubic(npix=8, ndet=2, dark=440.0, c=0.99):
    coeffs = []
    for d in range(1, ndet + 1):
        lines = {f"LINE{k}": _vals(dark + d + 0.1 * k, npix) for k in range(1, 7)}
        coeffs.append({
            "@detector_id": f"{d:02d}",
            "NB_OF_PIXELS": str(npix),
            "GROUND_EQUALIZATION": {
                "CUBIC": {
                    "COEFF_A": _vals(0.0, npix),
                    "COEFF_B": _vals(0.0, npix),
                    "COEFF_C": _vals(c, npix),
                    "COEFF_D": {"A_10M_BAND": lines},
                }
            },
        })
    return {
        "GS2_RADIOS2_EQUALIZATION_ONGROUND": {
            "DATA": {
                "BAND_ID": "2",
                "COEFFICIENTS_LIST": {"@tdi_config": "APPLIED", "COEFFICIENTS": coeffs},
            }
        }
    }


def _json_eqog_bilinear(npix=4, ndet=2, dark=495.0, a1=0.95, a2=0.96, zs=600.0):
    coeffs = []
    for d in range(1, ndet + 1):
        lines = {f"LINE{k}": _vals(dark + d, npix) for k in range(1, 4)}
        coeffs.append({
            "@detector_id": f"{d:02d}",
            "NB_OF_PIXELS": str(npix),
            "GROUND_EQUALIZATION": {
                "BI-LINEAR": {
                    "COEFF_A1": _vals(a1, npix),
                    "COEFF_A2": _vals(a2, npix),
                    "COEFF_Zs": _vals(zs, npix),
                    "COEFF_D": {"A_20M_BAND": lines},
                }
            },
        })
    return {
        "GS2_RADIOS2_EQUALIZATION_ONGROUND": {
            "DATA": {
                "BAND_ID": "11",
                "COEFFICIENTS_LIST": {"@tdi_config": "APPLIED", "COEFFICIENTS": coeffs},
            }
        }
    }


def _json_rdepi():
    bands = []
    for bid in range(13):
        cols = "2 5" if bid == 11 else ""
        bands.append({
            "@band_id": str(bid),
            "SINGULARITY_LIST": {
                "SINGULARITY": {
                    "@type": "SATURATED_RESPONSE",
                    "POSITION": {"@detector_id": "01", "COLUMNS": cols},
                }
            },
        })
    return {"GS2_RADIOS2_DEFECTIVE_PIXELS": {"DATA": {"BAND": bands}}}


def _json_blindp():
    bands = []
    for bid in range(13):
        bands.append({
            "@band_id": str(bid),
            "DETECTOR": {
                "@detector_id": "01",
                "SIDE": {
                    "@side_id": "LEFT",
                    "VALID_BLIND_PIXELS": "0 1",
                    "NON_VALID_BLIND_PIXELS": "2 3",
                },
            },
        })
    return {"GS2_BLIND_PIXELS": {"DATA": {"BAND": bands}}}


def _json_r2para():
    l1b = [{"@band_id": str(i), "#text": "-100"} for i in range(13)]
    l1c = [{"@band_id": str(i), "#text": "-1000"} for i in range(13)]
    eqs = [{
        "@band_id": str(i),
        "EQUALIZATION_FLAG": "true",
        "OFFSET": "true",
        "DARK_SIGNAL_NON_UNIFORMITY": "true",
    } for i in range(13)]
    return {
        "GS2_RADIOS2_PARAMETERS": {
            "DATA": {
                "NOMINAL_SCENARIO": {"EQUALIZATION": {"BAND_EQUALIZATION": eqs}},
                "RADIOMETRIC_SHIFT": {
                    "RADIANCE_OFFSET_L1B": {"RADIO_ADD_OFFSET": l1b},
                    "REFLECTANCE_OFFSET_L1C": {"RADIO_ADD_OFFSET": l1c},
                },
            }
        }
    }


def _json_r2crco():
    rows = [{
        "@band_id_k": str(i),
        "OPTICAL": _vals(0.0, 13),
        "ELECTRICAL": _vals(0.0, 13),
    } for i in range(13)]
    return {"GS2_RADIOS2_CROSSTALK_CORRECTION": {"DATA": {"CROSSTALK_COEFF_LIST": {"CROSSTALK_COEFF": rows}}}}


@pytest.fixture
def tiny_gipp_json(tmp_path):
    root = tmp_path / "gipp-json"
    (root / "B03").mkdir(parents=True)
    (root / "B11").mkdir(parents=True)
    (root / "B00").mkdir(parents=True)
    (root / "B03" / "S2B_ADF_REQOG_test.json").write_text(json.dumps(_json_eqog_cubic()))
    (root / "B11" / "S2B_ADF_REQOG_test.json").write_text(json.dumps(_json_eqog_bilinear()))
    (root / "B00" / "S2B_ADF_RDEPI_test.json").write_text(json.dumps(_json_rdepi()))
    (root / "B00" / "S2B_ADF_BLIND_test.json").write_text(json.dumps(_json_blindp()))
    (root / "B00" / "S2B_ADF_RPARA_test.json").write_text(json.dumps(_json_r2para()))
    (root / "B00" / "S2B_ADF_RCRCO_test.json").write_text(json.dumps(_json_r2crco()))
    return str(root)


# --- parser tests ------------------------------------------------------------

def test_r2eqog_cubic_band(tiny_gipp):
    be = gipp.read_r2eqog_band(tiny_gipp, "B03")
    assert be.tdi is True and be.npix == 8
    d1 = be.detectors[1]
    assert d1.model == "CUBIC"
    assert set(d1.coeffs) == {"A", "B", "C"}
    assert np.allclose(d1.rel_gain, 0.99)              # COEFF_C
    assert d1.dark.shape == (8,)
    assert d1.dark.mean() == pytest.approx(441.35, abs=0.5)  # 440+det1 + mean(0.1*k)


def test_r2eqog_bilinear_band(tiny_gipp):
    be = gipp.read_r2eqog_band(tiny_gipp, "B11")
    d1 = be.detectors[1]
    assert d1.model == "BILINEAR"
    assert set(d1.coeffs) == {"A1", "A2", "Zs"}
    assert np.allclose(d1.rel_gain, 0.95)              # COEFF_A1
    assert d1.dark.mean() == pytest.approx(496.0)


def test_r2depi_blindp_para_crco(tiny_gipp):
    gs = gipp.load_gipp_set(tiny_gipp, bands=("B03", "B11"))
    assert list(gs.defective["B11"][1]) == [2, 5]      # band_id 11 saturated cols
    assert list(gs.defective["B03"][1]) == []
    assert list(gs.blind["B03"][1]) == [0, 1, 2, 3]
    assert gs.params.radiance_offset_l1b["B12"] == -100
    assert gs.params.reflectance_offset_l1c["B12"] == -1000
    assert np.abs(gs.crosstalk["B12"]).max() == 0.0


def test_from_gipp_builds_real_adf(tiny_gipp):
    gs = gipp.load_gipp_set(tiny_gipp, bands=("B03", "B11"))
    a = adf.BandADF.from_gipp(sensor.band("B03"), 2, gs)
    assert a.prnu_is_real and a.source in ("GIPP R2EQOG", "GIPP JSON REQOG")
    assert a.dark_dn.shape == (8,) and a.prnu_gain.shape == (8,)
    assert np.allclose(a.prnu_gain, 0.99)


def test_r2eqog_json_band(tiny_gipp_json):
    be = gipp.read_r2eqog_band(tiny_gipp_json, "B03")
    assert be.tdi is True and be.npix == 8
    assert be.source == "GIPP JSON REQOG"
    d1 = be.detectors[1]
    assert d1.model == "CUBIC"
    assert np.allclose(d1.rel_gain, 0.99)
    assert d1.dark.mean() == pytest.approx(441.35, abs=0.5)


def test_r2depi_blindp_json(tiny_gipp_json):
    gs = gipp.load_gipp_set(tiny_gipp_json, bands=("B03", "B11"))
    assert list(gs.defective["B11"][1]) == [2, 5]
    assert list(gs.blind["B03"][1]) == [0, 1, 2, 3]
    assert gs.params.radiance_offset_l1b["B12"] == -100


def test_load_gipp_set_json_layout(tiny_gipp_json):
    gs = gipp.load_gipp_set(tiny_gipp_json, bands=("B03", "B11"))
    a = adf.BandADF.from_gipp(sensor.band("B03"), 2, gs)
    assert a.source == "GIPP JSON REQOG"
    assert np.allclose(a.prnu_gain, 0.99)


# --- EOPF ADF (.json) R2EQOG reader ------------------------------------------

def _col(v, n):
    return [round(float(v), 5)] * n


@pytest.fixture
def tiny_eqog_adf(tmp_path):
    """Minimal EOPF ``ADF_REQOG`` json: VNIR cubic B03 (coeff_d w/ 3 sub-lines) + SWIR bilinear B11."""
    nv, ns = 8, 4
    dv = {
        "b03/coeff_a": {"dims": ["detector", "px"], "data": [_col(0.0, nv)] * 2},
        "b03/coeff_b": {"dims": ["detector", "px"], "data": [_col(0.0, nv)] * 2},
        "b03/coeff_c": {"dims": ["detector", "px"], "data": [_col(0.99, nv)] * 2},
        "b03/coeff_d": {"dims": ["detector", "line_3", "px"],
                        "data": [[_col(440.0 + d, nv), _col(441.0 + d, nv), _col(442.0 + d, nv)]
                                 for d in range(2)]},   # per-det mean -> 441+d
        "b11/coeff_a1": {"dims": ["detector", "px"], "data": [_col(0.95, ns)] * 2},
        "b11/coeff_a2": {"dims": ["detector", "px"], "data": [_col(0.96, ns)] * 2},
        "b11/coeff_zs": {"dims": ["detector", "px"], "data": [_col(600.0, ns)] * 2},
        "b11/coeff_d": {"dims": ["detector", "px"], "data": [_col(495.0 + d, ns) for d in range(2)]},
    }
    p = tmp_path / "S2A_ADF_REQOG_20240417T000000_21000101T000000_20240417T000000.json"
    p.write_text(json.dumps({"attrs": {"eopf:type": "ADF_REQOG"}, "data_vars": dv}))
    return str(p)


def test_r2eqog_eopf_cubic(tiny_eqog_adf):
    be = gipp.read_r2eqog_eopf(tiny_eqog_adf, "B03")
    assert be.source == "ESA EOPF ADF_REQOG" and be.npix == 8
    d1 = be.detectors[1]
    assert d1.model == "CUBIC" and set(d1.coeffs) == {"A", "B", "C"}
    assert np.allclose(d1.rel_gain, 0.99)                 # coeff_c
    assert d1.dark.shape == (8,)
    assert d1.dark.mean() == pytest.approx(441.0)          # mean of 3 sub-lines, det 1
    assert be.detectors[2].dark.mean() == pytest.approx(442.0)


def test_r2eqog_eopf_bilinear(tiny_eqog_adf):
    d1 = gipp.read_r2eqog_eopf(tiny_eqog_adf, "B11").detectors[1]
    assert d1.model == "BILINEAR" and set(d1.coeffs) == {"A1", "A2", "Zs"}
    assert np.allclose(d1.rel_gain, 0.95)                 # coeff_a1
    assert d1.dark.mean() == pytest.approx(495.0)


def test_read_r2eqog_eopf_case_insensitive_band(tiny_eqog_adf):
    assert gipp.read_r2eqog_eopf(tiny_eqog_adf, "b03").npix == 8   # lower-case band accepted


def test_load_gipp_set_eqog_adf_override(tiny_gipp, tiny_eqog_adf):
    """Equalization comes from the EOPF ADF; defective/blind/params still from the XML gipp_dir."""
    gs = gipp.load_gipp_set(tiny_gipp, bands=("B03", "B11"), eqog_adf=tiny_eqog_adf)
    assert gs.band("B03").source == "ESA EOPF ADF_REQOG"
    assert np.allclose(gs.band("B03").detectors[1].rel_gain, 0.99)
    assert list(gs.blind["B03"][1]) == [0, 1, 2, 3]        # still XML-sourced
    a = adf.BandADF.from_gipp(sensor.band("B03"), 1, gs)
    assert a.prnu_is_real and a.source == "ESA EOPF ADF_REQOG"
    # blind-column stripping to an active width (EOPF-sourced BandEq + XML BLINDP)
    a2 = adf.BandADF.from_gipp(sensor.band("B03"), 2, gs, active_width=4)
    assert a2.dark_dn.shape == (4,)


# --- ADF temporal validity ---------------------------------------------------

_ADF_NAME = "S2A_ADF_REQOG_20240417T000000_21000101T000000_20240417T000000.json"


def test_parse_eqog_adf_epoch():
    ep = gipp.parse_eqog_adf_epoch("/store/esa-adf/" + _ADF_NAME)
    assert ep["platform"] == "S2A" and ep["type"] == "REQOG"
    assert ep["applicability_start"] == "2024-04-17T00:00:00Z"
    assert ep["valid_stop"] == "2100-01-01T00:00:00Z"
    assert gipp.parse_eqog_adf_epoch("not-an-adf.json") == {}


def test_temporal_validity_flags_stale_adf():
    ep = gipp.parse_eqog_adf_epoch(_ADF_NAME)
    tv = gipp.temporal_validity(ep, "2018-08-20T08:36:01")   # turkey: 2018 vs 2024 ADF
    assert tv["warn"] is True and tv["within_validity"] is False
    assert tv["gap_years"] > 5


def test_temporal_validity_accepts_contemporary_adf():
    ep = gipp.parse_eqog_adf_epoch(_ADF_NAME)
    tv = gipp.temporal_validity(ep, "2024-05-26T01:16:38")   # ~5 weeks after applicability
    assert tv["warn"] is False and tv["within_validity"] is True
    assert tv["gap_years"] < 1


def test_temporal_validity_compact_date():
    ep = gipp.parse_eqog_adf_epoch(_ADF_NAME)
    assert gipp.temporal_validity(ep, "20240526T011638")["gap_years"] == pytest.approx(0.11, abs=0.02)


# --- optional: operational GIPP -----------------------------------------

def test_gipp_dark_matches_dqr_range():
    gipp_dir = os.environ.get("S2_GIPP_DIR")
    if not gipp_dir or not os.path.isdir(gipp_dir):
        pytest.skip("set S2_GIPP_DIR to the gipp-json folder to run")
    gs = gipp.load_gipp_set(gipp_dir)
    assert len(gs.equalization) == 13
    for b in sensor.BANDS:
        dark = gs.band(b).detectors[1].dark
        assert 400 <= dark.mean() <= 560 # DQR pedestal range (per-pixel)


def test_parse_eqog_adf_epoch_psfd_platform():
    ep = gipp.parse_eqog_adf_epoch(
        "S02B_ADF_REQOG_20231211T010000_21000101T000000_20231207T103000.json"
    )
    assert ep["platform"] == "S2B" and ep["type"] == "REQOG"
    assert ep["applicability_start"] == "2023-12-11T01:00:00Z"

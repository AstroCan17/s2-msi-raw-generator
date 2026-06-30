"""Tests for the original GIPP parser (``s2_e2es.gipp``) and ``BandADF.from_gipp``.

Structurally-faithful but tiny GIPP XML fixtures are generated inline (no large vendored files). An
optional test runs against the real operational GIPP when ``S2_E2ES_GIPP_DIR`` points at it.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from s2_e2es import adf, gipp, sensor


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
    assert a.prnu_is_real and a.source == "GIPP R2EQOG"
    assert a.dark_dn.shape == (8,) and a.prnu_gain.shape == (8,)
    assert np.allclose(a.prnu_gain, 0.99)
    # blind-column stripping to an active width
    a2 = adf.BandADF.from_gipp(sensor.band("B03"), 2, gs, active_width=4)
    assert a2.dark_dn.shape == (4,)


# --- optional: real operational GIPP -----------------------------------------

def test_real_gipp_dark_matches_dqr_range():
    gipp_dir = os.environ.get("S2_E2ES_GIPP_DIR")
    if not gipp_dir or not os.path.isdir(gipp_dir):
        pytest.skip("set S2_E2ES_GIPP_DIR to the real GIPP folder to run")
    gs = gipp.load_gipp_set(gipp_dir)
    assert len(gs.equalization) == 13
    for b in sensor.BANDS:
        dark = gs.band(b).detectors[1].dark
        assert 400 <= dark.mean() <= 560        # DQR pedestal range (real per-pixel)

"""End-to-end integration: synthetic L1B radiance → full reverse chain → complete L0 RAW product.

Exercises the whole pipeline (reverse_full = S1,S6,S7,S8,S10,S11–S14 + l0product S15 ISP) across
multiple detectors and bands (incl. reverse SWIR re-arrangement + injected defects), then validates the L0 RAW
EOProduct structure, quality masks, ISP telemetry, and sensor-config metadata.
"""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from s2_msi_raw_generator import adf, isp, l0product, reverse, sensor


def test_full_pipeline_l1b_to_l0_with_isp(tmp_path):
    detectors = [4, 7]
    bands = ["B02", "B03", "B04", "B08", "B11", "B12"]  # 10 m group + SWIR (TDI/defects)
    rng = np.random.default_rng(2026)

    l0_frames: dict[tuple[int, str], np.ndarray] = {}
    masks: dict[tuple[int, str], np.ndarray] = {}
    for det in detectors:
        for bn in bands:
            b = sensor.band(bn)
            width = 32 if b.gsd_m == 10 else 16
            radiance = np.clip(rng.normal(b.lref, b.lref * 0.3, size=(40, width)), 0, None)
            a = adf.synthesize(b, n_det=width, seed=det * 13 + len(bn))

            kwargs: dict = {}
            if bn in sensor.SWIR_BANDS:                       # S8 SWIR re-arrangement (reverse)
                shifts = np.zeros(width, dtype=int)
                shifts[::2] = 1
                kwargs["swir_shifts"] = shifts
            if bn == "B11":                                   # S10: 3 defective in B11
                kwargs["dead_cols"] = (2, 5, 9)
            if bn == "B12":                                   # S10: 1 defective in B12
                kwargs["hot_pixels"] = ((4, 3),)

            dn, qa = reverse.reverse_full(radiance, a, rng, **kwargs)
            l0_frames[(det, bn)] = dn
            masks[(det, bn)] = qa

    out = str(tmp_path / "S02MSIL0__synthetic.zarr")
    l0product.write_l0_product(out, l0_frames, masks=masks, with_isp=True)

    g = zarr.open_group(out, mode="r")

    # --- measurements: every detector/band frame, uint16 in range ---
    for det in detectors:
        for bn in bands:
            bkey, bnum = sensor.zarr_band_key(bn), sensor.band_number(bn)
            arr = g[f"measurements/d{det:02d}/{bkey}/band{bnum}"]
            assert arr.dtype == np.uint16
            data = arr[:]
            assert data.min() >= 0 and data.max() <= sensor.DN_MAX
            # ISP header per band (S15)
            ih = g[f"measurements/d{det:02d}/{bkey}/isp_header"]
            assert ih.shape == (40, isp.ISP_HEADER_LEN)

    # --- quality masks reflect injected defects (S2 MSK_QUALIT bit-planes) ---
    from s2_msi_raw_generator import quality
    assert np.all(g["quality/d04/b11/mask"][:][:, [2, 5, 9]] & quality.MSK_DEFECTIVE)  # B11 dead columns
    assert g["quality/d04/b12/mask"][4, 3] & quality.MSK_SATURATED                      # B12 hot pixel

    # --- conditions/anc_data SAD telemetry present for each APID ---
    apid = dict(g["measurements/d04/b03"].attrs)["apid"]
    assert g[f"conditions/anc_data/s{apid}/isp"].dtype == np.uint8
    assert g[f"conditions/anc_data/s{apid}/packet_data_length"].dtype == np.uint16

    # --- root metadata: sensor config ---
    attrs = dict(g.attrs)
    assert attrs["stac_discovery"]["properties"]["eopf:type"] == "S2MSIL0_"
    ac = attrs["other_metadata"]["sensor_configuration"]["acquisition_configuration"]
    assert ac["tdi_configuration_list"] == {"03": "APPLIED", "04": "APPLIED",
                                            "11": "APPLIED", "12": "APPLIED"}
    assert attrs["other_metadata"]["sensor_configuration"]["time_stamp"]["line_period"] \
        == pytest.approx(1.5658736)
    prov = attrs["processing_history"]["adf_provenance"]
    assert "SentiWiki" in prov["psf"]          # official ESA PSF
    assert "SRF" in prov["spectral"]           # SRF wavelengths

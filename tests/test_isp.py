"""Increment-4 tests: S15 CCSDS ISP packet generation + SAD telemetry + L0 with_isp."""

from __future__ import annotations

import numpy as np
import pytest

from s2_msi_raw_generator import isp, sensor


def test_primary_header_roundtrip():
    b = isp.build_primary_header(apid=1234, seq_count=42, data_len=2607)
    assert len(b) == isp.PRIMARY_HEADER_LEN
    f = isp.parse_primary_header(b)
    assert f["apid"] == 1234
    assert f["seq_count"] == 42
    assert f["data_len"] == 2607
    assert f["packet_type"] == 0 and f["sec_hdr_flag"] == 1
    assert f["seq_flags"] == isp.SEQ_STANDALONE


def test_primary_header_rejects_oversized_apid():
    with pytest.raises(ValueError):
        isp.build_primary_header(apid=2048, seq_count=0, data_len=0)  # 11-bit max is 2047


def test_cuc_time_encodes_coarse_and_fine():
    b = isp.cuc_time(5.5)
    assert len(b) == isp.CUC_TIME_LEN
    coarse = (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]
    fine = (b[4] << 8) | b[5]
    assert coarse == 5
    assert fine == 32768  # 0.5 * 65536


def test_parse_cuc_time_roundtrips():
    for t in (0.0, 5.5, 1.39e9 + 0.25):  # incl. a real 2024 GPS second-of-epoch
        assert isp.parse_cuc_time(isp.cuc_time(t)) == pytest.approx(t, abs=1.0 / 65536)


def test_frame_isp_headers_shape_seq_and_length():
    frame = np.zeros((20, 100), dtype=np.uint16)
    hdr, plen = isp.frame_isp_headers(frame, apid=1040, t0_seconds=0.0, line_period_s=1.5658736e-3)
    assert hdr.shape == (20, isp.ISP_HEADER_LEN)
    assert hdr.dtype == np.uint8
    # data field = CUC(6) + 100 samples * 2 octets = 206; length field stores the octet count
    assert np.all(plen == 6 + 100 * 2)
    # sequence count increments per line; APID preserved
    f0 = isp.parse_primary_header(bytes(hdr[0, :6]))
    f5 = isp.parse_primary_header(bytes(hdr[5, :6]))
    assert f0["apid"] == 1040 and f0["seq_count"] == 0
    assert f5["seq_count"] == 5
    assert f0["data_len"] == 6 + 100 * 2 - 1  # CCSDS: octets - 1


def test_frame_isp_timestamps_increment_by_line_period():
    frame = np.zeros((3, 4), dtype=np.uint16)
    lp = 1.5658736e-3
    hdr, _ = isp.frame_isp_headers(frame, apid=1040, t0_seconds=100.0, line_period_s=lp)
    def t(row):
        c = hdr[row, 6:10]; fi = hdr[row, 10:12]
        coarse = (int(c[0]) << 24) | (int(c[1]) << 16) | (int(c[2]) << 8) | int(c[3])
        fine = (int(fi[0]) << 8) | int(fi[1])
        return coarse + fine / 65536
    assert t(0) == pytest.approx(100.0, abs=1e-4)
    assert t(2) - t(0) == pytest.approx(2 * lp, abs=1e-4)


def test_build_sad_packets():
    sad, lengths = isp.build_sad_packets(apid=1305, n_packets=5, period_s=0.0125)
    assert sad.shape[0] == 5 and sad.dtype == np.uint8
    assert np.all(lengths == isp.CUC_TIME_LEN + 16)
    assert isp.parse_primary_header(bytes(sad[0, :6]))["apid"] == 1305


def test_apid_for_is_deterministic_and_11bit():
    a = isp.apid_for(4, sensor.BANDS.index("B03"))
    assert a == isp.apid_for(4, 2) and 0 <= a < (1 << 11)
    assert isp.apid_for(4, 2) != isp.apid_for(5, 2)


def test_l0_with_isp_writes_headers_and_telemetry(tmp_path):
    zarr = pytest.importorskip("zarr")
    from s2_msi_raw_generator import l0product
    frames = {(4, "B03"): np.full((16, 8), 100.0)}
    l0 = l0product.reverse_to_l0_frames(frames, seed=1)
    out = str(tmp_path / "L0isp.zarr")
    l0product.write_l0_product(out, l0, with_isp=True)

    g = zarr.open_group(out, mode="r")
    # per-band isp_header present
    ih = g["measurements/d04/b03/isp_header"]
    assert ih.shape == (16, isp.ISP_HEADER_LEN) and ih.dtype == np.uint8
    apid = dict(g["measurements/d04/b03"].attrs)["apid"]
    # conditions/anc_data/s{APID}/isp + packet_data_length present
    assert g[f"conditions/anc_data/s{apid}/isp"].dtype == np.uint8
    assert g[f"conditions/anc_data/s{apid}/packet_data_length"].dtype == np.uint16


def test_l0_isp_timestamps_use_real_gps_epoch(tmp_path):
    """REQ-FUNC-035: the CUC time in the written ISP headers is the real GPS OBT, not t0=0."""
    zarr = pytest.importorskip("zarr")
    from s2_msi_raw_generator import datation, l0product
    frames = {(4, "B03"): np.full((16, 8), 100.0)}
    l0 = l0product.reverse_to_l0_frames(frames, seed=1)
    out = str(tmp_path / "L0isp_epoch.zarr")
    d = datation.Datation(epoch_utc="2024-04-03T10:24:15Z")
    l0product.write_l0_product(out, l0, datation=d, with_isp=True)

    ih = np.asarray(zarr.open_group(out, mode="r")["measurements/d04/b03/isp_header"])
    t0 = isp.parse_cuc_time(bytes(ih[0, 6:12]))          # first-line CUC time
    assert t0 == pytest.approx(d.line_time_gps(0, "B03"), abs=1.0 / 65536)
    assert t0 > 1.30e9                                    # real GPS second-of-epoch, not zero

"""Tests for the L0 quality-flag layer (REQ-FUNC-040): QAFlag seeds + MSK_QUALIT masks."""

from __future__ import annotations

import numpy as np

from s2_msi_raw_generator import quality, sensor


def test_qaflag_bit_values_match_processor():
    # Identical to msi_processor.computing.common.types.QAFlag (monotone-OR interop).
    assert (quality.NO_DATA, quality.LOST_PACKET, quality.SATURATED, quality.DEFECTIVE) == (1, 2, 4, 8)


def test_l0_flags_seeds_saturation_nodata_defective_and_lost():
    dn = np.array([[480, sensor.DN_MAX, 5],
                   [480, 480, 480],
                   [0, 0, 0]], dtype=np.uint16)          # trailing all-zero line
    qa = quality.l0_flags(dn, dead_cols=(0,), hot_pixels=((0, 2),))
    assert qa.dtype == np.uint16
    assert qa[0, 1] & quality.SATURATED                  # DN == DN_MAX
    assert np.all(qa[:, 0] & quality.DEFECTIVE)          # dead column
    assert qa[0, 2] & quality.DEFECTIVE                  # hot pixel flagged defective
    assert np.all(qa[2, :] & quality.LOST_PACKET)        # wholly-zero trailing line
    assert np.all(qa[2, :] & quality.NO_DATA)            # ... and its zeros are no-data


def test_from_s10_qa_maps_dead_and_hot():
    s10 = np.array([[0, 1, 2]], dtype=np.uint8)          # bit0 dead, bit1 hot
    qa = quality.from_s10_qa(s10)
    assert qa[0, 0] == 0
    assert qa[0, 1] & quality.DEFECTIVE and not (qa[0, 1] & quality.SATURATED)
    assert qa[0, 2] & quality.SATURATED and not (qa[0, 2] & quality.DEFECTIVE)


def test_to_msk_qualit_plane_mapping():
    qa = np.array([[quality.NO_DATA, quality.LOST_PACKET, quality.SATURATED, quality.DEFECTIVE]],
                  dtype=np.uint16)
    mk = quality.to_msk_qualit(qa)
    assert mk.dtype == np.uint8
    assert mk[0, 0] == quality.MSK_NODATA
    assert mk[0, 1] == quality.MSK_MSI_LOST
    assert mk[0, 2] == quality.MSK_SATURATED
    assert mk[0, 3] == quality.MSK_DEFECTIVE

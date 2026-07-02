# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Space-packet segmentation tests: seq_flags grammar, continuity, exact reassembly."""

from __future__ import annotations

import numpy as np
import pytest

from s2_msi_raw_generator import isp


def _mk(payload_sizes, max_payload=64, seq_start=0):
    payload = b"".join(bytes([i % 251] * n) for i, n in enumerate(payload_sizes))
    bounds = list(np.cumsum([0] + list(payload_sizes[:-1])).astype(int))
    times = 1.39e9 + np.arange(len(bounds)) * 0.0125
    return payload, isp.packetize_stream(
        payload, 1090, segment_bounds=bounds, segment_times_gps=times,
        max_payload=max_payload, seq_start=seq_start)


def test_seq_flags_assignment():
    payload, (stream, offsets, lengths) = _mk([10, 200, 64], max_payload=64)
    flags = [h["seq_flags"] for h, _, _ in isp.iter_packets(stream)]
    # 10B → STANDALONE; 200B → FIRST,CONT,CONT,LAST (64*3=192 <200 ≤ 256); 64B → STANDALONE
    assert flags == [isp.SEQ_STANDALONE, isp.SEQ_FIRST, isp.SEQ_CONT, isp.SEQ_CONT,
                     isp.SEQ_LAST, isp.SEQ_STANDALONE]
    assert offsets.size == lengths.size == 6


def test_sequence_counter_continuous_mod_16384():
    _, (stream, offsets, _) = _mk([50] * 10, max_payload=16, seq_start=isp.SEQ_COUNT_MOD - 3)
    seqs = [h["seq_count"] for h, _, _ in isp.iter_packets(stream)]
    expect = [(isp.SEQ_COUNT_MOD - 3 + i) % isp.SEQ_COUNT_MOD for i in range(len(seqs))]
    assert seqs == expect


def test_reassemble_is_exact_inverse():
    sizes = [1, 8192, 100, 8193, 5]
    payload, (stream, _, _) = _mk(sizes, max_payload=1000)
    segs = isp.reassemble_segments(stream)
    assert [len(s) for s in segs] == sizes
    assert b"".join(segs) == payload


def test_cuc_time_per_segment():
    _, (stream, _, _) = _mk([100, 100], max_payload=30)
    times = [t for _, t, _ in isp.iter_packets(stream)]
    # all packets of segment 0 share its epoch; segment 1 is one line period (8 lines) later
    assert times[0] == times[1] == pytest.approx(1.39e9, abs=1e-4)
    assert times[-1] == pytest.approx(1.39e9 + 0.0125, abs=1e-4)


def test_offsets_and_lengths_tile_stream():
    _, (stream, offsets, lengths) = _mk([333, 4096, 7], max_payload=512)
    recs = offsets + isp.PRIMARY_HEADER_LEN + lengths
    assert offsets[0] == 0
    assert np.array_equal(offsets[1:], recs[:-1])
    assert int(recs[-1]) == stream.size


def test_reassemble_rejects_gaps_and_bad_grammar():
    _, (stream, offsets, _) = _mk([100, 100], max_payload=30)
    # drop one middle packet → sequence gap
    o1, o2 = int(offsets[1]), int(offsets[2])
    broken = np.concatenate([stream[:o1], stream[o2:]])
    with pytest.raises(ValueError, match="gap|FIRST|CONTINUATION"):
        isp.reassemble_segments(broken)
    # truncate inside a group → ends inside a segmented group / overrun
    with pytest.raises(ValueError):
        isp.reassemble_segments(stream[: int(offsets[-1])if False else int(offsets[1]) + 3])


def test_packetize_validates_inputs():
    with pytest.raises(ValueError):
        isp.packetize_stream(b"xx", 1090, segment_bounds=[1], segment_times_gps=np.array([0.0]))
    with pytest.raises(ValueError):
        isp.packetize_stream(b"xx", 1090, segment_bounds=[0], segment_times_gps=np.array([]))
    with pytest.raises(ValueError):
        isp.packetize_stream(b"xx", 1090, segment_bounds=[0], segment_times_gps=np.array([0.0]),
                             max_payload=0)

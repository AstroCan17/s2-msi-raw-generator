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

"""L0 quality flags — msi-processor ``QAFlag``-compatible seeds + Sentinel-2 ``MSK_QUALIT`` masks.

Two representations, one source of truth:

* :func:`l0_flags` → ``uint16`` bitmask using the **same** bit values as the processor's
  ``msi_processor.computing.common.types.QAFlag`` (``NO_DATA=1``, ``LOST_PACKET=2``, ``SATURATED=4``,
  ``DEFECTIVE=8``), so the processor's monotone OR-accumulation picks up the generator's seeds directly
  (the open-container ``quality/l0_flags/<band>``).
* :func:`to_msk_qualit` → ``uint8`` in the Sentinel-2 ``MSK_QUALIT`` 8-bit-plane layout (the canonical
  Synthetic L0 product mask ``quality/d{DD}/b{BB}/mask``).
"""

from __future__ import annotations

import numpy as np

from . import sensor

# msi-processor QAFlag bit values (common.types.QAFlag) — kept identical for OR-interoperability.
NO_DATA = 1
LOST_PACKET = 2
SATURATED = 4
DEFECTIVE = 8

# Sentinel-2 MSK_QUALIT sub-mask bit-planes (S2 PSD: 8 planes). The L0 seeds the ones it can assert.
MSK_ANC_LOST = 1 << 0
MSK_ANC_DEG = 1 << 1
MSK_MSI_LOST = 1 << 2
MSK_MSI_DEG = 1 << 3
MSK_DEFECTIVE = 1 << 4
MSK_NODATA = 1 << 5
MSK_CROSSTALK = 1 << 6
MSK_SATURATED = 1 << 7


def l0_flags(
    dn: np.ndarray,
    *,
    dead_cols: tuple[int, ...] = (),
    hot_pixels: tuple[tuple[int, int], ...] = (),
    dn_max: int = sensor.DN_MAX,
) -> np.ndarray:
    """QAFlag-compatible (``uint16``) L0 quality seed for one ``(line, detector)`` frame.

    Flags ``SATURATED`` where ``DN ≥ dn_max``, ``NO_DATA`` where ``DN == DN_NODATA`` (0), ``DEFECTIVE``
    on ``dead_cols`` / ``hot_pixels``, and ``LOST_PACKET`` on wholly-zero trailing lines (the
    processor's line-loss convention).
    """
    dn = np.asarray(dn)
    qa = np.zeros(dn.shape, dtype=np.uint16)
    qa[dn >= dn_max] |= SATURATED
    qa[dn == sensor.DN_NODATA] |= NO_DATA
    for c in dead_cols:
        qa[:, c] |= DEFECTIVE
    for r, c in hot_pixels:
        qa[r, c] |= DEFECTIVE
    nonzero = np.any(dn != 0, axis=1)
    if nonzero.any():
        last = int(np.max(np.nonzero(nonzero)))
        qa[last + 1:, :] |= LOST_PACKET
    return qa


def from_s10_qa(qa_s10: np.ndarray) -> np.ndarray:
    """Map the low-level ``reverse.s10_inject_defects`` qa (bit0 = dead, bit1 = hot) to QAFlag bits."""
    qa_s10 = np.asarray(qa_s10)
    qa = np.zeros(qa_s10.shape, dtype=np.uint16)
    qa[(qa_s10 & 1) != 0] |= DEFECTIVE   # dead column
    qa[(qa_s10 & 2) != 0] |= SATURATED   # hot / saturated pixel
    return qa


def to_msk_qualit(qa: np.ndarray) -> np.ndarray:
    """Translate a QAFlag ``uint16`` seed to the S2 ``MSK_QUALIT`` ``uint8`` 8-bit-plane mask."""
    qa = np.asarray(qa)
    out = np.zeros(qa.shape, dtype=np.uint8)
    out[(qa & NO_DATA) != 0] |= MSK_NODATA
    out[(qa & LOST_PACKET) != 0] |= MSK_MSI_LOST
    out[(qa & SATURATED) != 0] |= MSK_SATURATED
    out[(qa & DEFECTIVE) != 0] |= MSK_DEFECTIVE
    return out

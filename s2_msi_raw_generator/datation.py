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

"""GPS/OBT line datation for the L0 ISP — OBT/GPS/TAI line timing (ADF_DATAT model).

Replaces the placeholder ``t0 = 0`` CUC time with a Sentinel-2 on-board time derived from a
acquisition epoch. The MSI line-datation model (ADF_DATAT) is

    t(line, band) = epoch + line · line_period + time_shift(band)

expressed here on the **GPS** timescale (the S2 on-board clock is GPS-derived; the 32-bit CUC coarse
field holds the GPS second-of-epoch). UTC and TAI are offered for the product metadata
(``orbit_ephemeris`` carries TAI/UTC/UT1). ``msi-processor`` does not consume the CUC time for L1B, but
EOPF EOQC's ``Datation_Sync`` / ``Time_Correlation`` checks read the datation metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import sensor

# GPS epoch and the (stable since 2017-01-01) integer clock offsets — valid for the 2024 reference epoch.
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
GPS_UTC_OFFSET_S = 18     # GPS − UTC  (accumulated leap seconds − 19)
TAI_UTC_OFFSET_S = 37     # TAI − UTC

# A plausible Sentinel-2A morning descending-node acquisition (metadataism; overridable).
DEFAULT_EPOCH_UTC = "2024-04-03T10:24:15Z"


def _parse_utc(iso: str) -> datetime:
    """Parse an ISO-8601 UTC string (``Z`` or ``+00:00``) to an aware UTC datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Format an aware datetime as ``...Z`` ISO-8601 (millisecond precision; EOQC ISO_Time)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utc_to_gps_seconds(utc: datetime) -> float:
    """Seconds on the GPS timescale since the GPS epoch (1980-01-06T00:00:00)."""
    return (utc - GPS_EPOCH).total_seconds() + GPS_UTC_OFFSET_S


@dataclass(frozen=True)
class Datation:
    """Line-datation model for one acquisition (the ADF_DATAT parameters we need for the Synthetic L0)."""

    epoch_utc: str = DEFAULT_EPOCH_UTC
    line_period_s: float = sensor.LINE_PERIOD_MS / 1000.0
    time_shift_s: dict[str, float] = field(default_factory=dict)  # per-band along-track shift (default 0)

    @property
    def epoch(self) -> datetime:
        return _parse_utc(self.epoch_utc)

    @property
    def gps_epoch_s(self) -> float:
        """GPS second-of-epoch of the first line (the CUC/OBT ``t0``)."""
        return utc_to_gps_seconds(self.epoch)

    def _offset(self, line: int, band: str | None) -> float:
        return line * self.line_period_s + (self.time_shift_s.get(band, 0.0) if band else 0.0)

    def line_time_gps(self, line: int, band: str | None = None) -> float:
        """GPS seconds of ``line`` (optionally with the per-band along-track ``time_shift``)."""
        return self.gps_epoch_s + self._offset(line, band)

    def line_time_utc(self, line: int, band: str | None = None) -> datetime:
        return self.epoch + timedelta(seconds=self._offset(line, band))

    def span_utc(self, n_lines: int) -> tuple[str, str]:
        """``(start, end)`` UTC ISO for the acquisition (first → last line)."""
        return _iso_z(self.line_time_utc(0)), _iso_z(self.line_time_utc(max(n_lines - 1, 0)))

    def band_time_stamp(self) -> dict[str, dict]:
        """Per-band first-line GPS time stamp for the Synthetic L0 ``other_metadata`` (band number → {unit, value})."""
        return {
            sensor.band_number(b): {"unit": "s (GPS)", "value": self.line_time_gps(0, b)}
            for b in sensor.BANDS
        }

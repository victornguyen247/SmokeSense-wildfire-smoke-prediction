"""Per-site corrections for AirNow monitors whose UTC labels are wrong.

Some AirNow sites report readings under the wrong UTC hour for stretches of
time. Each entry here maps a station_id -- the identifier normalize_airnow_row
derives for monitor identity (StationID, then AQSID, then FullAQSCode, ...;
for /aq/data/ rows that is FullAQSCode, e.g. "061030007") -- to the periods
where its labels are off.

Sign convention: shift_hours is added to AirNow's UTC label to get the true
hour. Red Bluff, AirNow 2021-08-06T17:00 RawConcentration 204.0 is AQS 88101
Date GMT 2021-08-06, Time GMT 16:00, 204.0, so true = label - 1 h, and that
period has shift_hours = -1.

start_utc is inclusive and end_utc exclusive, both compared against AirNow's
label (not the corrected hour). Only periods backed by an hour-by-hour
comparison with AQS belong here; stations and times not covered are left
unchanged. See docs/data-sources.md for how to add a site.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class OffsetPeriod(NamedTuple):
    start_utc: datetime  # inclusive, AirNow label
    end_utc: datetime  # exclusive, AirNow label
    shift_hours: int  # true hour = label + shift_hours
    evidence: str


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# Red Bluff evidence: AirNow /aq/data/ RawConcentration (pulled 2026-10-05 for
# a small bbox around the site) vs AirData hourly_88101 POC 3, GMT columns,
# hour by hour. An hour counts for a shift when the values are equal at that
# shift and at no other. Where AirNow has no rows at a switch, the boundary
# is the first missing label after the last hour clearly at the old offset,
# so the change happens on an hour with no data and no two readings ever
# land on the same corrected hour.
AIRNOW_TIME_OFFSETS: dict[str, list[OffsetPeriod]] = {
    # Red Bluff - Walnut office, Tehama County APCD (AQS 06-103-0007).
    "061030007": [
        OffsetPeriod(
            _utc("2017-01-03T15:00"), _utc("2017-02-10T22:00"), +1,
            "560/560 unambiguous hours at +1 (2017-01-03 15:00 .. 2017-02-10 "
            "21:00). Starts at the first row with an AQS match; the 8 rows "
            "on Jan 1-3 before it have none, and nothing before 2017 was "
            "checked. Ends where the archive gap starts (no rows 2017-02-10 "
            "22:00 .. 2017-08-31 18:00). Checked 2026-10-05.",
        ),
        OffsetPeriod(
            _utc("2017-08-31T22:00"), _utc("2021-09-14T16:00"), -1,
            "Aug 31 19:00-21:00 match at 0 (3 hours, smoke values 96/90/76), "
            "22:00 missing, -1 from 23:00. Last -1 hour 2021-09-14 15:00 "
            "(61.0 = AQS 14:00), first 0 hour 16:00 (26.0 = AQS 16:00). "
            "18,699/18,700 unambiguous hours at -1, every year 2017-2021; the "
            "one 0 (2021-08-16 19:00) is AirNow repeating 127.0 on two "
            "labels. Checked 2026-10-05.",
        ),
        OffsetPeriod(
            _utc("2022-08-24T17:00"), _utc("2022-09-26T14:00"), -1,
            "Last 0 hour 2022-08-24 16:00, labels 17:00-19:00 missing, -1 "
            "from 20:00; boundary anywhere in 17:00-20:00 gives the same "
            "result. Last -1 hour 2022-09-26 13:00, then no AirNow or AQS "
            "data until 23:00. 508 unambiguous hours. Checked 2026-10-05.",
        ),
        OffsetPeriod(
            _utc("2022-09-26T14:00"), _utc("2022-10-01T07:00"), +1,
            "+1 from 2022-09-26 23:00 to 2022-10-01 03:00 (53 unambiguous "
            "hours); 04:00-06:00 fit +1 (04:00 and 05:00 rule out 0); label "
            "07:00 missing; 0 from 08:00. Checked 2026-10-05.",
        ),
        OffsetPeriod(
            _utc("2023-01-01T07:00"), _utc("2023-04-01T07:00"), -1,
            "Last 0 hour 2023-01-01 06:00, labels 07:00 .. 2023-01-03 23:00 "
            "missing, -1 from 2023-01-04 01:00. Last -1 hour 2023-04-01 "
            "06:00, label 07:00 missing, 08:00 fits -1 or 0, 0 from 09:00. "
            "1,289 unambiguous hours. Checked 2026-10-05.",
        ),
    ],
}


def max_abs_shift_hours() -> int:
    """Largest |shift_hours| in the config: how far a label can be off.

    Batch fetches pad their AirNow window by this on both ends, so a
    shifted site still has a row for the event's first and last hours.
    """

    return max(
        (
            abs(period.shift_hours)
            for periods in AIRNOW_TIME_OFFSETS.values()
            for period in periods
        ),
        default=0,
    )


def airnow_time_shift(station_id: str, label_utc: datetime) -> timedelta:
    """Correction to add to an AirNow UTC label for this station and hour."""

    for period in AIRNOW_TIME_OFFSETS.get(station_id, ()):
        if period.start_utc <= label_utc < period.end_utc:
            return timedelta(hours=period.shift_hours)
    return timedelta(0)

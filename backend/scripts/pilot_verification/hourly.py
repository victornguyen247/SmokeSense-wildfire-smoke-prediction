"""Hourly AirNow PM2.5 per site, true-hour corrected, grouped into local-standard-time days.

Days are UTC-8 (Pacific standard time all year), the convention AQS daily means use.
Red Bluff labels arrive already corrected: normalize_airnow_row applies
ingestion/connectors/airnow_time_offsets.py (on dev since PR #27).
"""
import json, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage2
from ingestion.connectors.airnow import normalize_airnow_row, split_airnow_range

LST = timedelta(hours=-8)


def site_hours(bbox, start, end):
    """{aqs: {"name","lat","lon","vals": {true_utc_hour: pm25}}} for local days start..end."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    pad = (e + timedelta(days=1)).isoformat()
    chunks = split_airnow_range(start, end) + [(pad, pad)]
    lo = datetime.combine(s, datetime.min.time(), timezone.utc) + timedelta(hours=8)
    hi = datetime.combine(e + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=8)
    out = {}
    for cs, ce in chunks:
        for row in stage2.airnow(bbox, cs, ce):
            rec = normalize_airnow_row(row)
            code = str(row.get("FullAQSCode"))
            site = out.setdefault(stage2.aqs(code), {"name": row["SiteName"].replace("  ", " "),
                                                     "lat": float(row["Latitude"]), "lon": float(row["Longitude"]), "vals": {}})
            if rec is None:
                continue
            # valid_at is already the true hour: normalize_airnow_row applies the
            # offset table, so shifting again here would double-correct.
            t = rec["observation"]["valid_at"]
            if lo <= t < hi:
                site["vals"][t] = rec["observation"]["pm25"]
    return out


def days(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return [s + timedelta(days=i) for i in range((e - s).days + 1)]


def by_day(vals):
    d = defaultdict(list)
    for t, v in vals.items():
        d[(t + LST).date()].append(v)
    return d

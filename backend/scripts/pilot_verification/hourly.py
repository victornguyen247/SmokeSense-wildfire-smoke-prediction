"""Hourly AirNow PM2.5 per site, true-hour corrected, grouped into local-standard-time days.

Days are UTC-8 (Pacific standard time all year), the convention AQS daily means use.
Red Bluff labels are corrected with PR #24's airnow_time_offsets table.
"""
import json, sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage2
from airnow_time_offsets import airnow_time_shift
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
            # normalize_airnow_row on dev applies no shift; apply PR #24's correction here.
            t = rec["observation"]["valid_at"] + airnow_time_shift(code, rec["observation"]["valid_at"])
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

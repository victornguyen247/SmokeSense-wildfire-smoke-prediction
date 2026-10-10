"""Item 6: elevation inputs -- event peak vs the pre-event baseline, per in-box AirNow site.

Baseline = median daily mean over the 7 local-standard-time days before the
event start, using only days with >= 18 valid hours (same day rule as item3).
Those days are pulled from AirNow on the event's tight bbox. Peaks come from
item3. Reported for the best site (most hours) and the max-peak site; no
thresholds are applied.
"""
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import hourly
from paths import OUT

BASELINE_DAYS = 7
MIN_HOURS = 18


def baseline_window(start):
    s = date.fromisoformat(start)
    return (s - timedelta(days=BASELINE_DAYS)).isoformat(), (s - timedelta(days=1)).isoformat()


def elevation(peak, base):
    if peak is None or base is None:
        return None, None
    return round(peak - base, 1), (round(peak / base, 2) if base > 0 else None)


def run(only=None):
    S2 = json.loads((OUT / "stage2.json").read_text())
    I3 = json.loads((OUT / "item3.json").read_text())
    outp = OUT / "item6.json"
    out = json.loads(outp.read_text()) if outp.exists() else {}
    for eid, r in S2.items():
        if only and eid not in only:
            continue
        in_box = {s["aqs"] for s in r["sites"] if s["pct_hours"] > 0}
        b0, b1 = baseline_window(r["start"])
        S = hourly.site_hours(r["bbox"], b0, b1) if in_box else {}
        sites = {}
        for code in sorted(in_box):
            days = hourly.by_day(S.get(code, {}).get("vals", {}))
            full = [sum(v) / len(v) for d, v in days.items() if len(v) >= MIN_HOURS]
            sites[code] = {"baseline": round(statistics.median(full), 1) if full else None,
                           "baseline_days": len(full)}
        i3 = I3.get(eid) or {}
        rec = {"baseline_window": [b0, b1], "sites": sites}
        for role, site_key, peak_key in (("best", "best", "best_peak"), ("max", "max_site", "max_peak")):
            code = i3.get(site_key)
            if code is None:
                rec[role] = None
                continue
            base = sites.get(code, {}).get("baseline")
            diff, ratio = elevation(i3[peak_key], base)
            rec[role] = {"aqs": code, "peak": i3[peak_key], "baseline": base,
                         "baseline_days": sites.get(code, {}).get("baseline_days", 0),
                         "peak_minus_baseline": diff, "peak_over_baseline": ratio}
        out[eid] = rec
        outp.write_text(json.dumps(out, indent=1))
        print(eid, "best", rec["best"], "| max", rec["max"])


if __name__ == "__main__":
    run(sys.argv[1:] or None)

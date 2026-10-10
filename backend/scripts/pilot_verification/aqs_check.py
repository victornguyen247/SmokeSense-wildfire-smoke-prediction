"""AQS (AirData hourly 88101/88502) vs AirNow for the dark days at PE-008, PE-011, PE-004 Paradise."""
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage2
from ingestion.connectors.airnow import split_airnow_range
from paths import CACHE, OUT

AD = CACHE / "airdata"
S2 = I2 = None  # loaded from out/ in main()


def aqs_rows(year, state="06", county=None, site=None):
    out = []
    for p in ("88101", "88502"):
        with open(AD / f"ca_hourly_{p}_{year}.csv") as f:
            for r in csv.DictReader(f):
                if county and r["County Code"] != county:
                    continue
                if site and r["Site Num"] != site:
                    continue
                r["gmt"] = datetime.fromisoformat(f"{r['Date GMT']}T{r['Time GMT']}").replace(tzinfo=timezone.utc)
                r["v"] = float(r["Sample Measurement"])
                out.append(r)
    return out


def airnow_raw(eid, code9):
    """Raw AirNow rows (label UTC -> RawConcentration) for one site over the event's cached pulls."""
    r = S2[eid]
    e = date.fromisoformat(r["end"]) + timedelta(days=1)
    out = {}
    for cs, ce in split_airnow_range(r["start"], r["end"]) + [(e.isoformat(), e.isoformat())]:
        for row in stage2.airnow(r["bbox"], cs, ce):
            if str(row.get("FullAQSCode"))[-9:] == code9:
                t = datetime.fromisoformat(row["UTC"]).replace(tzinfo=timezone.utc)
                out[t] = float(row["RawConcentration"])
    return out


CASES = [("PE-004", "06-007-2003", 2024)]

def main():
    global S2, I2
    S2 = json.loads((OUT / "stage2.json").read_text())
    I2 = {(r["event"], r["aqs"]): r for r in json.loads((OUT / "item2.json").read_text())}
    for eid, aqs, year in CASES:
        st, co, sn = aqs.split("-")
        A = aqs_rows(year, county=co, site=sn)
        dark = [x["day"] for x in I2[(eid, aqs)]["rows"] if x["hours"] == 0]
        print(f"\n== {eid} {aqs} {I2[(eid, aqs)]['name']}  dark LST days: {dark}")
        series = defaultdict(dict)  # (param, poc, method) -> {gmt: v}
        for r in A:
            series[(r["Parameter Code"], r["POC"], r["Method Code"], r["Method Name"][:45])][r["gmt"]] = r
        for key in series:
            print("   AQS series", key, "hours in year", len(series[key]))
        # dark days per series
        for d in dark:
            line = []
            for key, s in series.items():
                vals = [r["v"] for r in s.values() if r["Date Local"] == d]
                line.append(f"{key[0]}/POC{key[1]}: {len(vals)}h" + (f" peak {max(vals):.1f} mean {sum(vals)/len(vals):.1f}" if vals else ""))
            print(f"   {d}: " + " | ".join(line))
        # exact match on days both have data, shift 0, against each series
        an = airnow_raw(eid, "06" + co + sn)
        win_lo = datetime.fromisoformat(S2[eid]["start"]).replace(tzinfo=timezone.utc) + timedelta(hours=8)
        win_hi = datetime.fromisoformat(S2[eid]["end"]).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=8)
        an = {t: v for t, v in an.items() if win_lo <= t < win_hi and v != -999}
        print(f"   AirNow valid hours in window: {len(an)}")
        for key, s in series.items():
            both = [t for t in an if t in s]
            eq = sum(1 for t in both if abs(an[t] - s[t]["v"]) < 1e-6)
            sh = {}
            for k in (-1, 1):
                b2 = [t for t in an if (t + timedelta(hours=k)) in s]
                sh[k] = (sum(1 for t in b2 if abs(an[t] - s[t + timedelta(hours=k)]["v"]) < 1e-6), len(b2))
            diffs = sorted(((t, an[t], s[t]["v"]) for t in both if abs(an[t] - s[t]["v"]) >= 1e-6), key=lambda x: x[0])[:5]
            print(f"   {key[0]}/POC{key[1]} shift0 exact {eq}/{len(both)}  (shift -1: {sh[-1][0]}/{sh[-1][1]}, +1: {sh[1][0]}/{sh[1][1]})  first mismatches: "
                  + "; ".join(f"{t:%m-%d %H}Z AN {a} AQS {b}" for t, a, b in diffs))
            aqs_only = sorted({(t - timedelta(hours=8)).date().isoformat() for t in s if win_lo <= t < win_hi and t not in an})
            print(f"   {key[0]}/POC{key[1]} AQS hours with no AirNow row, by LST day: "
                  + ", ".join(f"{d}:{sum(1 for t in s if win_lo <= t < win_hi and t not in an and (t - timedelta(hours=8)).date().isoformat()==d)}" for d in aqs_only))


if __name__ == "__main__":
    main()

"""Item 3: peak daily mean PM2.5 (AirNow RawConcentration, LST days, >=18 h) per event."""
import json
import sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import hourly
from paths import EVENTS
from paths import OUT

TIER_RANGES = [("high", 125.45, 1e9), ("high-medium", 55.45, 125.45), ("medium-low", 35.45, 55.45), ("low", -1, 35.45)]


def tier_of(v):
    for t, lo, hi in TIER_RANGES:
        if lo <= v < hi:
            return t


def run(only=None):
    S2 = json.loads((OUT / "stage2.json").read_text())
    outp = OUT / "item3.json"
    out = json.loads(outp.read_text()) if outp.exists() else {}
    for eid, name, tier, start, end, *_ in EVENTS:
        if only and eid not in only:
            continue
        r = S2[eid]
        S = hourly.site_hours(r["bbox"], start, end)
        per = {}
        for code, s in S.items():
            dd = hourly.by_day(s["vals"])
            full = {d: sum(v) / len(v) for d, v in dd.items() if len(v) >= 18}
            if not s["vals"]:
                continue
            pk = max(full.items(), key=lambda kv: kv[1]) if full else (None, None)
            per[code] = {"name": s["name"], "hours": len(s["vals"]), "peak": pk[1], "peak_day": str(pk[0]) if pk[0] else None,
                         "complete_days": len(full), "days": len(hourly.days(start, end))}
        if not per:
            out[eid] = {"tier": tier, "best": None}
            continue
        # same "best site" as the doc's % hours column (most valid hours over the window, stage 2)
        ranked = [x["aqs"] for x in sorted(r["sites"], key=lambda x: -x["pct_hours"]) if x["aqs"] in per]
        best = ranked[0]
        top = max((c for c in per if per[c]["peak"] is not None), key=lambda c: per[c]["peak"])
        b, t = per[best], per[top]
        out[eid] = {"tier": tier, "best": best, "best_name": b["name"], "best_peak": round(b["peak"], 1), "best_day": b["peak_day"],
                    "best_tier": tier_of(b["peak"]), "max_site": top, "max_name": t["name"], "max_peak": round(t["peak"], 1),
                    "max_day": t["peak_day"], "max_tier": tier_of(t["peak"]), "sites": per}
        print(f"{eid} doc={tier:<12} best {b['name']} {b['peak']:.1f} ({b['peak_day']}) -> {tier_of(b['peak'])}"
              f" | max {t['name']} {t['peak']:.1f} ({t['peak_day']}) -> {tier_of(t['peak'])}")
    outp.write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    run(sys.argv[1:] or None)

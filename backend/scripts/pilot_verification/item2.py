"""Item 2: do the missing hours of sites <90% fall on peak-smoke days?

Day value = the site's own daily mean (LST day) from the hours that exist; on a
day the site is dark, the mean of its AirNow neighbours (other sites within
100 km), scaled by the median site/neighbour ratio over days both report.
Top quartile = the ceil(n/4) highest-valued days of the event window.
"""
import json, math, statistics, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import hourly, stage1

S2 = json.loads((HERE / "stage2.json").read_text())
R = 100.0


def neighbours(code, s, start, end):
    kx = stage1.km_per_deg_lon(s["lat"])
    box = [round(s["lon"] - R / kx, 2), round(s["lat"] - R / 111.32, 2), round(s["lon"] + R / kx, 2), round(s["lat"] + R / 111.32, 2)]
    W = hourly.site_hours(box, start, end)
    return {c: w for c, w in W.items() if c != code and w["vals"] and stage1.hav(s["lat"], s["lon"], w["lat"], w["lon"]) <= R}


def run():
    out = []
    for eid, r in S2.items():
        S = hourly.site_hours(r["bbox"], r["start"], r["end"])
        D = hourly.days(r["start"], r["end"])
        for code, s in S.items():
            if not s["vals"] or len(s["vals"]) / (24 * len(D)) >= 0.90:
                continue
            own = {d: (len(v), sum(v) / len(v)) for d, v in hourly.by_day(s["vals"]).items()}
            N = neighbours(code, s, r["start"], r["end"])
            nday = {}
            for w in N.values():
                for d, v in hourly.by_day(w["vals"]).items():
                    nday.setdefault(d, []).append(sum(v) / len(v))
            nmean = {d: statistics.mean(v) for d, v in nday.items()}
            ratios = [own[d][1] / nmean[d] for d in own if d in nmean and nmean[d] > 0]
            k = statistics.median(ratios) if ratios else 1.0
            rows = []
            for d in D:
                hrs, m = own.get(d, (0, None))
                val, src = (m, "own") if hrs else ((k * nmean[d], "nbr") if d in nmean else (None, "none"))
                rows.append({"day": str(d), "hours": hrs, "own_mean": m, "nbr_mean": nmean.get(d), "value": val, "src": src})
            ranked = sorted([x for x in rows if x["value"] is not None], key=lambda x: -x["value"])
            q = math.ceil(len(D) / 4)
            top = {x["day"] for x in ranked[:q]}
            for x in rows:
                x["top"] = x["day"] in top
            miss = lambda xs: (sum(24 - x["hours"] for x in xs), 24 * len(xs))
            mt, ht = miss([x for x in rows if x["top"]])
            mo, ho = miss([x for x in rows if not x["top"]])
            rec = {"event": eid, "aqs": code, "name": s["name"], "pct": round(100 * len(s["vals"]) / (24 * len(D)), 1),
                   "n_days": len(D), "q": q, "top_missing": mt, "top_hours": ht, "other_missing": mo, "other_hours": ho,
                   "top_share": round(100 * mt / ht, 1), "other_share": round(100 * mo / ho, 1) if ho else None,
                   "neighbours": [w["name"] for w in N.values()], "scale": round(k, 2),
                   "dark_top_days": [x["day"] for x in rows if x["top"] and x["hours"] == 0], "rows": rows}
            out.append(rec)
            print(f"{eid} {s['name']:<26} {rec['pct']}%  top-quartile ({q}d) missing {rec['top_share']}%  other missing {rec['other_share']}%"
                  f"  nbrs={len(N)} scale={k:.2f} dark top days={rec['dark_top_days']}")
    (HERE / "item2.json").write_text(json.dumps(out, indent=1, default=str))


run()

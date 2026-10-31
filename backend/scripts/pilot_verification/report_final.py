"""Write reports/final_check.md from a PILOT_EVENTS=final run (out_final)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import events_pr21
from paths import EVENTS, EVENTS_MODULE, OUT
from rules_final import ELEV_DIFF, ELEV_RATIO, MAX_OTHER_FRP, MIN_PCT_HOURS, NEAR_KM, evaluate

REPORT = HERE / "reports" / "final_check.md"
COLS = ["firms", "near_40km", "hours_75", "other_20", "elevation"]
YN = {True: "pass", False: "FAIL", None: "n/a"}


def tier_label(t):
    return "-".join(w.capitalize() for w in t.split("-")) if t else "—"


def main():
    S2, I3, I6 = (json.loads((OUT / n).read_text()) for n in ("stage2.json", "item3.json", "item6.json"))
    rows, failed = [], []
    for eid, name, _, start, end, counties, anchor in EVENTS:
        r = S2[eid]
        e = evaluate(r, I3.get(eid), I6.get(eid))
        if not e["pass"]:
            failed.append(eid)
        n, b = e["nearest"], e["best"]
        if e["tier"] == "low":
            elev = "n/a (Low)"
            if e["baseline"] is not None:
                elev += f"; {e['baseline']:.1f} → {e['peak_minus_baseline']:+.1f} (×{e['peak_over_baseline']:.2f})"
        elif e["baseline"] is None:
            elev = "no baseline"
        else:
            elev = f"{e['baseline']:.1f} → {e['peak_minus_baseline']:+.1f} (×{e['peak_over_baseline']:.2f})"
        if e["baseline_source"]:
            elev += f"; baseline: {e['baseline_source']}"
        doc = events_pr21.DOC_CHECK.get(eid) if eid not in ("PE-016", "PE-017") else None
        ref = f"{doc[4]} ({doc[1]})" if doc else "—"
        other = "—" if e["other_frp_share"] is None else f"{100 * e['other_frp_share']:.1f}%"
        bbox = ", ".join(f"{v:.2f}" for v in r["bbox"])
        if r.get("bbox_adjust"):
            bbox += f" — computed {', '.join(f'{v:.2f}' for v in r['bbox_computed'])}; {r['bbox_adjust']}"
        rows.append(
            f"| {eid} {name} | {start} → {end} | " + " | ".join(YN[e["rules"][k]] for k in COLS)
            + f" | **{'PASS' if e['pass'] else 'FAIL'}** | {tier_label(e['tier'])} | {e['tier_site_name'] or '—'}: "
            f"{e['peak'] if e['peak'] is not None else '—'} ({e['peak_day'] or '—'}) | {elev} "
            f"| {n['name'].replace('  ', ' ') + ', ' + str(n['dist_fire_km']) + ' km' if n else '—'} | "
            f"{(b['name'].replace('  ', ' ') + ', ' + str(b['pct_hours']) + '%') if b else '—'} | "
            f"{other} | {e['fire_detections']:,} "
            f"| {bbox} | {ref} |")

    lines = [
        "# Final pilot event check", "",
        "Run 2026-10-10 with `PILOT_EVENTS=final` (`events_final.py`) on live FIRMS `_SP` and AirNow `/aq/data/`. "
        "AirNow values are preliminary, not AQS.", "",
        "Rules (`rules_final.py`): **firms** ≥ 1 detection in the event's own FIRMS cluster; "
        f"**near_40km** nearest in-box AirNow site ≤ {NEAR_KM:.0f} km from the fire detections; "
        f"**hours_75** best site ≥ {MIN_PCT_HOURS:.0f}% of hours; "
        f"**other_20** in-box FRP from other fires < {100 * MAX_OTHER_FRP:.0f}%; "
        f"**elevation** (non-Low tiers) tier-site peak ≥ {ELEV_RATIO:.0f}× baseline and peak − baseline ≥ {ELEV_DIFF:.0f}. "
        "Tier: item3 `TIER_RANGES` (EPA 2024 AQI breakpoints) on the max peak daily mean over in-box sites "
        "(days ≥ 18 h); that site is the tier site. Baseline: median of the 7 pre-start LST days with ≥ 18 h; "
        "with fewer than 3 such days, the 20th percentile of the tier site's in-window daily means.", "",
        "| Event | Window | " + " | ".join(COLS) + " | Result | Tier | Tier site: peak (day) | Baseline → elevation "
        "| Nearest in-box site | Best site, % hours | Other-fire FRP | Fire detections | Bbox (W, S, E, N) and adjustment "
        "| AQS 50 km reference (PR #21) |",
        "|" + "---|" * (len(COLS) + 12),
        *rows, "",
        f"**{len(EVENTS) - len(failed)} of {len(EVENTS)} pass.**" + (f" Failed: {', '.join(failed)}." if failed else ""),
    ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"wrote {REPORT.relative_to(HERE)}; failed: {failed or 'none'}")
    return failed


if __name__ == "__main__":
    if EVENTS_MODULE.__name__ != "events_final":
        sys.exit("run with PILOT_EVENTS=final")
    sys.exit(1 if main() else 0)

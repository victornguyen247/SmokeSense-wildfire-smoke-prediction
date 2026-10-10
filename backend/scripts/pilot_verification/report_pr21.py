"""Write reports/pr21_check.md from a PILOT_EVENTS=pr21 run (stage2, item2, item3, item5, item6, anchors)."""
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import events
from paths import EVENTS, EVENTS_MODULE, OUT

PASS_KM = 40.0
REPORT = HERE / "reports" / "pr21_check.md"


def load(name, default=None):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else default


def tier_label(t):
    return "-".join(w.capitalize() for w in t.split("-")) if t else "—"


def fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def main():
    S2, I3 = load("stage2.json"), load("item3.json")
    I2, I5, I6 = load("item2.json", []), load("item5.json", {}), load("item6.json", {})
    anchors = load("anchors.json", {})
    doc = EVENTS_MODULE.DOC_CHECK
    old = {e[0]: e for e in events.EVENTS}

    rows = []
    for eid, name, tier, start, end, counties, anchor in EVENTS:
        r, i3, i6 = S2[eid], I3.get(eid) or {}, I6.get(eid) or {}
        d_aqs, d_name, d_dist, d_pct, d_peak = doc[eid]
        sites = [s for s in r["sites"] if s["pct_hours"] > 0]
        near = min((s for s in sites if s["dist_fire_km"] is not None), key=lambda s: s["dist_fire_km"], default=None)
        if near:
            nearest = f"{near['aqs']} {near['name'].replace('  ', ' ')}, {near['dist_fire_km']} km, {near['pct_hours']}%"
            passes = "Yes" if near["dist_fire_km"] <= PASS_KM else "No"
        else:
            wp = (r.get("wide_probe") or {}).get("nearest") or []
            nearest = "None in box" + (f" (nearest outside: {wp[0][2]} {wp[0][1]}, {wp[0][0]} km)" if wp else "")
            passes = "No"

        if i3.get("best"):
            peak = f"best {i3['best_name']} {fmt(i3['best_peak'])} ({tier_label(i3['best_tier'])})"
            if i3["max_site"] != i3["best"]:
                peak += f"; max {i3['max_name']} {fmt(i3['max_peak'])} ({tier_label(i3['max_tier'])})"
        else:
            peak = "No AirNow data"

        elev = []
        for role in ("best", "max"):
            e = i6.get(role)
            if e and (role == "best" or i3.get("max_site") != i3.get("best")):
                if e["baseline"] is None:
                    elev.append(f"{role}: no baseline (0 of 7 days with ≥ 18 h)")
                else:
                    ratio = "" if e["peak_over_baseline"] is None else f" (×{e['peak_over_baseline']:.2f})"
                    elev.append(f"{role} {e['baseline']:.1f} → {e['peak_minus_baseline']:+.1f}{ratio}")
        elev = "; ".join(elev) or "—"

        share = "—" if r.get("other_frp_share") is None else f"{100 * r['other_frp_share']:.1f}%"
        if eid in I5:
            share += f" in box; {I5[eid]['frp'][0]:.1f}% outside box within 200 km (median)"

        named = next((s for s in r["sites"] if s["aqs"] == d_aqs), None)
        named = f"Yes ({named['pct_hours']}%)" if named and named["pct_hours"] > 0 else "No"

        recs = [x for x in I2 if x["event"] == eid]
        dark = [f"{x['name']}: {', '.join(x['dark_top_days'])}" for x in recs if x["dark_top_days"]]
        dark = ("Yes — " + "; ".join(dark)) if dark else ("No" if recs else "n/a (no site < 90%)")

        rows.append(f"| {eid} {name} | {tier_label(tier)}; {d_peak} ({d_name} {d_aqs}) | {nearest} | {passes} | "
                    f"{peak} | {elev} | {share} | {named} | {dark} |")

    lines = [
        "# PR #21 event set vs AirNow tight-box rules",
        "",
        f"Generated {date.today().isoformat()} by `report_pr21.py` from a `PILOT_EVENTS=pr21` run of "
        "`run_all.py` (live FIRMS `_SP` and AirNow `/aq/data/`). AirNow values are preliminary, not AQS.",
        "",
        "| Event | PR #21 tier; peak (closest AQS site) | Nearest in-box AirNow site, distance to fire detections, % hours "
        f"| ≤ {PASS_KM:.0f} km? | AirNow peak daily PM2.5 (tier, item3 TIER_RANGES) | Baseline → elevation (item6) "
        "| Other-fire FRP share | PR #21 closest AQS site in AirNow, tight box? | Dark peak day (item2) |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Column notes:",
        "- **Nearest in-box AirNow site**: AirNow sites reporting PM2.5 inside the tight bbox during the window; "
        "distance is to the nearest FIRMS detection of the event's own cluster; % is of the window's UTC hours.",
        f"- **≤ {PASS_KM:.0f} km?**: that nearest site is within {PASS_KM:.0f} km of the fire detections.",
        "- **AirNow peak**: highest daily mean over local-standard-time days with ≥ 18 h. *best* is the site with "
        "the most hours, *max* the highest peak in the box (shown when different).",
        "- **Baseline → elevation**: baseline is the median daily mean over the 7 LST days before the start "
        "(days with ≥ 18 h), from AirNow on the tight box; elevation is peak − baseline (× peak / baseline).",
        "- **Other-fire FRP share**: share of in-box FIRMS FRP from clusters other than the event's (stage2); then "
        "item5's median share of FRP within 200 km of the in-box sites that lies outside the box.",
        "- **Dark peak day**: item2, for sites with < 90% hours: top-quartile days of the window with no hours at all.",
        "",
        "## Bboxes",
        "",
        "| Event | Window | Bbox (W, S, E, N) | Size (km) |",
        "|---|---|---|---|",
    ]
    for eid, name, tier, start, end, counties, anchor in EVENTS:
        r = S2[eid]
        lines.append(f"| {eid} | {start} → {end} | {', '.join(f'{v:.2f}' for v in r['bbox'])} "
                     f"| {r['width_km']} × {r['height_km']} |")

    lines += ["", "## Anchors", "",
              "The anchor only picks which FIRMS cluster in the county union is the event; the bbox is then "
              "built around that cluster.", "",
              "| Event | Anchor (lat, lon) | Source |", "|---|---|---|"]
    for eid, name, tier, start, end, counties, anchor in EVENTS:
        if eid in ("PE-017", "PE-019"):
            src = "Ignition point stated in the PR #21 doc (NIFC WFIGS)"
            if eid == "PE-019":
                src += "; Hennessey. The Walbridge ignition (38.5975, −122.9979) is a separate cluster, not used"
        elif eid in anchors:
            src = "New fire: centroid of the highest-FRP cluster in the county union (top 3 below)"
        elif eid in old and old[eid][6] == anchor:
            src = "Same fire as events.py (PR #26); its anchor kept"
        else:
            src = "Set by hand"
        lines.append(f"| {eid} {name} | {anchor[0]}, {anchor[1]} | {src} |")

    lines += ["", "Top 3 FIRMS clusters (FRP-weighted centroid) for the new fires, county union over the window:", ""]
    for eid, a in anchors.items():
        lines.append(f"- **{eid} {a['name']}** (union {', '.join(f'{v:.2f}' for v in a['union_bbox'])}; "
                     f"{a['detections']:,} detections):")
        for t in a["top3"]:
            lines.append(f"  - {t['lat']}, {t['lon']}: {t['n']:,} detections, FRP {t['frp']:,} MW, "
                         f"{t['first']} → {t['last']}")

    lines += ["", "## Overrides", "",
              "PR #26's per-event overrides in `stage1.py` are keyed by event id. For this set: LNU's link rule "
              "(PE-019) is kept, since it is the same fire; the River Complex exclusion is dropped, because PE-018 "
              "is now the Lake Fire; and PE-001's hand-widened bbox is not applied, so every event is checked on "
              "its computed tight box. FIRMS products are the `_SP` archive only: NOAA-21 (NRT) is not counted "
              "for PE-004 or PE-018."]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print(f"wrote {REPORT.relative_to(HERE)}")


if __name__ == "__main__":
    if EVENTS_MODULE.__name__ != "events_pr21":
        sys.exit("run with PILOT_EVENTS=pr21")
    main()

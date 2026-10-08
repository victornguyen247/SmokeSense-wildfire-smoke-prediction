"""Turn stage1/stage2/item3/item5 results into verdicts, config entries and doc-table rows."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from paths import OUT

SHORT = {"MODIS_SP": "MODIS", "VIIRS_SNPP_SP": "SNPP", "VIIRS_NOAA20_SP": "NOAA-20"}

# From docs/pilot-events.md on dev (region, NWS grid, PurpleAir density)
DOC = {
    "PE-001": ("Northern California (Trinity, Tehama, Glenn, Lake, Mendocino counties)", ["EKA", "STO"], "moderate"),
    "PE-003": ("Northern California (Mendocino, Lake, Colusa, Glenn counties)", ["EKA", "STO", "MTR"], "sparse"),
    "PE-004": ("Northern California (Butte, Tehama counties)", ["STO"], "excellent"),
    "PE-005": ("Bay Area / Diablo Range (Santa Clara, Alameda, Contra Costa, San Joaquin, Stanislaus counties)", ["MTR", "STO"], "excellent"),
    "PE-007": ("Northern California (Napa, Sonoma counties)", ["MTR"], "good"),
    "PE-010": ("Southern California (Los Angeles, Ventura counties)", ["LOX"], "moderate"),
    "PE-014": ("Sierra Nevada Foothills (Nevada, Placer counties)", ["STO"], "good"),
}
TIER = {"high": "high", "high-medium": "high-medium", "medium-low": "medium-low", "low": "low"}
from events import EVENTS
EV = {e[0]: e for e in EVENTS}

CONTAM = {
    "PE-001": "Zogg Fire (40.49,-122.62; 2020-09-27..11-06) lies inside the box: 3,321 detections, 2.3% of in-box FRP.",
    "PE-012": "A Yosemite-area fire (37.84,-119.62) is inside the box: 1.5% of in-box FRP.",
    "PE-019": "",
}


def best(sites):
    s = [x for x in sites if x["pct_hours"] > 0]
    return max(s, key=lambda x: x["pct_hours"]) if s else None


def nearest(r):
    s = [x for x in r["sites"] if x["pct_hours"] > 0 and x["dist_fire_km"] is not None]
    return min(s, key=lambda x: x["dist_fire_km"]) if s else None


def verdict(eid, r):
    tot = sum(r["firms_counts"].values())
    if tot == 0:
        wp = r.get("wide_probe", {}).get("nearest") or []
        near = f"nearest AirNow site {wp[0][1]} ({wp[0][2]}) is {wp[0][0]} km from the box centre" if wp else "no AirNow site within 150 km"
        return "FAIL", (f"0 FIRMS _SP detections in the bbox (MODIS_SP and VIIRS_SNPP_SP, {r['start']}..{r['end']}); "
                        f"no AirNow site reports in the bbox, so no monitor within 25 km; {near}. "
                        "All of Shasta County had 3 detections in the window, none inside the box: the fire named on dev "
                        "could not be found (open PR #21 says it does not exist).")
    if r["airnow_raw_rows"] == 0:
        wp = r.get("wide_probe", {})
        if not wp.get("nearest"):
            return "FAIL", (f"AirNow /aq/data/ has no rows in the bbox for the window and none in a 300 km box around the fire "
                            "(statewide California returns 0 rows for 2007 and 2008; AirNow coverage starts later). "
                            "Labels would need AQS/AirData instead.")
        n = wp["nearest"][0]
        return "FAIL", (f"No AirNow site reports in the bbox. Nearest site in a 1-day probe: {n[1]} ({n[2]}), "
                        f"{n[0]} km from the fire: inside the 150 km event rule, outside the 25 km rule. "
                        "Placerville and South Lake Tahoe (listed in the doc) do not report PM2.5 to AirNow in this window.")
    nb, bs = nearest(r), best(r["sites"])
    if bs["pct_hours"] < 75:
        return "BORDERLINE", (f"Only AirNow site {bs['name']} ({bs['aqs']}, {bs['dist_fire_km']} km) has {bs['pct_hours']}% of hours, "
                              "under the doc's 75% rule.")
    if r.get("other_frp_share", 0) > 0.2:
        oc = r["other_clusters"]
        return "BORDERLINE", (f"{round(100 * r['other_frp_share'])}% of in-box FRP is from other fires "
                              + "; ".join(f"({c['lat']},{c['lon']}, {c['n']:,} detections)" for c in oc[:2])
                              + ": the River Complex to the north and McFarland Fire to the south. Monitor is fine "
                              f"({nb['name']} {nb['aqs']}, {nb['dist_fire_km']} km, {nb['pct_hours']}%).")
    if nb["dist_fire_km"] > 25:
        return "BORDERLINE", (f"Nearest reporting AirNow site {nb['name']} ({nb['aqs']}) is {nb['dist_fire_km']} km from the fire "
                              f"({nb['pct_hours']}% of hours): passes the 150 km event rule but no monitor within 25 km, "
                              "so no training rows near the fire.")
    return "PASS", ""


def tier_label(t):
    return "-".join(w.capitalize() for w in t.split("-"))


def peak_cells(i3):
    """Peak daily PM2.5 and Tier confirmed? cells, in the format of docs/pilot-events.md."""
    if not i3 or i3.get("best") is None:
        return "No AirNow data", "Pending (no AirNow data)"
    peak = f"{i3['best_peak']:.1f} µg/m³ ({i3['best_name']}, {i3['best_day']}) — AirNow prelim."
    if i3["max_site"] != i3["best"]:
        peak += f" Max in bbox: {i3['max_peak']:.1f} ({i3['max_name']}, {i3['max_day']})"
    bt, dt = i3["best_tier"], i3["tier"]
    tier = f"Yes — {tier_label(bt)}" if bt == dt else f"No — measured {tier_label(bt)} (doc: {tier_label(dt)})"
    if i3["max_tier"] != bt:
        tier += f"; {tier_label(i3['max_tier'])} at {i3['max_name']}"
    return peak, tier


def main():
    S1 = json.loads((OUT / "stage1.json").read_text())
    S2 = json.loads((OUT / "stage2.json").read_text())
    I3 = json.loads((OUT / "item3.json").read_text())
    I5 = json.loads((OUT / "item5.json").read_text()) if (OUT / "item5.json").exists() else {}
    rows, entries = [], []
    for eid in sorted(S2):
        r = S2[eid]
        v, why = verdict(eid, r)
        r["verdict"], r["why"] = v, why
        rows.append(r)
        if v != "PASS":
            continue
        e = EV[eid]
        region, nws, pa = DOC[eid]
        s1 = S1[eid]
        prods = [p for p, n in r["firms_counts"].items() if n > 0]
        sites = [s for s in r["sites"] if s["pct_hours"] > 0]
        note = (f"Centred on the FRP-weighted centroid of the event's FIRMS _SP cluster ({s1['cluster']['lat']:.3f}, {s1['cluster']['lon']:.3f}): "
                f"the cluster's FRP-weighted 98th-percentile extent plus a 25 km buffer, symmetric about the centroid. "
                f"{r['width_km']} x {r['height_km']} km. ")
        if s1.get("bbox_adjust"):
            note += "E-W buffer " + s1["bbox_adjust"] + ". "
        if CONTAM.get(eid):
            note += "Other fires: " + CONTAM[eid]
        else:
            note += f"Other fires: {r['other_detections']} detections, {round(100 * r['other_frp_share'], 1)}% of in-box FRP."
        entries.append({
            "event_id": eid,
            "name": e[1],
            "region": region,
            "tier": TIER[e[2]],
            "start_date": e[3],
            "end_date": e[4],
            "bbox": ",".join(f"{x:.2f}" for x in r["bbox"]),
            "bbox_note": note.strip(),
            "nws_grid": nws,
            "airnow_monitors_nearby": [s["name"].replace("  ", " ") for s in sites],
            "purpleair_density": pa,
            "firms_products": prods,
            "firms_products_note": "Archive (_SP) products with detections in this bbox and window: "
                                   + ", ".join(f"{p} {r['firms_counts'][p]:,}" for p in prods)
                                   + ". VIIRS_NOAA21 has no _SP product.",
            "verification_status": "firms_airnow_verified",
            "verification_note": "FIRMS and AirNow checked 2026-10-06. AirNow sites in bbox (AQS id, distance to nearest fire detection, % of window hours with a valid RawConcentration): "
                                 + "; ".join(f"{s['name'].replace('  ', ' ')} {s['aqs']} {s['dist_fire_km']} km {s['pct_hours']}%" for s in sites)
                                 + ". Measured peak daily PM2.5 is in docs/pilot-events.md; the tier will be re-derived under the measured-peak thresholds.",
        })
    (OUT / "verdicts.json").write_text(json.dumps(rows, indent=1))
    (OUT / "entries.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False))

    # doc table
    lines = []
    for r in rows:
        eid = r["event_id"]
        fc = " / ".join(f"{SHORT[p]} {n:,}" for p, n in r["firms_counts"].items())
        tot = sum(r["firms_counts"].values())
        fc = f"{tot:,} ({fc})"
        sites = [s for s in r["sites"] if s["pct_hours"] > 0]
        if sites:
            ids = "<br>".join(f"{s['aqs']} {s['name'].replace('  ', ' ')} ({s['dist_fire_km']} km{'' if s['dist_fire_km'] <= 25 else ', >25'})" for s in sites)
            b = best(sites)
            pct = f"{b['pct_hours']}% ({b['name'].replace('  ', ' ')})"
        else:
            wp = (r.get("wide_probe") or {}).get("nearest") or []
            ids = "None in bbox" + (f" (nearest: {wp[0][2]} {wp[0][1]}, {wp[0][0]} km)" if wp else " (no AirNow data)")
            pct = "0%"
        peak, tier = peak_cells(I3.get(eid))
        lines.append(f"| {eid} | {ids} | {pct} | {peak} | {tier} | {fc} | Pending |")
    # item5: not a column of the doc's table, so it gets its own table below it
    lines += ["", "| ID | Outside-bbox share of FIRMS FRP within 200 km of in-bbox sites: median (min–max) "
                  "| Outside-bbox share of detections: median (min–max) |", "|---|---|---|"]
    for eid in sorted(I5):
        f, d = I5[eid]["frp"], I5[eid]["det"]
        lines.append(f"| {eid} | {f[0]}% ({f[1]}–{f[2]}%) | {d[0]}% ({d[1]}–{d[2]}%) |")
    (OUT / "doc_table.md").write_text("\n".join(lines) + "\n")
    for r in rows:
        print(r["event_id"], r["verdict"], r["width_km"], r["height_km"], r["why"][:150])


if __name__ == "__main__":
    main()

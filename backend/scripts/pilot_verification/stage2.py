"""Stage 2: verify each final bbox against FIRMS (_SP) and AirNow. Read-only; no DB."""
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/
import stage1
from paths import OFFLINE, OUT, CacheMiss, cache_dir
from events import EVENTS, products_for
from firms_pull import pull
from ingestion.connectors._common import load_env, redact
from ingestion.connectors.airnow import fetch_airnow_rows, normalize_airnow_row, split_airnow_range

load_env()
AKEY = os.environ.get("AIRNOW_API_KEY")  # only needed on a cache miss
ACACHE = cache_dir("airnow_cache")

# PE-020 has no fire to cluster on; verify the bbox already in backend/docs/pilot_events.json.
DEV_BBOX = {"PE-020": [-122.6, 40.4, -122.1, 40.8]}


def airnow(bbox, start, end, sh="00", eh="23"):
    f = ACACHE / (f"{stage1.fmt(bbox)}_{start}{sh}_{end}{eh}.json".replace(",", "_"))
    if f.exists():
        return json.loads(f.read_text())
    if OFFLINE:
        raise CacheMiss(f"airnow_cache/{f.name}")
    if not AKEY:
        raise RuntimeError("AIRNOW_API_KEY is not set")
    try:
        rows = fetch_airnow_rows(AKEY, bbox=stage1.fmt(bbox), start_date=start, start_hour=sh, end_date=end, end_hour=eh)
    except Exception as exc:
        raise RuntimeError(redact(str(exc), AKEY)[:300]) from None
    f.write_text(json.dumps(rows))
    return rows


def aqs(code):
    c = str(code)[-9:]
    return f"{c[:2]}-{c[2:5]}-{c[5:]}"


def verify(ev, S1):
    eid, name, tier, start, end, counties, anchor = ev
    s1 = S1[eid]
    bbox = s1.get("bbox") or DEV_BBOX[eid]
    res = {"event_id": eid, "name": name, "bbox": bbox, "start": start, "end": end}
    lat0 = (bbox[1] + bbox[3]) / 2
    res["width_km"] = round((bbox[2] - bbox[0]) * stage1.km_per_deg_lon(lat0))
    res["height_km"] = round((bbox[3] - bbox[1]) * 111.32)

    # ---- (a) FIRMS per product inside the final bbox
    rows = []
    counts = {}
    for p in products_for(start, end):
        r = pull(p, stage1.fmt(bbox), start, end)
        counts[p] = len(r)
        rows += r
    res["firms_counts"] = counts
    fire_pts = []
    if rows and anchor:
        excl = stage1.EXCLUDE.get(eid)
        comps = stage1.clusters(rows, stage1.LINK_OVERRIDE.get(eid))
        near = [k for k in comps if any(stage1.hav(anchor[0], anchor[1], float(r["latitude"]), float(r["longitude"])) <= 15 for r in k["rows"])]
        main = max(near, key=lambda k: k["frp"])
        if excl:  # re-split the main component on the documented exclusion
            mine = [r for r in main["rows"] if not excl(r)]
        else:
            mine = main["rows"]
        ids = {id(r) for r in mine}
        other = [r for r in rows if id(r) not in ids]
        frp_all = sum(max(float(r["frp"] or 0), 0) for r in rows) or 1
        frp_other = sum(max(float(r["frp"] or 0), 0) for r in other)
        res["fire_detections"] = len(mine)
        res["other_detections"] = len(other)
        res["other_frp_share"] = round(frp_other / frp_all, 3)
        # biggest other clusters, for naming contamination
        oc = stage1.clusters(other, stage1.LINK_OVERRIDE.get(eid)) if other else []
        res["other_clusters"] = [{"n": k["n"], "frp": round(k["frp"]), "lat": round(k["lat"], 3), "lon": round(k["lon"], 3),
                                  "first": min(r["acq_date"] for r in k["rows"]), "last": max(r["acq_date"] for r in k["rows"])}
                                 for k in oc[:3] if k["frp"] > 0.01 * frp_all]
        fire_pts = [(float(r["latitude"]), float(r["longitude"])) for r in mine]
        res["centroid"] = [round(s1["cluster"]["lat"], 3), round(s1["cluster"]["lon"], 3)]
    # thin points for distance calc (perimeter proxy)
    thin = list({(round(a, 2), round(b, 2)) for a, b in fire_pts})

    # ---- (b)/(c) AirNow monitors in bbox over the window (UTC dates, as batch_ingest requests them)
    total_hours = ((date.fromisoformat(end) - date.fromisoformat(start)).days + 1) * 24
    site_hours = defaultdict(set)
    site_meta = {}
    raw_rows = 0
    for cs, ce in split_airnow_range(start, end):
        for row in airnow(bbox, cs, ce):
            raw_rows += 1
            code = row.get("FullAQSCode") or row.get("IntlAQSCode")
            site_meta.setdefault(code, (row.get("SiteName"), float(row["Latitude"]), float(row["Longitude"]), row.get("AgencyName")))
            rec = normalize_airnow_row(row)
            if rec is not None:
                site_hours[code].add(rec["observation"]["valid_at"].isoformat())
    sites = []
    for code, (nm, la, lo, ag) in site_meta.items():
        d_c = stage1.hav(la, lo, *res["centroid"]) if "centroid" in res else None
        d_f = min((stage1.hav(la, lo, a, b) for a, b in thin), default=None)
        sites.append({"aqs": aqs(code), "name": nm, "lat": la, "lon": lo, "agency": ag,
                      "hours": len(site_hours[code]), "pct_hours": round(100 * len(site_hours[code]) / total_hours, 1),
                      "dist_centroid_km": None if d_c is None else round(d_c, 1),
                      "dist_fire_km": None if d_f is None else round(d_f, 1)})
    sites.sort(key=lambda s: (s["dist_fire_km"] if s["dist_fire_km"] is not None else 1e9))
    res["total_hours"] = total_hours
    res["airnow_raw_rows"] = raw_rows
    res["sites"] = sites

    # ---- nearest monitor outside the bbox, only when none inside reports near the fire
    if (not any(s["pct_hours"] > 0 for s in sites)) or min((s["dist_fire_km"] or 1e9) for s in sites) > 25:
        c = res.get("centroid") or [lat0, (bbox[0] + bbox[2]) / 2]
        kx = stage1.km_per_deg_lon(c[0])
        wide = [round(c[1] - 150 / kx, 2), round(c[0] - 150 / 111.32, 2), round(c[1] + 150 / kx, 2), round(c[0] + 150 / 111.32, 2)]
        mid = (date.fromisoformat(start) + (date.fromisoformat(end) - date.fromisoformat(start)) / 2).isoformat()
        wr = airnow(wide, mid, mid)
        seen = {}
        for row in wr:
            code = row.get("FullAQSCode")
            la, lo = float(row["Latitude"]), float(row["Longitude"])
            d = min((stage1.hav(la, lo, a, b) for a, b in thin), default=stage1.hav(la, lo, c[0], c[1]))
            seen[code] = (round(d, 1), row.get("SiteName"), aqs(code))
        res["wide_probe"] = {"bbox": wide, "date": mid, "sites": len(seen),
                             "nearest": sorted(seen.values())[:3]}
    return res


if __name__ == "__main__":
    only = sys.argv[1:]
    S1 = json.loads((OUT / "stage1.json").read_text())
    out_p = OUT / "stage2.json"
    out = json.loads(out_p.read_text()) if out_p.exists() else {}
    for ev in EVENTS:
        if only and ev[0] not in only:
            continue
        r = verify(ev, S1)
        out[ev[0]] = r
        out_p.write_text(json.dumps(out, indent=1, default=str))
        print(f"\n== {r['event_id']} {r['name']} bbox={stage1.fmt(r['bbox'])} {r['width_km']}x{r['height_km']} km")
        print(f"   FIRMS {r['firms_counts']}  fire={r.get('fire_detections')} other={r.get('other_detections')} other_frp_share={r.get('other_frp_share')}")
        for oc in r.get("other_clusters", []):
            print(f"     other cluster {oc}")
        print(f"   AirNow raw rows={r['airnow_raw_rows']} window hours={r['total_hours']}")
        for s in r["sites"]:
            print(f"     {s['aqs']} {s['name']:<32} {s['pct_hours']:5.1f}%  fire {s['dist_fire_km']} km  centroid {s['dist_centroid_km']} km")
        if "wide_probe" in r:
            print(f"   wide probe {r['wide_probe']}")

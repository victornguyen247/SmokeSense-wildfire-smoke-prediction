"""Item 5: share of FIRMS FRP / detections within 200 km of each in-bbox AirNow site that is outside the event bbox."""
import json, statistics, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage1
from events import products_for
from firms_pull import pull

S2 = json.loads((HERE / "stage2.json").read_text())
V = {v["event_id"]: v["verdict"] for v in json.loads((HERE / "verdicts.json").read_text())}
RAD = 200.0


def hav_np(lat, lon, la, lo):
    p1, p2 = np.radians(lat), np.radians(la)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo - lon) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def run(only=None):
    outp = HERE / "item5.json"
    out = json.loads(outp.read_text()) if outp.exists() else {}
    for eid, r in S2.items():
        if V[eid] == "FAIL" or (only and eid not in only) or eid in out:
            continue
        sites = [s for s in r["sites"] if s["pct_hours"] > 0]
        boxes = []
        for s in sites:
            kx = stage1.km_per_deg_lon(s["lat"])
            boxes.append([s["lon"] - RAD / kx, s["lat"] - RAD / 111.32, s["lon"] + RAD / kx, s["lat"] + RAD / 111.32])
        big = [round(min(b[0] for b in boxes), 2), round(min(b[1] for b in boxes), 2),
               round(max(b[2] for b in boxes), 2), round(max(b[3] for b in boxes), 2)]
        rows = []
        for p in products_for(r["start"], r["end"]):
            rows += pull(p, stage1.fmt(big), r["start"], r["end"])
        lat = np.array([float(x["latitude"]) for x in rows]); lon = np.array([float(x["longitude"]) for x in rows])
        frp = np.array([max(float(x["frp"] or 0), 0.0) for x in rows])
        b = r["bbox"]
        inside = (lon >= b[0]) & (lon <= b[2]) & (lat >= b[1]) & (lat <= b[3])
        per = []
        any_near = np.zeros(len(rows), bool)
        for s in sites:
            near = hav_np(s["lat"], s["lon"], lat, lon) <= RAD
            any_near |= near
            n, no = int(near.sum()), int((near & ~inside).sum())
            f, fo = float(frp[near].sum()), float(frp[near & ~inside].sum())
            per.append({"aqs": s["aqs"], "name": s["name"].replace("  ", " "), "det": n, "det_out": no,
                        "det_share": round(100 * no / n, 1) if n else None, "frp_share": round(100 * fo / f, 1) if f else None})
        rec = {"bbox": b, "query_box": big, "detections_pulled": len(rows), "sites": per}
        fs = [x["frp_share"] for x in per if x["frp_share"] is not None]
        ds = [x["det_share"] for x in per if x["det_share"] is not None]
        rec["frp"] = [statistics.median(fs), min(fs), max(fs)]
        rec["det"] = [statistics.median(ds), min(ds), max(ds)]
        if eid in ("PE-001", "PE-005"):
            sel = [rows[i] for i in np.where(any_near & ~inside)[0]]
            cl = stage1.clusters(sel)
            rec["outside_clusters"] = [{"n": k["n"], "frp": round(k["frp"]), "lat": round(k["lat"], 3), "lon": round(k["lon"], 3),
                                        "first": min(x["acq_date"] for x in k["rows"]), "last": max(x["acq_date"] for x in k["rows"])}
                                       for k in cl[:8]]
        out[eid] = rec
        outp.write_text(json.dumps(out, indent=1))
        print(f"{eid} {V[eid]:<10} sites={len(per)} FRP-out med/min/max {rec['frp']}  det-out {rec['det']}  pulled={len(rows)}", flush=True)


run(sys.argv[1:] or None)

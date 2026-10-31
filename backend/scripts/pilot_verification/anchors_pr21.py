"""Top 3 FIRMS clusters in each county union, for events whose anchor is a new fire.

The anchors of PR #21's new fires (PE-006, -009, -011, -016, -018, -020) are the
centroids of the highest-FRP cluster listed here. Run with PILOT_EVENTS=pr21.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import stage1
from firms_pull import pull
from paths import EVENTS, EVENTS_MODULE, OUT, products_for

NEW_FIRES = ("PE-006", "PE-009", "PE-011", "PE-016", "PE-018", "PE-020")


def run(only=None):
    out = {}
    for eid, name, tier, start, end, counties, anchor in EVENTS:
        if eid not in NEW_FIRES or (only and eid not in only):
            continue
        ub = stage1.union_bbox(counties)
        rows = []
        for p in products_for(start, end):
            rows += pull(p, stage1.fmt(ub), start, end)
        top = [{"n": k["n"], "frp": round(k["frp"]), "lat": round(k["lat"], 3), "lon": round(k["lon"], 3),
                "first": min(r["acq_date"] for r in k["rows"]), "last": max(r["acq_date"] for r in k["rows"])}
               for k in stage1.clusters(rows)[:3]]
        out[eid] = {"name": name, "union_bbox": ub, "detections": len(rows), "top3": top, "anchor": anchor}
        print(eid, name, "union", stage1.fmt(ub), "detections", len(rows), "anchor", anchor)
        for t in top:
            print("   ", t)
    (OUT / "anchors.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    if EVENTS_MODULE.__name__ != "events_pr21":
        sys.exit("run with PILOT_EVENTS=pr21")
    run(sys.argv[1:] or None)

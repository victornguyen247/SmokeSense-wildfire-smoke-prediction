"""Stage 1: county-union FIRMS pull -> FRP-weighted clusters -> fire-centred bbox."""
import json, math, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from events import EVENTS, products_for
from firms_pull import pull

COUNTIES = json.loads((HERE / "ca_counties.json").read_text())
CELL = 0.05          # deg grid for clustering
LINK = 1             # neighbouring 0.05-deg cells (gaps < ~5-10 km) join the same cluster

# LNU's Aug-18 run toward Lake Berryessa sits >1 cell from the Aug-17 core; it is the same fire.
LINK_OVERRIDE = {"PE-019": 2}

# Documented, per-event exclusions of detections that belong to a different fire
# but touch this one on the grid (see first-detection-date analysis in the PR).
EXCLUDE = {
    # River Complex: burning at >= 41.0N by day 1-5; Monument's front reached 40.9N only on day 24-29.
    "PE-018": lambda r: float(r["latitude"]) >= 41.0,
}
BUFFER_KM = 25.0     # buffer beyond the cluster's extent (matches the 25 km label rule)


def km_per_deg_lon(lat):
    return 111.32 * math.cos(math.radians(lat))


def hav(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def union_bbox(counties):
    bs = [COUNTIES[c] for c in counties]
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def fmt(b):
    return ",".join(f"{v:.2f}" for v in b)


def clusters(rows, link=None):
    link = link or LINK
    cells = defaultdict(list)
    for r in rows:
        cells[(math.floor(float(r["latitude"]) / CELL), math.floor(float(r["longitude"]) / CELL))].append(r)
    seen, comps = set(), []
    for c in cells:
        if c in seen:
            continue
        stack, comp = [c], []
        seen.add(c)
        while stack:
            cur = stack.pop()
            comp.extend(cells[cur])
            for di in range(-link, link + 1):
                for dj in range(-link, link + 1):
                    n = (cur[0] + di, cur[1] + dj)
                    if n in cells and n not in seen:
                        seen.add(n)
                        stack.append(n)
        frp = [max(float(r["frp"] or 0), 0.0) for r in comp]
        W = sum(frp) or 1.0
        lat = sum(float(r["latitude"]) * w for r, w in zip(comp, frp)) / W
        lon = sum(float(r["longitude"]) * w for r, w in zip(comp, frp)) / W
        comps.append({"rows": comp, "n": len(comp), "frp": sum(frp), "lat": lat, "lon": lon})
    comps.sort(key=lambda k: -k["frp"])
    return comps


def wpct(vals, weights, q):
    """FRP-weighted percentile: low-FRP stragglers (ag burns, noise) barely move it."""
    pairs = sorted(zip(vals, weights))
    W = sum(weights) or 1.0
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * W:
            return v
    return pairs[-1][0] if pairs else 0


def fire_bbox(comp):
    lat0, lon0 = comp["lat"], comp["lon"]
    kx = km_per_deg_lon(lat0)
    w = [max(float(r["frp"] or 0), 0.0) for r in comp["rows"]]
    dx = [abs(float(r["longitude"]) - lon0) * kx for r in comp["rows"]]
    dy = [abs(float(r["latitude"]) - lat0) * 111.32 for r in comp["rows"]]
    hx = wpct(dx, w, 0.98) + BUFFER_KM
    hy = wpct(dy, w, 0.98) + BUFFER_KM
    b = [lon0 - hx / kx, lat0 - hy / 111.32, lon0 + hx / kx, lat0 + hy / 111.32]
    return [round(b[0], 2), round(b[1], 2), round(b[2], 2), round(b[3], 2)], 2 * hx, 2 * hy


def main(only=None):
    out = {}
    for ev in EVENTS:
        eid, name, tier, start, end, counties, anchor = ev
        if only and eid not in only:
            continue
        ub = union_bbox(counties)
        prods = products_for(start, end)
        rows = []
        for p in prods:
            rows += pull(p, fmt(ub), start, end)
        excl = EXCLUDE.get(eid)
        comps = clusters([r for r in rows if not (excl and excl(r))], LINK_OVERRIDE.get(eid))
        print(f"\n== {eid} {name} {start}..{end} union={fmt(ub)} products={prods} detections={len(rows)}")
        for k in comps[:6]:
            d = hav(anchor[0], anchor[1], k["lat"], k["lon"]) if anchor else float("nan")
            print(f"   cluster n={k['n']:6d} frp={k['frp']:10.0f} at {k['lat']:.3f},{k['lon']:.3f}  anchor_dist={d:6.1f} km")
        chosen = None
        if anchor:
            near = [k for k in comps if min(hav(anchor[0], anchor[1], float(r["latitude"]), float(r["longitude"])) for r in k["rows"]) <= 15]
            chosen = max(near, key=lambda k: k["frp"]) if near else None
        rec = {"union_bbox": ub, "products": prods, "union_detections": len(rows),
               "top_cluster": None if not comps else {k: comps[0][k] for k in ("n", "frp", "lat", "lon")}}
        if chosen:
            b, wkm, hkm = fire_bbox(chosen)
            rec.update(cluster={k: chosen[k] for k in ("n", "frp", "lat", "lon")}, bbox=b, width_km=wkm, height_km=hkm,
                       top_is_chosen=chosen is comps[0])
            print(f"   CHOSEN n={chosen['n']} frp={chosen['frp']:.0f} centroid {chosen['lat']:.3f},{chosen['lon']:.3f} "
                  f"bbox={fmt(b)} ({wkm:.0f} x {hkm:.0f} km)  top_is_chosen={chosen is comps[0]}")
        else:
            print("   CHOSEN: none (no cluster within 15 km of anchor)")
        out[eid] = rec
    return out


if __name__ == "__main__":
    only = sys.argv[1:] or None
    res = main(only)
    p = HERE / "stage1.json"
    prev = json.loads(p.read_text()) if p.exists() else {}
    prev.update(res)
    p.write_text(json.dumps(prev, indent=1))

"""Generate docs/api/fixtures/*.json for PM-02 (Park Fire, PE-004, 2024-07-27 18:00Z).

Applies the PM-03 serving contract: Stage A at AirNow monitors (h1 persistence,
h3-24 v2), Stage B IDW to the GEO-02 grid (12.5 km squares in EPSG:3310, k=4,
50 km, w=1/max(d,1)^2).
Usage: pip install -r docs/api/requirements.txt && python docs/api/gen_fixtures.py [out_dir]
out_dir defaults to docs/api/fixtures. CI regenerates into a temp dir and diffs it
against the committed fixtures, so edit this script rather than the JSON.
"""

import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyproj import Transformer

DEFAULT_OUT = Path(__file__).resolve().parent / "fixtures"
UTC = timezone.utc
ISSUED = datetime(2024, 7, 27, 18, 0, tzinfo=UTC)
NOW = datetime(2024, 7, 27, 18, 40, tzinfo=UTC)
MODEL_KEY = "baseline_v2/1.0.0"
AQI_TABLE = "epa-2024"
HORIZONS = (1, 3, 6, 12, 24)
LOW_CONFIDENCE_KM = 25
MAX_IDW_KM = 50
AQI_LABEL = "AQI category (hourly PM2.5)"

# GEO-02 grid (backend/app/db/seed_ca_forecast_grid.py): squares aligned to EPSG:3310 multiples.
CELL_M = 12_500
GRID_KEY = f"grid-ca-epsg3310-{CELL_M}m"
TO_3310 = Transformer.from_crs(4326, 3310, always_xy=True)
TO_4326 = Transformer.from_crs(3310, 4326, always_xy=True)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def uuid7(seed, t=ISSUED):
    """Deterministic UUIDv7-shaped id (48-bit ms timestamp + hashed tail)."""
    ms = int(t.timestamp() * 1000)
    tail = hashlib.sha256(seed.encode()).hexdigest()
    h = f"{ms:012x}" + "7" + tail[:3] + "8" + tail[3:18]
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def external_id(prefix, *parts):
    """Same shape as ingestion.normalize.stable_external_id (GEO-02 monitor point ids)."""
    return f"{prefix}:" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.008
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# EPA 2024 PM2.5 breakpoints, applied to pm25 truncated to 0.1 µg/m³ (EPA/AirNow practice).
# TODO: import from shared/aqi.py once backend/shared/aqi.py exists (the table is also in
# docs/api.md and openapi.yaml until then).
AQI = [
    ("good", "Good", "#00E400", 0.0, 9.0),
    ("moderate", "Moderate", "#FFFF00", 9.1, 35.4),
    ("unhealthy_sensitive", "Unhealthy for Sensitive Groups", "#FF7E00", 35.5, 55.4),
    ("unhealthy", "Unhealthy", "#FF0000", 55.5, 125.4),
    ("very_unhealthy", "Very Unhealthy", "#8F3F97", 125.5, 225.4),
    ("hazardous", "Hazardous", "#7E0023", 225.5, None),
]


def t1(pm25):
    """Truncate to 0.1 (the epsilon absorbs float error such as 35.4 * 10 = 353.99...)."""
    return round(math.floor(pm25 * 10 + 1e-9) / 10, 1)


def category(pm25):
    # From the truncated value, which is also what `pm25` returns, so the two always agree.
    v = t1(pm25)
    for key, _, _, lo, hi in AQI:
        if hi is None or v <= hi:
            return key
    raise AssertionError


def r1(x):
    return round(x, 1)


def pt(lat, lon):
    return {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}


# --- Stage A: AirNow monitors (real sites from dataset_build/airnow_sites.csv) ---
# pm25 per horizon 1/3/6/12/24. h1 = persistence = the 17:00Z reading.
MONITORS = [
    ("060070008", "Chico - East", 39.76168, -121.84047, "v2", [88.4, 95.1, 104.7, 79.6, 91.2]),
    ("060072003", "Paradise - Clark Road", 39.757861, -121.607908, "v2", [131.6, 142.3, 150.8, 112.4, 127.9]),
    ("061030007", "Red Bluff - Walnut office", 40.170917, -122.255667, "v2", [61.2, 66.8, 72.5, 54.3, 63.0]),
    ("060210003", "Willows-Colusa", 39.53387, -122.190834, "v2", [42.7, 46.9, 51.8, 38.2, 44.6]),
    ("060610003", "Auburn", 38.93568, -121.09959, "v2", [17.9, 19.6, 22.4, 15.1, 18.8]),
    ("060610004", "Colfax", 39.1003, -120.9528, "v2", [21.3, 23.0, 26.1, 18.4, 22.5]),
    # No regulatory reading in the last 6 h -> v1 fallback; never feeds a cell.
    ("061050002", "Weaverville", 40.734722, -122.941109, "fallback", [33.0, 34.8, 37.2, 29.5, 31.9]),
]

monitors = []
for code, name, lat, lon, src, vals in MONITORS:
    srcs = ["persistence" if (h == 1 and src == "v2") else src for h in HORIZONS]
    monitors.append({
        "forecast_point_id": external_id("airnow", code),
        "monitor_id": uuid7("monitors:" + code, datetime(2024, 3, 2, tzinfo=UTC)),
        "aqs_code": code, "name": name, "lat": lat, "lon": lon,
        "by_h": {h: (v, s) for h, v, s in zip(HORIZONS, vals, srcs)},
    })


def eligible(m, h):
    return m["by_h"][h][1] in ("v2", "persistence")


def idw(lat, lon, h):
    """Stage B for one centroid and horizon. None when no eligible monitor ≤ 50 km."""
    near = []
    for m in monitors:
        if not eligible(m, h):
            continue
        d = haversine(lat, lon, m["lat"], m["lon"])
        if d <= MAX_IDW_KM:
            near.append((d, m["by_h"][h][0]))
    if not near:
        return None
    near.sort()
    near = near[:4]
    w = [1 / max(d, 1.0) ** 2 for d, _ in near]
    return sum(wi * v for wi, (_, v) in zip(w, near)) / sum(w), near[0][0]


def nearest_eligible_km(lat, lon):
    """Distance to the nearest monitor Stage B could use this cycle, with no 50 km limit."""
    ds = [haversine(lat, lon, m["lat"], m["lon"]) for m in monitors if any(eligible(m, h) for h in HORIZONS)]
    return r1(min(ds)) if ds else None


# --- GEO-02 grid cells ---
def cell_id(row, col):
    return f"{GRID_KEY}-r{row:+07d}-c{col:+07d}-p00"


def cell(row, col):
    """One unclipped square (the fixture area is inland, so every cell is part 00)."""
    x0, y0, x1, y1 = col * CELL_M, row * CELL_M, (col + 1) * CELL_M, (row + 1) * CELL_M
    ring = [TO_4326.transform(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    clon, clat = TO_4326.transform((x0 + x1) / 2, (y0 + y1) / 2)
    return {
        "id": cell_id(row, col), "lat": clat, "lon": clon,
        "ring": [[round(lon, 5), round(lat, 5)] for lon, lat in ring],
    }


def cell_at(lat, lon):
    x, y = TO_3310.transform(lon, lat)
    return cell(math.floor(y / CELL_M), math.floor(x / CELL_M))


def cells_in_bbox(bbox):
    """Cells whose polygon intersects the bbox (densified so the curved edges are covered)."""
    w, s, e, n = bbox
    edge = [(w + (e - w) * i / 20, s) for i in range(21)] + [(w + (e - w) * i / 20, n) for i in range(21)]
    edge += [(w, s + (n - s) * i / 20) for i in range(21)] + [(e, s + (n - s) * i / 20) for i in range(21)]
    xs, ys = zip(*(TO_3310.transform(lon, lat) for lon, lat in edge))
    out = []
    for row in range(math.floor(min(ys) / CELL_M), math.floor(max(ys) / CELL_M) + 1):
        for col in range(math.floor(min(xs) / CELL_M), math.floor(max(xs) / CELL_M) + 1):
            c = cell(row, col)
            lons, lats = zip(*c["ring"])
            if min(lons) < e and max(lons) > w and min(lats) < n and max(lats) > s:
                out.append(c)
    return sorted(out, key=lambda c: c["id"])


def fv(h, pm25, method, source, dist):
    return {
        "horizon_hours": h,
        "target_time": iso(ISSUED + timedelta(hours=h)),
        "pm25": t1(pm25),
        "aqi_category": category(pm25),
        "method": method,
        "source": source,
        "nearest_monitor_dist_km": r1(dist),
    }


def monitor_forecasts(m):
    return [fv(h, m["by_h"][h][0], "model", m["by_h"][h][1], 0.0) for h in HORIZONS]


def envelope():
    return {"issued_at": iso(ISSUED), "model_key": MODEL_KEY, "aqi_table_version": AQI_TABLE}


def point_response(qlat, qlon):
    c = cell_at(qlat, qlon)
    forecasts = []
    for h in HORIZONS:
        res = idw(c["lat"], c["lon"], h)
        if res is not None:
            forecasts.append(fv(h, res[0], "interpolated", "idw", res[1]))
    # Physically nearest monitor of any source (fallback included), measured from the query point.
    m = min(monitors, key=lambda m: haversine(qlat, qlon, m["lat"], m["lon"]))
    return {
        **envelope(),
        "query": {"lat": qlat, "lon": qlon, "zip": None, "zip_area_km2": None},
        "cell": {
            "forecast_point_id": c["id"],
            "centroid": {"lat": round(c["lat"], 5), "lon": round(c["lon"], 5)},
            "has_forecast": bool(forecasts),
            "no_forecast_reason": None if forecasts else "no_monitor_within_50km",
            "nearest_monitor_dist_km": nearest_eligible_km(c["lat"], c["lon"]),
            "forecasts": forecasts,
        },
        "nearest_monitor": {
            "forecast_point_id": m["forecast_point_id"], "aqs_code": m["aqs_code"], "name": m["name"],
            "location": {"lat": round(m["lat"], 5), "lon": round(m["lon"], 5)},
            "distance_km": r1(haversine(qlat, qlon, m["lat"], m["lon"])),
            "forecasts": monitor_forecasts(m),
        },
    }


def main(out):
    out.mkdir(parents=True, exist_ok=True)

    def write(name, obj):
        (out / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    # --- /grid/cells and /forecast/grid?bbox=-122.95,39.40,-121.50,40.10 (Clear Lake NF to Paradise) ---
    bbox = [-122.95, 39.40, -121.50, 40.10]
    cells = cells_in_bbox(bbox)
    write("grid_cells.json", {
        "type": "FeatureCollection", "grid_key": GRID_KEY, "cell_size_m": CELL_M,
        "bbox": bbox, "cell_count": len(cells),
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [c["ring"]]},
            "properties": {"id": c["id"]},
        } for c in cells],
    })

    horizons = []
    for h in HORIZONS:
        rows = []
        for c in cells:
            res = idw(c["lat"], c["lon"], h)
            if res is not None:
                rows.append({"id": c["id"], "pm25": t1(res[0]), "aqi_category": category(res[0]),
                             "nearest_monitor_dist_km": r1(res[1])})
        horizons.append({"horizon_hours": h, "target_time": iso(ISSUED + timedelta(hours=h)), "cells": rows})
    write("forecast_grid.json", {
        **envelope(), "grid_key": GRID_KEY, "method": "interpolated", "source": "idw",
        "bbox": bbox, "horizons": horizons,
    })

    # --- /forecast/monitors ---
    write("forecast_monitors.json", {
        "type": "FeatureCollection", **envelope(),
        "features": [{
            "type": "Feature",
            "geometry": pt(m["lat"], m["lon"]),
            "properties": {
                "forecast_point_id": m["forecast_point_id"], "aqs_code": m["aqs_code"], "name": m["name"],
                "forecasts": monitor_forecasts(m),
            },
        } for m in monitors],
    })

    # --- /forecast/point?lat=&lon= ---
    write("forecast_point.json", point_response(39.7285, -121.8375))            # downtown Chico
    write("forecast_point_no_forecast.json", point_response(39.75, -122.85))    # Mendocino NF, Glenn Co.

    # --- /fires/active (72 h window, VIIRS SNPP only, every confidence level) ---
    rng = random.Random(4)
    passes = [  # time, daynight, n, centre, spread
        (datetime(2024, 7, 25, 9, 36, tzinfo=UTC), "N", 3, (39.80, -121.78), 0.02),
        (datetime(2024, 7, 25, 21, 6, tzinfo=UTC), "D", 4, (39.88, -121.74), 0.06),
        (datetime(2024, 7, 26, 9, 24, tzinfo=UTC), "N", 5, (39.94, -121.72), 0.08),
        (datetime(2024, 7, 26, 21, 18, tzinfo=UTC), "D", 6, (39.98, -121.70), 0.10),
        (datetime(2024, 7, 27, 9, 42, tzinfo=UTC), "N", 12, (40.08, -121.60), 0.15),
    ]
    fires = []
    for t, dn, n, (clat, clon), spread in passes:
        for i in range(n):
            lat = clat + rng.uniform(-spread, spread)
            lon = clon + rng.uniform(-spread * 1.3, spread * 1.3)
            raw = rng.choices(["l", "n", "h"], weights=[2, 7, 2])[0]
            conf = {"l": "low", "n": "nominal", "h": "high"}[raw]
            frp = rng.uniform(1.5, 9) if conf == "low" else rng.uniform(8, 140) if conf == "nominal" else rng.uniform(90, 420)
            fires.append({
                "type": "Feature",
                "geometry": pt(lat, lon),
                "properties": {
                    "detection_id": uuid7(f"fire:VIIRS_SNPP:{t}:{i}", t), "detected_at": iso(t),
                    "satellite": "VIIRS_SNPP", "product": "NRT", "confidence": conf, "confidence_raw": raw,
                    "frp_mw": r1(frp), "daynight": dn,
                },
            })
    write("fires_active.json", {
        "type": "FeatureCollection", "generated_at": iso(NOW), "window_hours": 72,
        "window_start": iso(NOW - timedelta(hours=72)), "window_end": iso(NOW),
        "detection_count": len(fires), "features": fires,
    })

    # --- /observations/pm25/latest (≤ 2 h old; AirNow regulatory + PurpleAir Barkjohn qa ok; outdoor) ---
    valid = datetime(2024, 7, 27, 17, 0, tzinfo=UTC)
    obs = [{
        "type": "Feature", "geometry": pt(m["lat"], m["lon"]),
        "properties": {
            "monitor_id": m["monitor_id"], "provider": "airnow", "station_code": m["aqs_code"], "name": m["name"],
            "valid_at": iso(valid), "pm25": t1(m["by_h"][1][0]), "aqi_category": category(m["by_h"][1][0]),
            "correction": "regulatory",
        },
    } for m in monitors if m["by_h"][1][1] != "fallback"]
    purpleair = [  # sensor_index, name, lat, lon, Barkjohn-corrected pm25
        ("131075", "Chico - Mangrove Ave", 39.7452, -121.8264, 82.6),
        ("98213", "Chico - Chapmantown", 39.7198, -121.8231, 79.1),
        ("176540", "Durham", 39.6463, -121.7997, 71.4),
        ("150992", "Paradise - Skyway", 39.7639, -121.6211, 124.8),
        ("112318", "Oroville - South", 39.4943, -121.5571, 63.9),
    ]
    for idx, name, lat, lon, v in purpleair:
        obs.append({
            "type": "Feature", "geometry": pt(lat, lon),
            "properties": {
                "monitor_id": uuid7("purpleair:" + idx, datetime(2024, 5, 11, tzinfo=UTC)), "provider": "purpleair",
                "station_code": idx, "name": name, "valid_at": iso(valid), "pm25": t1(v), "aqi_category": category(v),
                "correction": "purpleair_barkjohn",
            },
        })
    write("observations_pm25_latest.json", {
        "type": "FeatureCollection", "generated_at": iso(NOW), "max_age_hours": 2,
        "aqi_table_version": AQI_TABLE, "features": obs,
    })

    # --- /meta ---
    def source(name, last_ok, latest, stale_after):
        age = int((NOW - latest).total_seconds() // 60)
        return {"source": name, "last_success_at": iso(last_ok), "latest_data_at": iso(latest),
                "age_minutes": age, "stale_after_minutes": stale_after, "stale": age > stale_after}

    write("meta.json", {
        "generated_at": iso(NOW), "api_version": "v1", "model_key": MODEL_KEY, "model_status": "production",
        "latest_issued_at": iso(ISSUED), "forecast_age_minutes": 40, "forecast_stale_after_minutes": 120,
        "forecast_stale": False, "horizons": list(HORIZONS), "grid_key": GRID_KEY,
        "low_confidence_dist_km": LOW_CONFIDENCE_KM, "max_interpolation_dist_km": MAX_IDW_KM,
        "aqi_category_label": AQI_LABEL, "aqi_table_version": AQI_TABLE,
        "aqi_categories": [{"key": k, "label": lab, "color": c, "pm25_min": lo, "pm25_max": hi} for k, lab, c, lo, hi in AQI],
        "sources": [
            source("airnow", datetime(2024, 7, 27, 18, 25, tzinfo=UTC), valid, 120),
            source("purpleair", datetime(2024, 7, 27, 18, 30, tzinfo=UTC), valid, 120),
            source("firms", datetime(2024, 7, 27, 18, 15, tzinfo=UTC), datetime(2024, 7, 27, 9, 42, tzinfo=UTC), 720),
            source("nws_obs", datetime(2024, 7, 27, 18, 20, tzinfo=UTC), datetime(2024, 7, 27, 15, 53, tzinfo=UTC), 120),
        ],
    })

    write("health.json", {"status": "ok", "environment": "development"})
    write("error_out_of_scope.json", {
        "code": "out_of_scope",
        "message": "Point (45.52, -122.68) is outside California; SmokeSense only forecasts for California.",
    })
    write("error_invalid_query.json", {
        "code": "invalid_query",
        "message": "Pass either lat and lon, or zip, not both.",
    })
    print("grid cells:", len(cells), "fires:", len(fires), "obs:", len(obs))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT)

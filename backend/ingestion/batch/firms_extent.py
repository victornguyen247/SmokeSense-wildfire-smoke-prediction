"""How far each source's ingestion reaches beyond a pilot event's tight bbox and window.

Features at a forecast point look back in time (fire lookback, PM2.5 lags,
the latest weather report) and labels look ahead (forecast horizons), so the
first and last hours of an event need data from outside its window, and
points near the bbox edge need fires and stations from outside the box.
PurpleAir keeps the tight bbox and window.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

# 200 km: the FRP-share analysis radius and the live-inference fire radius
# (features/spatial.py aggregate_fire_features_200km, radius_km=200).
FIRMS_MARGIN_KM = 200.0

# 72 h: matches the features lookback_hours default of 72 (PR #31).
FIRMS_LEAD_HOURS = 72

# 24 h: max(24, the largest PM2.5 lag, pm25_lag_24h in features/temporal.py).
AIRNOW_LEAD_HOURS = 24

# 24 h: the longest forecast horizon, max(ALLOWED_HORIZONS) in features/alignment.py.
AIRNOW_TAIL_HOURS = 24

# 50 km: the nearest NCEI station to a point near the bbox edge can lie outside it,
# as it can in live inference.
NCEI_MARGIN_KM = 50.0

# 24 h: the weather join takes the latest report before issue_time.
NCEI_LEAD_HOURS = 24

KM_PER_DEG_LAT = 111.32


def _floor2(x: float) -> float:
    # round() first so 39.26 * 100 = 3925.9999... is not floored to 39.25
    return math.floor(round(x * 100, 6)) / 100


def _ceil2(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def expand_bbox_km(bbox: str, margin_km: float = FIRMS_MARGIN_KM) -> str:
    """Grow a "west,south,east,north" bbox by margin_km on every side.

    Longitude degrees are sized at the bbox's poleward edge, where a degree
    is shortest, so the margin is at least margin_km everywhere along the
    box. Edges are rounded outward to 2 dp; latitude is clamped to [-90, 90].
    """
    west, south, east, north = (float(v) for v in bbox.split(","))
    dlat = margin_km / KM_PER_DEG_LAT
    poleward = max(abs(south), abs(north))
    km_per_deg_lon = KM_PER_DEG_LAT * math.cos(math.radians(poleward))
    dlon = margin_km / km_per_deg_lon if km_per_deg_lon > 0 else 360.0

    out = (
        _floor2(west - dlon),
        max(-90.0, _floor2(south - dlat)),
        _ceil2(east + dlon),
        min(90.0, _ceil2(north + dlat)),
    )
    return ",".join(f"{v:.2f}" for v in out)


def tail_end_date(end_date: str, tail_hours: int) -> str:
    """end_date ("YYYY-MM-DD") moved forward by tail_hours, rounded up to whole days."""
    end = date.fromisoformat(end_date) + timedelta(days=math.ceil(tail_hours / 24))
    return end.isoformat()


def lead_start_date(start_date: str, lead_hours: int = FIRMS_LEAD_HOURS) -> str:
    """start_date ("YYYY-MM-DD") moved back by lead_hours, rounded up to whole days."""
    start = date.fromisoformat(start_date) - timedelta(days=math.ceil(lead_hours / 24))
    return start.isoformat()

"""How far FIRMS ingestion reaches beyond a pilot event's tight bbox and window.

Fire features look for detections up to 200 km from a point and some hours
back, so a forecast point near the bbox edge on the event's first day needs
fires from outside the bbox and from before the window. AirNow, NCEI and
PurpleAir keep the tight bbox and window.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

# 200 km: the FRP-share analysis radius and the live-inference fire radius
# (features/spatial.py aggregate_fire_features_200km, radius_km=200).
FIRMS_MARGIN_KM = 200.0

# 72 h: matches the features lookback_hours default of 72 (PR #31).
FIRMS_LEAD_HOURS = 72

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


def lead_start_date(start_date: str, lead_hours: int = FIRMS_LEAD_HOURS) -> str:
    """start_date ("YYYY-MM-DD") moved back by lead_hours, rounded up to whole days."""
    start = date.fromisoformat(start_date) - timedelta(days=math.ceil(lead_hours / 24))
    return start.isoformat()

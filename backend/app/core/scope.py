"""California scope for forecast points (docs/data-decisions.md #17).

DATA-04 forecast points are AirNow monitors located in California: AQS state
code 06, or a tribal ("TT") site listed in CA_TRIBAL_SITES after its location
has been checked. Tribal AQS codes carry no state, so each one is added by hand.
"""

from __future__ import annotations

from app.schemas.query import Bbox

CALIFORNIA_STATE_CODE = "06"

# Rough California extent (minLon, minLat, maxLon, maxLat), the same box the frontend
# mock uses. API-01's mock mode checks scope against it; the database repository will
# check against the state polygon in PostGIS instead.
CALIFORNIA_BBOX = Bbox(-124.5, 32.5, -114.1, 42.1)

# The 3-digit prefixes of California ZIP codes.
CALIFORNIA_ZIP_PREFIXES = range(900, 962)

# Tribal (TT) AirNow sites confirmed to be in California, by 9-character AQS code.
CA_TRIBAL_SITES: dict[str, str] = {
    # Morongo Band of Mission Indians, Banning, Riverside County (33.9446, -116.8303).
    "TT5821016": "Morongo School",
}


def in_california_scope(aqs: str | None) -> bool:
    """Whether an AirNow site may be a forecast point.

    aqs is the 9-character AQS code, with or without dashes ("060072003",
    "06-007-2003", "TT-582-1016").
    """
    if not aqs:
        return False
    code = aqs.replace("-", "").strip()
    return code.startswith(CALIFORNIA_STATE_CODE) or code in CA_TRIBAL_SITES


def clip_to_california(bbox: Bbox) -> Bbox | None:
    """The part of bbox inside CALIFORNIA_BBOX, or None when they don't overlap."""
    ca = CALIFORNIA_BBOX
    clipped = Bbox(
        max(bbox.min_lon, ca.min_lon),
        max(bbox.min_lat, ca.min_lat),
        min(bbox.max_lon, ca.max_lon),
        min(bbox.max_lat, ca.max_lat),
    )
    if clipped.min_lon > clipped.max_lon or clipped.min_lat > clipped.max_lat:
        return None
    return clipped


def point_in_california(lat: float, lon: float) -> bool:
    ca = CALIFORNIA_BBOX
    return ca.min_lon <= lon <= ca.max_lon and ca.min_lat <= lat <= ca.max_lat


def is_california_zip(zip_code: str) -> bool:
    """zip_code is a validated 5-digit ZIP."""
    return int(zip_code[:3]) in CALIFORNIA_ZIP_PREFIXES

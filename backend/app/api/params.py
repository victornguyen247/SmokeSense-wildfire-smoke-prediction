"""Query parameters shared by several routes, parsed and validated into app.schemas.query.

Shape errors are 400 here (invalid_bbox, invalid_query). Scope (is it in California?)
is a business rule and is checked in app/services/scope_service.py.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Query

from app.core.errors import ApiError
from app.schemas.query import Bbox, PointQuery

# Same pattern as BboxParam in docs/api/openapi.yaml.
BBOX_PATTERN = re.compile(r"^-?[0-9]+(\.[0-9]+)?(,-?[0-9]+(\.[0-9]+)?){3}$")


def bbox_param(
    bbox: Annotated[
        str | None,
        Query(description="`minLon,minLat,maxLon,maxLat` (WGS84). Clipped to California; defaults to all of it."),
    ] = None,
) -> Bbox | None:
    if bbox is None:
        return None
    if not BBOX_PATTERN.match(bbox):
        raise ApiError(400, "invalid_bbox", "bbox must be minLon,minLat,maxLon,maxLat, e.g. -122.95,39.40,-121.50,40.10.")
    parsed = Bbox(*(float(v) for v in bbox.split(",")))
    if not (-180 <= parsed.min_lon <= 180 and -180 <= parsed.max_lon <= 180):
        raise ApiError(400, "invalid_bbox", "bbox longitudes must be between -180 and 180.")
    if not (-90 <= parsed.min_lat <= 90 and -90 <= parsed.max_lat <= 90):
        raise ApiError(400, "invalid_bbox", "bbox latitudes must be between -90 and 90.")
    if parsed.min_lon > parsed.max_lon or parsed.min_lat > parsed.max_lat:
        raise ApiError(400, "invalid_bbox", "bbox minimums must not be greater than its maximums.")
    return parsed


def point_param(
    lat: Annotated[float | None, Query(ge=-90, le=90, description="Latitude. Required with `lon`.")] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180, description="Longitude. Required with `lat`.")] = None,
    zip: Annotated[str | None, Query(pattern=r"^[0-9]{5}$", description="5-digit ZIP code.")] = None,
) -> PointQuery:
    if zip is not None:
        if lat is not None or lon is not None:
            raise ApiError(400, "invalid_query", "Pass either lat and lon, or zip, not both.")
        return PointQuery(zip=zip)
    if lat is None or lon is None:
        raise ApiError(400, "invalid_query", "Pass lat and lon together, or zip.")
    return PointQuery(lat=lat, lon=lon)

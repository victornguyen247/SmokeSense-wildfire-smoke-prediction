"""Parsed request parameters, passed from the routes to services and repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Bbox(NamedTuple):
    """WGS84 bounding box in GeoJSON order: minLon, minLat, maxLon, maxLat."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def __str__(self) -> str:
        return ",".join(f"{v:g}" for v in self)


@dataclass(frozen=True)
class PointQuery:
    """A /forecast/point location: either lat + lon, or a ZIP (never both)."""

    lat: float | None = None
    lon: float | None = None
    zip: str | None = None

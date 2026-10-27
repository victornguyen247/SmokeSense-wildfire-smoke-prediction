"""Mock-mode repository: answers every query with the PM-02 fixtures in docs/api/fixtures.

The fixtures show one area at one moment (Park Fire, 2024-07-27 18:00Z), so the bbox is
ignored and the fixture's own area is returned. Parameters are still validated and
scope-checked by the services before they get here, as they will be for real data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.repositories.base import Body
from app.schemas.query import Bbox, PointQuery

# A lat/lon this close (degrees) to the no-forecast fixture's query point gets that
# fixture, so the "no monitor within 50 km" case can be requested. Same rule as the
# frontend mock.
NO_FORECAST_RADIUS_DEG = 0.15


class FixtureRepository:
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def _load(self, name: str) -> Body:
        # Parsed per call, so a caller changing the body can't change the next response.
        return json.loads(_read(self.fixture_dir / name))

    def grid_cells(self, bbox: Bbox) -> Body:
        return self._load("grid_cells.json")

    def forecast_grid(self, bbox: Bbox) -> Body:
        return self._load("forecast_grid.json")

    def forecast_point(self, point: PointQuery) -> Body:
        if point.lat is not None and point.lon is not None:
            no_forecast = self._load("forecast_point_no_forecast.json")
            query = no_forecast["query"]
            if (
                abs(point.lat - query["lat"]) < NO_FORECAST_RADIUS_DEG
                and abs(point.lon - query["lon"]) < NO_FORECAST_RADIUS_DEG
            ):
                return no_forecast
        return self._load("forecast_point.json")

    def forecast_monitors(self, bbox: Bbox) -> Body:
        return self._load("forecast_monitors.json")

    def active_fires(self, bbox: Bbox) -> Body:
        return self._load("fires_active.json")

    def latest_pm25(self, bbox: Bbox) -> Body:
        return self._load("observations_pm25_latest.json")

    def meta(self) -> Body:
        return self._load("meta.json")


@lru_cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

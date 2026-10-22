"""The data-access interface the services call.

Each method returns a response body that already has the endpoint's shape in
docs/api/openapi.yaml. FixtureRepository serves the PM-02 fixtures (MOCK_MODE); the
database repository will implement the same methods, so real data swaps in here
without touching the routes or services.

Callers pass a bbox already validated and clipped to California, and a point already
checked to be in scope.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.schemas.query import Bbox, PointQuery

Body = dict[str, Any]


class Repository(Protocol):
    def grid_cells(self, bbox: Bbox) -> Body: ...

    def forecast_grid(self, bbox: Bbox) -> Body: ...

    def forecast_point(self, point: PointQuery) -> Body: ...

    def forecast_monitors(self, bbox: Bbox) -> Body: ...

    def active_fires(self, bbox: Bbox) -> Body: ...

    def latest_pm25(self, bbox: Bbox) -> Body: ...

    def meta(self) -> Body: ...

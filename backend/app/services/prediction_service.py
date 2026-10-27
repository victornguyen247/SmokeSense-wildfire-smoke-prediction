"""Forecasts and the grid they are drawn on (/grid/cells and /forecast/*)."""

from __future__ import annotations

from app.repositories.base import Body, Repository
from app.schemas.query import Bbox, PointQuery
from app.services.scope_service import check_point, resolve_bbox


def grid_cells(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.grid_cells(resolve_bbox(bbox))


def forecast_grid(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.forecast_grid(resolve_bbox(bbox))


def forecast_point(repo: Repository, point: PointQuery) -> Body:
    check_point(point)
    return repo.forecast_point(point)


def forecast_monitors(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.forecast_monitors(resolve_bbox(bbox))

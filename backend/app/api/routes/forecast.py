"""/grid/cells and /forecast/*: the forecast grid, and forecasts at cells, points and monitors."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import get_repository
from app.api.params import bbox_param, point_param
from app.repositories.base import Body, Repository
from app.schemas.query import Bbox, PointQuery
from app.services import prediction_service

router = APIRouter(tags=["forecast"])

Repo = Annotated[Repository, Depends(get_repository)]
BboxParam = Annotated[Bbox | None, Depends(bbox_param)]

# The grid only changes when GEO-02 is regenerated (a new grid_key), so clients cache it
# and refetch when /meta grid_key changes. No ETag: grid_key already says when it changed.
GRID_CELLS_CACHE_CONTROL = "public, max-age=86400"


@router.get("/grid/cells")
def get_grid_cells(response: Response, repo: Repo, bbox: BboxParam) -> Body:
    body = prediction_service.grid_cells(repo, bbox)
    response.headers["Cache-Control"] = GRID_CELLS_CACHE_CONTROL
    return body


@router.get("/forecast/grid")
def get_forecast_grid(repo: Repo, bbox: BboxParam) -> Body:
    return prediction_service.forecast_grid(repo, bbox)


@router.get("/forecast/point")
def get_forecast_point(repo: Repo, point: Annotated[PointQuery, Depends(point_param)]) -> Body:
    return prediction_service.forecast_point(repo, point)


@router.get("/forecast/monitors")
def get_forecast_monitors(repo: Repo, bbox: BboxParam) -> Body:
    return prediction_service.forecast_monitors(repo, bbox)

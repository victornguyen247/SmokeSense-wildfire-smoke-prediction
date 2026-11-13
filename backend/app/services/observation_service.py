"""What has been observed: satellite fire detections, sensor PM2.5 and station wind."""

from __future__ import annotations

from app.repositories.base import Body, Repository
from app.schemas.query import Bbox
from app.services.scope_service import resolve_bbox


def active_fires(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.active_fires(resolve_bbox(bbox))


def latest_pm25(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.latest_pm25(resolve_bbox(bbox))


def latest_wind(repo: Repository, bbox: Bbox | None) -> Body:
    return repo.latest_wind(resolve_bbox(bbox))

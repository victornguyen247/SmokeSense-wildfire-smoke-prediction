"""/observations/pm25/latest: the latest PM2.5 reading per outdoor sensor."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_repository
from app.api.params import bbox_param
from app.repositories.base import Body, Repository
from app.schemas.query import Bbox
from app.services import observation_service

router = APIRouter(tags=["observations"])


@router.get("/observations/pm25/latest")
def get_latest_pm25(
    repo: Annotated[Repository, Depends(get_repository)],
    bbox: Annotated[Bbox | None, Depends(bbox_param)],
) -> Body:
    return observation_service.latest_pm25(repo, bbox)

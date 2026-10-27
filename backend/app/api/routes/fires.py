"""/fires/active: VIIRS SNPP fire detections from the last 72 hours."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_repository
from app.api.params import bbox_param
from app.repositories.base import Body, Repository
from app.schemas.query import Bbox
from app.services import observation_service

router = APIRouter(tags=["fires"])


@router.get("/fires/active")
def get_active_fires(
    repo: Annotated[Repository, Depends(get_repository)],
    bbox: Annotated[Bbox | None, Depends(bbox_param)],
) -> Body:
    return observation_service.active_fires(repo, bbox)

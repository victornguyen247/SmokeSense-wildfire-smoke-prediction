"""/meta (model, freshness, thresholds, AQI legend) and /health under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_repository
from app.repositories.base import Body, Repository
from app.services import meta_service

router = APIRouter(tags=["meta"])


@router.get("/meta")
def get_meta(repo: Annotated[Repository, Depends(get_repository)]) -> Body:
    return meta_service.meta(repo)


@router.get("/health")
def get_health() -> dict[str, str]:
    return meta_service.health()

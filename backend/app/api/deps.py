"""FastAPI dependencies shared by the routes."""

from __future__ import annotations

from app.core.config import settings
from app.core.database import SessionLocal
from app.repositories.base import Repository
from app.repositories.cache import CycleCache
from app.repositories.database import DatabaseRepository
from app.repositories.fixtures import FixtureRepository

_forecast_cache = CycleCache()


def get_repository() -> Repository:
    """The data source for this request: the fixtures in mock mode, otherwise the database."""
    if settings.mock_mode:
        return FixtureRepository(settings.api_contract_dir / "fixtures")
    return DatabaseRepository(SessionLocal, _forecast_cache)

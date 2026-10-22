"""FastAPI dependencies shared by the routes."""

from __future__ import annotations

from app.core.config import settings
from app.repositories.base import Repository
from app.repositories.fixtures import FixtureRepository


def get_repository() -> Repository:
    """The data source for this request: the fixtures in mock mode.

    The database repository plugs in here when it exists. Until then MOCK_MODE=false
    has no data source, so data routes fail with a logged internal_error.
    """
    if not settings.mock_mode:
        raise RuntimeError("MOCK_MODE=false needs the database repository, which isn't built yet.")
    return FixtureRepository(settings.api_contract_dir / "fixtures")

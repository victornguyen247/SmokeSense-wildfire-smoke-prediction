"""Service metadata (/meta) and the liveness probe (/health)."""

from __future__ import annotations

from app.core.config import settings
from app.repositories.base import Body, Repository


def meta(repo: Repository) -> Body:
    body = repo.meta()
    # From the setting, not the repository, so a real repository can't report demo data as live.
    body["mock_mode"] = settings.mock_mode
    return body


def health() -> dict[str, str]:
    """Liveness only: no repository call, so it answers even when data access is down."""
    return {"status": "ok", "environment": settings.environment}

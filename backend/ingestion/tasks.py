"""Celery app and scheduled ingestion tasks.

Keep task bodies thin: pull data via connectors, normalize, persist.
Beat schedules live here until we need a separate beat service.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "smokesense",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Alias expected by `celery -A ingestion.tasks` (looks for `app` or `celery`).
app = celery_app

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(name="ingestion.health")
def health() -> dict[str, str]:
    """Smoke-test task so the worker process is verifiable before real jobs land."""
    return {"status": "ok"}

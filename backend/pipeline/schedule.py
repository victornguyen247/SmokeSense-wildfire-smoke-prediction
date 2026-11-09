"""Beat entry for the hourly pipeline."""

from __future__ import annotations

from celery.schedules import crontab

from pipeline import settings


def beat_schedule() -> dict:
    return {
        "pipeline-hourly": {
            "task": "pipeline.hourly",
            "schedule": crontab(minute=settings.run_minute()),
            # A run still queued when the next one is due is dropped, not stacked up.
            "options": {"expires": 3600},
        },
    }

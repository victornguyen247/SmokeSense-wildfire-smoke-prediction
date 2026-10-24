"""Celery beat entries for the live jobs; cadences come from the environment.

Each source is its own entry with no chain or link between them, so one source's
failure or slowness never delays another. expires drops a queued run once the next
one is due, so a stalled worker does not pile up a backlog of the same job.
"""

from __future__ import annotations

from datetime import timedelta

from ingestion.live.common import env_int


def beat_schedule() -> dict:
    firms_minutes = env_int("LIVE_FIRMS_EVERY_MINUTES", 30)
    return {
        "live-firms": {
            "task": "ingestion.live.firms",
            "schedule": timedelta(minutes=firms_minutes),
            "options": {"expires": firms_minutes * 60},
        },
    }

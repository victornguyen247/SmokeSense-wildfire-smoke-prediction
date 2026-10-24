"""Celery beat entries for the live jobs; cadences come from the environment.

Each source is its own entry with no chain or link between them, so one source's
failure or slowness never delays another. expires drops a queued run once the next
one is due, so a stalled worker does not pile up a backlog of the same job.
"""

from __future__ import annotations

from datetime import timedelta

from celery.schedules import crontab

from ingestion.live.common import env_int


def beat_schedule() -> dict:
    firms_minutes = env_int("LIVE_FIRMS_EVERY_MINUTES", 30)
    return {
        # Hourly, offset after the top of the hour so AirNow has published the hour
        # that just ended (lag-1 for an issue time H is the reading labelled H - 1 h).
        "live-airnow": {
            "task": "ingestion.live.airnow",
            "schedule": crontab(minute=env_int("LIVE_AIRNOW_MINUTE", 25)),
            "options": {"expires": 3600},
        },
        # Hourly, a few minutes after the :53 routine METARs most stations send.
        "live-nws": {
            "task": "ingestion.live.nws",
            "schedule": crontab(minute=env_int("LIVE_NWS_MINUTE", 5)),
            "options": {"expires": 3600},
        },
        "live-firms": {
            "task": "ingestion.live.firms",
            "schedule": timedelta(minutes=firms_minutes),
            "options": {"expires": firms_minutes * 60},
        },
    }

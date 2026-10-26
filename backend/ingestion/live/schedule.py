"""Celery beat entries for the live jobs; cadences come from the environment.

Each source is its own entry with no chain or link between them, so one source's
failure or slowness never delays another. expires drops a queued run once the next
one is due, so a stalled worker does not pile up a backlog of the same job.
"""

from __future__ import annotations

from datetime import timedelta

from celery.schedules import crontab

from ingestion.live.common import env_int, purpleair_every_minutes


def beat_schedule() -> dict:
    firms_minutes = env_int("LIVE_FIRMS_EVERY_MINUTES", 30)
    purpleair_minutes = purpleair_every_minutes()
    schedule = {
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
        # Daily; dry run unless LIVE_RETENTION_DELETE=1.
        "live-retention": {
            "task": "ingestion.live.retention",
            "schedule": crontab(
                hour=env_int("LIVE_RETENTION_HOUR", 9),
                minute=env_int("LIVE_RETENTION_MINUTE", 15),
            ),
            "options": {"expires": 3600},
        },
    }
    # Map layer only, off by default (decision #44). Each run is one statewide request
    # billed in PurpleAir points (~42.6k on 2026-10-23), so cost scales with cadence.
    if purpleair_minutes > 0:
        schedule["live-purpleair"] = {
            "task": "ingestion.live.purpleair",
            "schedule": timedelta(minutes=purpleair_minutes),
            "options": {"expires": purpleair_minutes * 60},
        }
    return schedule

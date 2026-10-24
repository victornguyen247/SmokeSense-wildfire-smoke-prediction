"""Per-source data freshness for /api/v1/meta, from ingestion_runs (no extra table).

source_freshness() returns the `sources` array of the Meta schema in
docs/api/openapi.yaml, item by item in the SourceFreshness shape, JSON-ready
(timestamps are ISO-8601 UTC with "Z"). API-01's meta service can call it as is.

- last_success_at: finished_at of the newest run that succeeded (a "partial" run,
  e.g. NWS with one station down, counts: it wrote data).
- latest_data_at: newest ingestion_runs.watermark among those runs.
- age_minutes: generated time minus latest_data_at.
- stale: no successful run yet, or the last one finished more than
  stale_after_minutes ago. It is based on the job, not the data age, because a
  healthy FIRMS feed can go hours without a detection.

stale_after_minutes per source: FRESHNESS_STALE_AFTER_MINUTES_<SOURCE> (AIRNOW,
PURPLEAIR, FIRMS, NWS_OBS), defaulting to about two missed runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IngestionRun
from ingestion.live.common import env_int, utc_now

# /meta source name -> ingestion_runs.source, in the contract's enum order.
SOURCES = {
    "airnow": "airdata",
    "purpleair": "purpleair",
    "firms": "firms",
    "nws_obs": "nws_obs",
}

DEFAULT_STALE_AFTER_MINUTES = {
    "airnow": 150,  # hourly at :25
    "purpleair": 90,  # every 30 min
    "firms": 90,  # every 30 min
    "nws_obs": 150,  # hourly at :05
}


def stale_after_minutes() -> dict[str, int]:
    return {
        name: env_int(f"FRESHNESS_STALE_AFTER_MINUTES_{name.upper()}", default)
        for name, default in DEFAULT_STALE_AFTER_MINUTES.items()
    }


def _iso_z(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def freshness_from_runs(
    latest: dict[str, tuple[datetime | None, datetime | None]],
    now: datetime,
    thresholds: dict[str, int],
) -> list[dict]:
    """latest: {ingestion_runs.source: (last finished_at, newest watermark)} of successes."""
    items = []
    for name, run_source in SOURCES.items():
        last_success, latest_data = latest.get(run_source, (None, None))
        age = None
        if latest_data is not None:
            age = max(0, int((now - latest_data).total_seconds() // 60))
        limit = thresholds[name]
        stale = (
            last_success is None or (now - last_success).total_seconds() > limit * 60
        )
        items.append(
            {
                "source": name,
                "last_success_at": _iso_z(last_success),
                "latest_data_at": _iso_z(latest_data),
                "age_minutes": age,
                "stale_after_minutes": limit,
                "stale": stale,
            }
        )
    return items


def source_freshness(session: Session, now: datetime | None = None) -> list[dict]:
    """The /meta `sources` array, computed from ingestion_runs."""
    rows = session.execute(
        select(
            IngestionRun.source,
            func.max(IngestionRun.finished_at),
            func.max(IngestionRun.watermark),
        )
        .where(
            IngestionRun.source.in_(SOURCES.values()),
            IngestionRun.status.in_(("success", "partial")),
        )
        .group_by(IngestionRun.source)
    ).all()
    latest = {source: (finished, watermark) for source, finished, watermark in rows}
    return freshness_from_runs(latest, now or utc_now(), stale_after_minutes())

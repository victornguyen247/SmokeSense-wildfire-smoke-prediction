"""Per-source data freshness for /api/v1/meta, from ingestion_runs (no extra table).

source_freshness() returns the `sources` array of the Meta schema in
docs/api/openapi.yaml, item by item in the SourceFreshness shape, JSON-ready
(timestamps are ISO-8601 UTC with "Z").

- last_success_at: finished_at of the newest run that succeeded (a "partial" run,
  e.g. NWS with one station down, counts: it wrote data).
- latest_data_at: newest ingestion_runs.watermark among those runs.
- age_minutes: generated time minus latest_data_at.
- stale: no successful run yet, or the last one finished more than
  stale_after_minutes ago (decision #40). FIRMS is also stale when it has no
  detection, or its newest is older than FRESHNESS_MAX_DATA_AGE_MINUTES_FIRMS
  (72 h, the /fires/active window; decision #47): the job can keep succeeding while
  the satellite feed has stopped. A healthy feed can go hours without a detection,
  so only FIRMS gets this check, and only at the window length.

stale_after_minutes per source: FRESHNESS_STALE_AFTER_MINUTES_<SOURCE> (AIRNOW,
FIRMS, NWS_OBS) in app/core/config.py, defaulting to about two missed runs.

PurpleAir has no live job (decision #41), so it is not reported: Meta.sources sets no
minimum and requires no particular source, and a source that never runs would always
show as stale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import IngestionRun

# /meta source name -> ingestion_runs.source, in the contract's enum order.
SOURCES = {
    "airnow": "airdata",
    "firms": "firms",
    "nws_obs": "nws_obs",
}


def stale_after_minutes() -> dict[str, int]:
    """{source: minutes} for every live source."""
    return {
        "airnow": settings.freshness_stale_after_minutes_airnow,
        "firms": settings.freshness_stale_after_minutes_firms,
        "nws_obs": settings.freshness_stale_after_minutes_nws_obs,
    }


def max_data_age_minutes() -> dict[str, int]:
    """{source: minutes} for the sources also judged by data age (decision #47)."""
    return {"firms": settings.freshness_max_data_age_minutes_firms}


def _iso_z(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def freshness_from_runs(
    latest: dict[str, tuple[datetime | None, datetime | None]],
    now: datetime,
    thresholds: dict[str, int],
    max_data_age: dict[str, int] | None = None,
) -> list[dict]:
    """latest: {ingestion_runs.source: (last finished_at, newest watermark)} of successes.
    max_data_age: {source: minutes}; a listed source is also stale past that data age."""
    max_data_age = max_data_age or {}
    items = []
    for name, run_source in SOURCES.items():
        last_success, latest_data = latest.get(run_source, (None, None))
        age = None
        if latest_data is not None:
            age = max(0, int((now - latest_data).total_seconds() // 60))
        limit = thresholds[name]
        data_limit = max_data_age.get(name)
        stale = (
            last_success is None
            or (now - last_success).total_seconds() > limit * 60
            or (data_limit is not None and (age is None or age > data_limit))
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
    return freshness_from_runs(
        latest,
        now or datetime.now(timezone.utc),
        stale_after_minutes(),
        max_data_age_minutes(),
    )

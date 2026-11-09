"""Forecast freshness for /api/v1/meta, from pipeline_runs.

forecast_status() returns the Meta fields model_key, latest_issued_at,
forecast_age_minutes, forecast_stale_after_minutes and forecast_stale (docs/api/openapi.yaml),
JSON-ready (timestamps ISO-8601 UTC with "Z"). API-01's meta service can merge it as is.

It looks only at the newest *successful* run. A failed or running run never changes it,
and failed runs delete nothing, so the last good forecast stays served; once it is older
than PIPELINE_STALE_AFTER_MINUTES (default 150, about two missed hours) it is marked stale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineRun
from ingestion.live.common import utc_now
from pipeline import settings


def forecast_status(session: Session, now: datetime | None = None) -> dict:
    now = now or utc_now()
    threshold = settings.stale_after_minutes()
    last = session.execute(
        select(PipelineRun.issued_at, PipelineRun.model_key)
        .where(PipelineRun.status == "success")
        .order_by(PipelineRun.issued_at.desc())
        .limit(1)
    ).first()
    if last is None:
        return {"model_key": None, "latest_issued_at": None, "forecast_age_minutes": None,
                "forecast_stale_after_minutes": threshold, "forecast_stale": True}
    issued_at, model_key = last
    age = max(0, int((now - issued_at).total_seconds() // 60))
    return {
        "model_key": model_key,
        "latest_issued_at": issued_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast_age_minutes": age,
        "forecast_stale_after_minutes": threshold,
        "forecast_stale": age > threshold,
    }

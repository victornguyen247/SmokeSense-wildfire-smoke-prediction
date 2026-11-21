"""PM-06 episode rules. The caller commits episodes and notification outbox together."""

import logging
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.models.operations import PipelineRun
from app.models.predictions import Alert, Forecast, ModelVersion
from app.models.reference import ForecastPoint
from app.models.values import HORIZON_HOURS
from shared.aqi import AQI_TABLE_VERSION

logger = logging.getLogger(__name__)
SEVERITY = "unhealthy_sensitive"


@dataclass(frozen=True)
class AlertChange:
    """An episode opened by this call, ready for the notification dispatcher."""

    alert_id: str
    forecast_point_id: str


def _utc(value: datetime) -> datetime:
    # SQLite fixtures return naive timestamps; PostgreSQL returns aware values.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate(session: Session, issued_at: datetime) -> list[AlertChange]:
    """Evaluate a successful cycle in chronological order, flushing without commit.

    Evaluate active grid cells and cells with open episodes, without subscription
    queries. SQL reads are batched per cycle; ordered point locks serialize jobs.
    The returned list contains only new episodes; OPS-06 handles email delivery.
    """
    if issued_at.tzinfo is None or issued_at.utcoffset() != timedelta(0):
        raise ValueError("issued_at must be timezone-aware UTC")
    if issued_at.minute or issued_at.second or issued_at.microsecond:
        raise ValueError("issued_at must be the top of a UTC hour")

    cycle = session.execute(
        select(PipelineRun.model_key, ModelVersion.thresholds)
        .join(ModelVersion, ModelVersion.model_key == PipelineRun.model_key)
        .where(
            PipelineRun.issued_at == issued_at,
            PipelineRun.status == "success",
            ModelVersion.status == "production",
        )
        .order_by(PipelineRun.finished_at.desc(), PipelineRun.id.desc())
        .limit(1)
    ).first()
    if cycle is None:
        return []
    thresholds = {
        h: value
        for h in HORIZON_HOURS
        if isinstance(value := (cycle.thresholds or {}).get(str(h)), (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value >= 0
    }
    if not thresholds:
        logger.warning("Alert evaluation skipped: cycle model has no usable thresholds")
        return []

    open_points = select(Alert.forecast_point_id).where(
        Alert.status == "open", Alert.severity == SEVERITY
    )
    points = session.scalars(
        select(ForecastPoint.id)
        .where(
            ForecastPoint.kind == "grid_cell",
            or_(ForecastPoint.active.is_(True), ForecastPoint.id.in_(open_points)),
        )
        .order_by(ForecastPoint.id)
        .with_for_update()
    ).all()
    episodes = {
        alert.forecast_point_id: alert
        for alert in session.scalars(
            select(Alert)
            .where(
                Alert.status == "open",
                Alert.severity == SEVERITY,
                Alert.forecast_point_id.in_(points),
            )
            .execution_options(populate_existing=True)
        )
    }
    grouped = defaultdict(list)
    for forecast in session.scalars(
        select(Forecast)
        .where(
            Forecast.forecast_point_id.in_(points),
            Forecast.issued_at == issued_at,
            Forecast.model_key == cycle.model_key,
            Forecast.source == "idw",
            Forecast.is_shadow.is_(False),
        )
        .order_by(Forecast.horizon_hours)
    ):
        grouped[forecast.forecast_point_id].append(forecast)

    # One history query replaces a COUNT query for each cell. Exclude future
    # cycles so historical evaluation cannot count runs after this cycle.
    first_seen = min(
        (_utc(a.last_seen_at) for a in episodes.values()), default=issued_at
    )
    successes = [
        _utc(value)
        for value in session.scalars(
            select(PipelineRun.issued_at)
            .where(
                PipelineRun.status == "success",
                PipelineRun.issued_at > first_seen,
                PipelineRun.issued_at <= issued_at,
            )
            .order_by(PipelineRun.issued_at)
        )
    ]
    opened = []
    for point_id in points:
        episode = episodes.get(point_id)
        if episode and _utc(episode.last_seen_at) >= issued_at:
            continue
        forecasts = grouped[point_id]
        if not forecasts:
            if episode and issued_at - _utc(episode.last_seen_at) > timedelta(hours=24):
                episode.status = "resolved"
                episode.resolved_at = issued_at
            continue
        if not thresholds.keys() <= {f.horizon_hours for f in forecasts}:
            continue  # Partial forecasts cannot prove all evaluated horizons clear.
        exceeding = [
            f
            for f in forecasts
            if f.horizon_hours in thresholds
            and f.pm25_predicted >= thresholds[f.horizon_hours]
        ]
        if not exceeding:
            if (
                episode
                and len(successes) - bisect_right(successes, _utc(episode.last_seen_at))
                >= 3
            ):
                episode.status = "resolved"
                episode.resolved_at = issued_at
            continue

        trigger = exceeding[0]
        peak = max(forecasts, key=lambda f: f.pm25_predicted)
        if episode is None:
            episode = Alert(
                id=uuid7(),
                forecast_point_id=point_id,
                severity=SEVERITY,
                status="open",
                first_triggered_at=issued_at,
                last_seen_at=issued_at,
                pm25_threshold=thresholds[trigger.horizon_hours],
                horizon_hours=peak.horizon_hours,
                model_key=cycle.model_key,
                aqi_table_version=AQI_TABLE_VERSION,
                peak_pm25_predicted=peak.pm25_predicted,
                peak_target_time=peak.target_time,
                latest_forecast_id=trigger.id,
            )
            session.add(episode)
            opened.append(AlertChange(episode.id, point_id))
        else:
            episode.last_seen_at = issued_at
            episode.latest_forecast_id = trigger.id
            if (
                episode.peak_pm25_predicted is None
                or peak.pm25_predicted > episode.peak_pm25_predicted
            ):
                episode.peak_pm25_predicted = peak.pm25_predicted
                episode.peak_target_time = peak.target_time
                episode.horizon_hours = peak.horizon_hours
    session.flush()
    return opened

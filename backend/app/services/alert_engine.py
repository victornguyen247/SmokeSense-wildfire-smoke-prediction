"""Evaluate a completed hourly run; the caller owns the transaction.

API-04 must supply alert_subscriptions(forecast_point_id, status). This
lightweight SQL reference deliberately does not define or migrate that table.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

from sqlalchemy import column, select, table
from sqlalchemy.orm import Session

from app.models.predictions import Alert, Forecast, ModelVersion
from app.models.reference import ForecastPoint
from app.models.values import HORIZON_HOURS
from shared.aqi import AQI_TABLE_VERSION

subscriptions = table(
    "alert_subscriptions", column("forecast_point_id"), column("status")
)


@dataclass(frozen=True)
class AlertChange:
    """An episode opened by this call, ready for the notification dispatcher."""

    alert_id: str
    forecast_point_id: str


def _utc(value: datetime) -> datetime:
    # SQLite test sessions return naive timestamps; Postgres returns aware UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate(session: Session, issued_at: datetime) -> list[AlertChange]:
    """Open/update episodes, returning only newly opened alerts.

    Runs must be evaluated in order, once per UTC hour, after forecasts finish
    writing and before grid retention. Three hours since the last exceedance
    represents three clean runs under that pipeline contract. Missing point
    forecasts never count as clean. Commit alerts together with notification
    outbox records; this function flushes but never commits.
    """
    if issued_at.tzinfo is None or issued_at.utcoffset() != timedelta(0):
        raise ValueError("issued_at must be timezone-aware UTC")
    if issued_at.minute or issued_at.second or issued_at.microsecond:
        raise ValueError("issued_at must be the top of a UTC hour")

    active_points = select(subscriptions.c.forecast_point_id).where(
        subscriptions.c.status == "active"
    )
    # Serialize evaluations even when the point has no alert row yet.
    points = session.scalars(
        select(ForecastPoint.id)
        .where(ForecastPoint.id.in_(active_points))
        .order_by(ForecastPoint.id)
        .with_for_update()
    ).all()
    opened = []
    for point_id in points:
        rows = session.execute(
            select(Forecast, ModelVersion)
            .join(ModelVersion, Forecast.model_key == ModelVersion.model_key)
            .where(
                Forecast.forecast_point_id == point_id,
                Forecast.issued_at == issued_at,
                Forecast.is_shadow.is_(False),
                ModelVersion.status == "production",
            )
            .order_by(Forecast.horizon_hours)
        ).all()
        if not rows:
            continue
        if len({model.model_key for _, model in rows}) != 1:
            raise ValueError("Multiple production models forecast the same point")
        thresholds = rows[0][1].thresholds or {}
        for horizon in HORIZON_HOURS:
            cutoff = thresholds.get(str(horizon))
            if (
                isinstance(cutoff, bool)
                or not isinstance(cutoff, (int, float))
                or not isfinite(cutoff)
                or cutoff < 0
            ):
                raise ValueError("Production model needs finite per-horizon thresholds")
        # A partial run cannot prove a point clean or supply the full peak.
        if {forecast.horizon_hours for forecast, _ in rows} != set(HORIZON_HOURS):
            continue
        latest = session.scalars(
            select(Alert)
            .where(
                Alert.forecast_point_id == point_id,
                Alert.severity == "unhealthy_sensitive",
            )
            .order_by(Alert.first_triggered_at.desc())
            .limit(1)
        ).first()
        if (
            latest
            and max(
                _utc(latest.last_seen_at),
                _utc(latest.resolved_at or latest.last_seen_at),
            )
            >= issued_at
        ):
            continue
        episode = latest if latest and latest.status == "open" else None
        exceeding = [
            forecast
            for forecast, _ in rows
            if forecast.pm25_predicted >= thresholds[str(forecast.horizon_hours)]
        ]
        if not exceeding:
            if episode and issued_at - _utc(episode.last_seen_at) >= timedelta(hours=3):
                episode.status = "resolved"
                episode.resolved_at = issued_at
            continue

        trigger = exceeding[0]
        peak = max((forecast for forecast, _ in rows), key=lambda f: f.pm25_predicted)
        if episode is None:
            episode = Alert(
                forecast_point_id=point_id,
                severity="unhealthy_sensitive",
                status="open",
                first_triggered_at=issued_at,
                last_seen_at=issued_at,
                pm25_threshold=thresholds[str(trigger.horizon_hours)],
                horizon_hours=trigger.horizon_hours,
                model_key=trigger.model_key,
                aqi_table_version=AQI_TABLE_VERSION,
                peak_pm25_predicted=peak.pm25_predicted,
                peak_target_time=peak.target_time,
                latest_forecast_id=trigger.id,
            )
            session.add(episode)
            session.flush()
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
    session.flush()
    return opened

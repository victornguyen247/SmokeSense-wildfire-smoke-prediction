"""Models and predictions: model_versions, forecasts, forecast_verifications, alerts."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, false, func, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.models.base import Base, one_of
from app.models.reference import ForecastPoint
from app.models.values import (
    ALERT_STATUSES,
    HORIZON_HOURS,
    LABEL_CORRECTIONS,
    MODEL_STATUSES,
    SEVERITIES,
)


class ModelVersion(Base):
    """One row per trained model; never updated in place."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "version"),
        one_of("status", MODEL_STATUSES),
        # At most one production model per model_name
        Index(
            "one_production",
            "model_name",
            unique=True,
            postgresql_where=text("status = 'production'"),
        ),
    )

    model_key: Mapped[str] = mapped_column(primary_key=True)  # <model_name>/<version>
    model_name: Mapped[str]
    version: Mapped[str]
    algorithm: Mapped[str]
    artifact_uri: Mapped[str]
    artifact_sha256: Mapped[str]
    hyperparameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feature_list: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    training_data_uri: Mapped[str | None]
    training_data_hash: Mapped[str | None]
    backtest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str]
    notes: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    status_changed_at: Mapped[datetime | None]


class Forecast(Base):
    """ML output (µg/m³). Written only by ml/inference. 30-day retention."""

    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("forecast_point_id", "model_key", "issued_at", "horizon_hours"),
        one_of("horizon_hours", HORIZON_HOURS),
        CheckConstraint("pm25_predicted >= 0"),
        CheckConstraint("pm25_lower >= 0"),
        CheckConstraint("pm25_upper >= 0"),
        CheckConstraint("nearest_monitor_dist_km > 0"),
        CheckConstraint("is_experimental"),
        CheckConstraint("target_time = issued_at + make_interval(hours => horizon_hours)"),
        Index("ix_forecasts_target_time", "target_time"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    forecast_point_id: Mapped[str] = mapped_column(ForeignKey("forecast_points.id"))
    model_key: Mapped[str] = mapped_column(ForeignKey("model_versions.model_key"))
    issued_at: Mapped[datetime]
    horizon_hours: Mapped[int]
    target_time: Mapped[datetime]  # must equal issued_at + horizon_hours (DB-enforced)
    pm25_predicted: Mapped[float]
    pm25_lower: Mapped[float | None]
    pm25_upper: Mapped[float | None]
    nearest_monitor_dist_km: Mapped[float | None]
    is_shadow: Mapped[bool] = mapped_column(server_default=false())
    is_experimental: Mapped[bool] = mapped_column(server_default=true())
    feature_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    forecast_point: Mapped["ForecastPoint"] = relationship()
    model: Mapped["ModelVersion"] = relationship()


Index("ix_forecasts_point_issued", Forecast.forecast_point_id, Forecast.issued_at.desc())


class ForecastVerification(Base):
    """Forecast vs observed. Values are copied (no FKs) so rows outlive the forecast trim."""

    __tablename__ = "forecast_verifications"
    __table_args__ = (
        CheckConstraint("pm25_observed >= 0"),
        one_of("label_correction", LABEL_CORRECTIONS),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    forecast_id: Mapped[str | None]  # NULL once the forecast is trimmed
    forecast_point_id: Mapped[str]
    model_key: Mapped[str]
    horizon_hours: Mapped[int]
    issued_at: Mapped[datetime]
    target_time: Mapped[datetime]
    pm25_predicted: Mapped[float]
    pm25_observed: Mapped[float]
    label_correction: Mapped[str]
    label_monitor_dist_km: Mapped[float]  # only verify when ≤ 25 km
    verified_at: Mapped[datetime]


Index(
    "ix_fv_model_horizon",
    ForecastVerification.model_key,
    ForecastVerification.horizon_hours,
    ForecastVerification.target_time.desc(),
)
Index(
    "ix_fv_point_time",
    ForecastVerification.forecast_point_id,
    ForecastVerification.target_time.desc(),
)


class Alert(Base):
    """Exceedance episode: one open row per (point, severity), updated each cycle."""

    __tablename__ = "alerts"
    __table_args__ = (
        one_of("severity", SEVERITIES),
        one_of("status", ALERT_STATUSES),
        CheckConstraint("is_experimental"),
        Index("ix_alerts_latest_forecast", "latest_forecast_id"),
        Index(
            "one_open_alert",
            "forecast_point_id",
            "severity",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    forecast_point_id: Mapped[str] = mapped_column(ForeignKey("forecast_points.id"))
    severity: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="open")
    first_triggered_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
    pm25_threshold: Mapped[float]  # copied at creation
    aqi_table_version: Mapped[str]
    peak_pm25_predicted: Mapped[float | None]
    peak_target_time: Mapped[datetime | None]
    horizon_hours: Mapped[int | None]
    model_key: Mapped[str]  # copied at creation, no FK
    # Becomes NULL when the forecast is trimmed at 30 days; the alert survives.
    latest_forecast_id: Mapped[str | None] = mapped_column(
        ForeignKey("forecasts.id", ondelete="SET NULL")
    )
    is_experimental: Mapped[bool] = mapped_column(server_default=true())

    forecast_point: Mapped["ForecastPoint"] = relationship()
    latest_forecast: Mapped["Forecast | None"] = relationship()


Index("ix_alerts_point_triggered", Alert.forecast_point_id, Alert.first_triggered_at.desc())

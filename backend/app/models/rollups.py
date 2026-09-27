"""Durable rollups — built before observation partitions are dropped, kept forever."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.models.base import Base, one_of
from app.models.reference import City, Monitor
from app.models.values import LABEL_CORRECTIONS, SOURCE_SCOPES


class MonitorDailyPm25(Base):
    """Daily mean PM2.5 per monitor. Complete day = hours_reported >= 18."""

    __tablename__ = "monitor_daily_pm25"
    __table_args__ = (
        one_of("correction", LABEL_CORRECTIONS),  # purpleair_raw is never rolled up
        CheckConstraint("mean_pm25 >= 0"),
        CheckConstraint("max_pm25 >= 0"),
        CheckConstraint("hours_reported BETWEEN 0 AND 24"),
    )

    monitor_id: Mapped[str] = mapped_column(ForeignKey("monitors.id"), primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)  # monitor's local day
    correction: Mapped[str] = mapped_column(primary_key=True)
    mean_pm25: Mapped[float]
    max_pm25: Mapped[float | None]
    hours_reported: Mapped[int]
    computed_at: Mapped[datetime]

    monitor: Mapped["Monitor"] = relationship()


Index("ix_monitor_daily_local_date", MonitorDailyPm25.local_date.desc())
Index(
    "ix_monitor_daily_monitor",
    MonitorDailyPm25.monitor_id,
    MonitorDailyPm25.local_date.desc(),
)


class CityMonthlyAggregate(Base):
    """Monthly PM2.5 stats for City Air Quality History — descriptive, not a forecast."""

    __tablename__ = "city_monthly_aggregates"
    __table_args__ = (
        UniqueConstraint("city_id", "year_month", "source_scope"),
        one_of("source_scope", SOURCE_SCOPES),
        CheckConstraint("avg_pm25 >= 0"),
        CheckConstraint("max_pm25 >= 0"),
        CheckConstraint("p95_pm25 >= 0"),
        CheckConstraint("unhealthy_days >= 0"),
        CheckConstraint("data_coverage_pct BETWEEN 0 AND 100"),
        CheckConstraint("monitor_count > 0"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    city_id: Mapped[str] = mapped_column(ForeignKey("cities.id"))
    year_month: Mapped[date]  # first day of month
    source_scope: Mapped[str]
    avg_pm25: Mapped[float | None]
    max_pm25: Mapped[float | None]
    p95_pm25: Mapped[float | None]
    unhealthy_days: Mapped[int | None]  # daily avg > 35.4 µg/m³ (EPA 2024)
    data_coverage_pct: Mapped[float | None]
    monitor_count: Mapped[int | None]
    aqi_table_version: Mapped[str]  # e.g. epa-2024
    computed_at: Mapped[datetime]

    city: Mapped["City"] = relationship()


Index(
    "ix_city_monthly_city_month",
    CityMonthlyAggregate.city_id,
    CityMonthlyAggregate.year_month.desc(),
)

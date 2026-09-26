"""Live time-series tables.

observations, fire_detections, weather_observations and weather_forecasts are
range-partitioned by day. The parent table is what the ORM maps; daily
partitions are created by create_daily_partitions() (see the migration).
Primary keys and unique indexes include the partition column, as Postgres
requires.
"""

from datetime import datetime

from geoalchemy2 import WKBElement
from sqlalchemy import CheckConstraint, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.models.base import Base, one_of, point
from app.models.reference import ForecastPoint, Monitor
from app.models.values import (
    CONFIDENCE_LEVELS,
    CORRECTIONS,
    DATA_STATUSES,
    DAYNIGHT,
    FIRMS_PRODUCTS,
    SATELLITES,
)


class Observation(Base):
    """Hourly PM2.5 per monitor (µg/m³). ~72 h rolling window."""

    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("pm25 >= 0"),
        one_of("correction", CORRECTIONS),
        CheckConstraint("pm25_cf1_a >= 0"),
        CheckConstraint("pm25_cf1_b >= 0"),
        CheckConstraint("rh_pct BETWEEN 0 AND 100"),
        one_of("data_status", DATA_STATUSES),
        {"postgresql_partition_by": "RANGE (valid_at)"},
    )

    monitor_id: Mapped[str] = mapped_column(ForeignKey("monitors.id"), primary_key=True)
    valid_at: Mapped[datetime] = mapped_column(primary_key=True)  # start of hour, UTC
    received_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    pm25: Mapped[float]  # corrected for PurpleAir, raw regulatory for AirNow
    correction: Mapped[str]
    pm25_cf1_a: Mapped[float | None]  # PurpleAir channel A raw
    pm25_cf1_b: Mapped[float | None]  # PurpleAir channel B raw
    rh_pct: Mapped[float | None]
    qa_flag: Mapped[str | None]  # ok | suspect | invalid
    data_status: Mapped[str | None]

    monitor: Mapped["Monitor"] = relationship()


Index("ix_observations_valid_at", Observation.valid_at.desc())


class FireDetection(Base):
    """NASA FIRMS hotspot — a point, not a fire perimeter. 7-day window."""

    __tablename__ = "fire_detections"
    __table_args__ = (
        one_of("satellite", SATELLITES),
        one_of("product", FIRMS_PRODUCTS),
        one_of("confidence_level", CONFIDENCE_LEVELS),
        CheckConstraint("frp_mw >= 0"),
        CheckConstraint("scan_km > 0"),
        CheckConstraint("track_km > 0"),
        one_of("daynight", DAYNIGHT),
        Index("ix_fire_detections_geom", "geom", postgresql_using="gist"),
        Index("uq_fire_detections_dedup", "satellite", "external_id", "detected_at", unique=True),
        {"postgresql_partition_by": "RANGE (detected_at)"},
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    external_id: Mapped[str]  # hash of satellite + lat + lon + acq time
    satellite: Mapped[str]
    product: Mapped[str]
    geom: Mapped[WKBElement] = mapped_column(point(), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(primary_key=True)  # overpass time, UTC
    received_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confidence_raw: Mapped[str]  # as returned: 0–100 (MODIS) or l/n/h (VIIRS)
    confidence_level: Mapped[str]
    frp_mw: Mapped[float | None]
    bright_t31_k: Mapped[float | None]
    scan_km: Mapped[float | None]
    track_km: Mapped[float | None]
    daynight: Mapped[str | None]


Index("ix_fire_detections_detected_at", FireDetection.detected_at.desc())


class WeatherObservation(Base):
    """Measured surface weather from NWS stations."""

    __tablename__ = "weather_observations"
    __table_args__ = (
        CheckConstraint("wind_speed_ms >= 0"),
        CheckConstraint("wind_dir_deg BETWEEN 0 AND 360"),
        CheckConstraint("rh_pct BETWEEN 0 AND 100"),
        CheckConstraint("pressure_hpa > 800"),
        CheckConstraint("precip_1h_mm >= 0"),
        Index("ix_weather_obs_geom", "geom", postgresql_using="gist"),
        {"postgresql_partition_by": "RANGE (valid_at)"},
    )

    station_id: Mapped[str] = mapped_column(primary_key=True)  # e.g. KSAC
    valid_at: Mapped[datetime] = mapped_column(primary_key=True)
    received_at: Mapped[datetime]
    geom: Mapped[WKBElement] = mapped_column(point(), nullable=False)
    wind_speed_ms: Mapped[float | None]
    wind_dir_deg: Mapped[float | None]  # direction wind blows FROM, 0 = north
    temp_c: Mapped[float | None]
    rh_pct: Mapped[float | None]
    pressure_hpa: Mapped[float | None]
    precip_1h_mm: Mapped[float | None]
    qc_flag: Mapped[str | None]


Index("ix_weather_obs_valid_at", WeatherObservation.valid_at.desc())


class WeatherForecast(Base):
    """NWS hourly grid forecast. Many issued_at rows per valid_at."""

    __tablename__ = "weather_forecasts"
    __table_args__ = (
        CheckConstraint("wind_speed_ms >= 0"),
        CheckConstraint("wind_dir_deg BETWEEN 0 AND 360"),
        CheckConstraint("rh_pct BETWEEN 0 AND 100"),
        CheckConstraint("precip_prob_pct BETWEEN 0 AND 100"),
        {"postgresql_partition_by": "RANGE (valid_at)"},
    )

    grid_id: Mapped[str] = mapped_column(primary_key=True)  # e.g. STO/41,68
    issued_at: Mapped[datetime] = mapped_column(primary_key=True)
    valid_at: Mapped[datetime] = mapped_column(primary_key=True)
    received_at: Mapped[datetime]
    wind_speed_ms: Mapped[float | None]  # midpoint of NWS range, m/s
    wind_dir_deg: Mapped[float | None]
    temp_c: Mapped[float | None]
    rh_pct: Mapped[float | None]
    precip_prob_pct: Mapped[float | None]


Index(
    "ix_weather_fcst_valid_at",
    WeatherForecast.valid_at.desc(),
    WeatherForecast.issued_at.desc(),
)


class PointWeatherMap(Base):
    """Precomputed nearest NWS station + grid per forecast point."""

    __tablename__ = "point_weather_map"
    __table_args__ = (CheckConstraint("station_dist_km > 0"),)

    forecast_point_id: Mapped[str] = mapped_column(
        ForeignKey("forecast_points.id"), primary_key=True
    )
    station_id: Mapped[str]
    station_dist_km: Mapped[float]
    grid_id: Mapped[str]
    computed_at: Mapped[datetime]

    forecast_point: Mapped["ForecastPoint"] = relationship()

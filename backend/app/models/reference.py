"""Reference tables: cities, zip_codes, forecast_points, monitors."""

from datetime import datetime

from geoalchemy2 import WKBElement
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.models.base import Base, one_of, point
from app.models.values import KINDS, LOCATION_TYPES, MONITOR_SOURCES


class City(Base):
    """Stable join key for the History view (replaces free-text city joins)."""

    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("name", "state"),
        CheckConstraint("char_length(state) = 2"),
        Index("ix_cities_geom", "geom", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str]
    state: Mapped[str]
    timezone: Mapped[str]  # IANA zone, e.g. America/Los_Angeles
    geom: Mapped[WKBElement | None] = mapped_column(point())


class ForecastPoint(Base):
    """Every place the system can forecast for (city, ZIP, H3 cell, ad-hoc)."""

    __tablename__ = "forecast_points"
    __table_args__ = (
        one_of("kind", KINDS),
        Index("ix_forecast_points_geom", "geom", postgresql_using="gist"),
        Index("ix_forecast_points_city_id", "city_id"),
        Index("ix_forecast_points_forecast", "always_forecast", "last_requested_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    kind: Mapped[str]
    label: Mapped[str]
    h3_cell: Mapped[str | None]  # H3 resolution 7
    city_id: Mapped[str | None] = mapped_column(ForeignKey("cities.id"))
    geom: Mapped[WKBElement] = mapped_column(point(), nullable=False)
    timezone: Mapped[str]
    always_forecast: Mapped[bool] = mapped_column(server_default=true())
    last_requested_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    city: Mapped["City | None"] = relationship()


class ZipCode(Base):
    """Census ZCTA lookup; forecast_point_id is NULL until first requested."""

    __tablename__ = "zip_codes"
    __table_args__ = (Index("ix_zip_codes_geom", "geom", postgresql_using="gist"),)

    zcta: Mapped[str] = mapped_column(primary_key=True)
    state: Mapped[str]
    geom: Mapped[WKBElement | None] = mapped_column(point())
    area_km2: Mapped[float | None]
    forecast_point_id: Mapped[str | None] = mapped_column(
        ForeignKey("forecast_points.id", name="fk_zip_forecast_point")
    )

    forecast_point: Mapped["ForecastPoint | None"] = relationship()


class Monitor(Base):
    """AirNow / PurpleAir station. A sensor that moves > 500 m gets a new row."""

    __tablename__ = "monitors"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        one_of("source", MONITOR_SOURCES),
        one_of("location_type", LOCATION_TYPES),
        Index("ix_monitors_geom", "geom", postgresql_using="gist"),
        Index("ix_monitors_source_active", "source", "active", "location_type"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    source: Mapped[str]
    external_id: Mapped[str]  # AQS site code or PurpleAir sensor_index
    name: Mapped[str | None]
    city_id: Mapped[str | None] = mapped_column(ForeignKey("cities.id"))
    location_type: Mapped[str] = mapped_column(server_default="outdoor")
    geom: Mapped[WKBElement] = mapped_column(point(), nullable=False)
    elevation_m: Mapped[float | None]
    active: Mapped[bool] = mapped_column(server_default=true())
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime | None]

    city: Mapped["City | None"] = relationship()

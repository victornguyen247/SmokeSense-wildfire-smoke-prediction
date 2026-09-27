"""SQLAlchemy ORM models for the live database (docs/schema.md).

Importing this package registers every table on Base.metadata, which is what
Alembic's env.py compares against for autogenerate.
"""

from app.models.base import Base
from app.models.operations import IngestionRun
from app.models.predictions import Alert, Forecast, ForecastVerification, ModelVersion
from app.models.reference import City, ForecastPoint, Monitor, ZipCode
from app.models.rollups import CityMonthlyAggregate, MonitorDailyPm25
from app.models.timeseries import (
    FireDetection,
    Observation,
    PointWeatherMap,
    WeatherForecast,
    WeatherObservation,
)

__all__ = [
    "Alert",
    "Base",
    "City",
    "CityMonthlyAggregate",
    "FireDetection",
    "Forecast",
    "ForecastPoint",
    "ForecastVerification",
    "IngestionRun",
    "ModelVersion",
    "Monitor",
    "MonitorDailyPm25",
    "Observation",
    "PointWeatherMap",
    "WeatherForecast",
    "WeatherObservation",
    "ZipCode",
]

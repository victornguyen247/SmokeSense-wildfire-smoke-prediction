"""The real repository: data from PostGIS, in the shapes of docs/api/openapi.yaml.

Every response comes from one forecast cycle, because the contract carries a single
`issued_at` and `model_key`. The cycle is the newest non-shadow `issued_at` of a
production model, so a point left out of that cycle has no forecast rather than an
older one. The writer must therefore commit each cycle in one transaction.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import groupby
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.errors import ApiError
from app.core.geo import (
    DEFAULT_CELL_SIZE_M,
    LOW_CONFIDENCE_DIST_KM,
    MAX_INTERPOLATION_DIST_KM,
    california_grid_key,
)
from app.core.scope import CALIFORNIA_BBOX, OUT_OF_SCOPE
from app.models.values import HORIZON_HOURS
from app.repositories.base import Body
from app.repositories.cache import CycleCache
from app.repositories.freshness import source_freshness
from app.schemas.query import Bbox, PointQuery
from shared.aqi import (
    AQI_CATEGORIES,
    AQI_CATEGORY_LABEL,
    AQI_TABLE_VERSION,
    aqi_category,
    truncate_pm25,
)

FIRE_WINDOW_HOURS = 72
OBSERVATION_MAX_AGE_HOURS = 2

ENVELOPE = "ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)"
QUERY_POINT = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"
IN_CYCLE = "f.model_key = :model_key AND f.issued_at = :issued_at AND NOT f.is_shadow"

LATEST_CYCLE = text("""
    SELECT newest.issued_at, m.model_key
    FROM model_versions AS m
    CROSS JOIN LATERAL (
        SELECT f.issued_at
        FROM forecasts AS f
        WHERE f.model_key = m.model_key AND NOT f.is_shadow
        ORDER BY f.issued_at DESC
        LIMIT 1
    ) AS newest
    WHERE m.status = 'production'
    ORDER BY newest.issued_at DESC, m.model_key
    LIMIT 1
""")

PRODUCTION_MODEL = text("""
    SELECT model_key FROM model_versions
    WHERE status = 'production'
    ORDER BY status_changed_at DESC NULLS LAST, model_key
    LIMIT 1
""")

ANY_CELL_IN_BBOX = text(f"""
    SELECT EXISTS (
        SELECT 1 FROM forecast_points AS fp
        WHERE fp.kind = 'grid_cell' AND fp.active
          AND ST_Intersects(fp.cell_geom::geometry, {ENVELOPE})
    )
""")

GRID_CELLS = text(f"""
    SELECT fp.id, ST_AsGeoJSON(fp.cell_geom, 5) AS geometry
    FROM forecast_points AS fp
    WHERE fp.kind = 'grid_cell' AND fp.active
      AND ST_Intersects(fp.cell_geom::geometry, {ENVELOPE})
    ORDER BY fp.id
""")

GRID_VALUES = text(f"""
    SELECT f.horizon_hours, fp.id, f.pm25_predicted, f.nearest_monitor_dist_km
    FROM forecasts AS f
    JOIN forecast_points AS fp ON fp.id = f.forecast_point_id
    WHERE {IN_CYCLE}
      AND fp.kind = 'grid_cell' AND fp.active
      AND ST_Intersects(fp.cell_geom::geometry, {ENVELOPE})
    ORDER BY f.horizon_hours, fp.id
""")

MONITOR_VALUES = text(f"""
    SELECT fp.id, m.aqs_code, m.name,
           ST_Y(fp.geom::geometry) AS lat, ST_X(fp.geom::geometry) AS lon,
           f.horizon_hours, f.target_time, f.pm25_predicted, f.source,
           f.nearest_monitor_dist_km
    FROM forecasts AS f
    JOIN forecast_points AS fp ON fp.id = f.forecast_point_id
    JOIN monitors AS m ON m.id = fp.monitor_id
    WHERE {IN_CYCLE}
      AND fp.kind = 'monitor' AND fp.active AND m.aqs_code IS NOT NULL
      AND ST_Intersects(fp.geom::geometry, {ENVELOPE})
    ORDER BY fp.id, f.horizon_hours
""")

CELL_AT_LOCATION = text("SELECT forecast_point_id FROM lookup_grid_forecast_point(:lon, :lat)")

ZIP_LOCATION = text("""
    SELECT forecast_point_id, area_km2,
           ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
    FROM zip_codes
    WHERE zcta = :zip AND forecast_point_id IS NOT NULL AND geom IS NOT NULL
""")

CELL_CENTROID = text("""
    SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon
    FROM forecast_points
    WHERE id = :id
""")

POINT_VALUES = text(f"""
    SELECT f.horizon_hours, f.target_time, f.pm25_predicted, f.source, f.nearest_monitor_dist_km
    FROM forecasts AS f
    WHERE f.forecast_point_id = :id AND {IN_CYCLE}
    ORDER BY f.horizon_hours
""")

# Monitors Stage B can use (never `fallback`), with no 50 km limit.
NEAREST_USABLE_MONITOR_KM = text(f"""
    SELECT min(ST_Distance(fp.geom, cell.geom, false)) / 1000 AS km
    FROM forecasts AS f
    JOIN forecast_points AS fp ON fp.id = f.forecast_point_id
    JOIN forecast_points AS cell ON cell.id = :cell_id
    WHERE {IN_CYCLE}
      AND fp.kind = 'monitor' AND fp.active AND f.source IN ('v2', 'persistence')
""")

# The physically nearest monitor of any source, from the query location.
NEAREST_MONITOR = text(f"""
    SELECT fp.id, m.aqs_code, m.name,
           ST_Y(fp.geom::geometry) AS lat, ST_X(fp.geom::geometry) AS lon,
           ST_Distance(fp.geom, {QUERY_POINT}, false) / 1000 AS km
    FROM forecast_points AS fp
    JOIN monitors AS m ON m.id = fp.monitor_id
    WHERE fp.kind = 'monitor' AND fp.active AND m.aqs_code IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM forecasts AS f
          WHERE f.forecast_point_id = fp.id AND {IN_CYCLE}
      )
    ORDER BY km, fp.id
    LIMIT 1
""")


ACTIVE_FIRES = text(f"""
    SELECT f.id, f.detected_at, f.satellite, f.product, f.confidence_level, f.confidence_raw,
           f.frp_mw, f.daynight,
           ST_Y(f.geom::geometry) AS lat, ST_X(f.geom::geometry) AS lon
    FROM fire_detections AS f
    WHERE f.satellite = 'VIIRS_SNPP'
      AND f.detected_at >= :window_start AND f.detected_at < :window_end
      AND ST_Intersects(f.geom::geometry, {ENVELOPE})
    ORDER BY f.detected_at DESC, f.id
""")

# Each sensor's newest eligible reading (docs/api.md). Raw and failed-QA PurpleAir values
# never count, so an older good reading wins over a newer bad one.
LATEST_OBSERVATIONS = text(f"""
    SELECT DISTINCT ON (o.monitor_id)
           o.monitor_id, o.valid_at, o.pm25, o.correction,
           m.source AS provider, m.aqs_code, m.external_id, m.name,
           ST_Y(m.geom::geometry) AS lat, ST_X(m.geom::geometry) AS lon
    FROM observations AS o
    JOIN monitors AS m ON m.id = o.monitor_id
    WHERE o.valid_at >= :oldest AND o.valid_at <= :now
      AND m.active AND m.location_type = 'outdoor'
      AND (
          (m.source = 'airnow' AND o.correction = 'regulatory' AND m.aqs_code IS NOT NULL)
          OR (m.source = 'purpleair' AND o.correction = 'purpleair_barkjohn' AND o.qa_flag = 'ok')
      )
      AND ST_Intersects(m.geom::geometry, {ENVELOPE})
    ORDER BY o.monitor_id, o.valid_at DESC
""")


class Cycle(NamedTuple):
    issued_at: datetime
    model_key: str


class Location(NamedTuple):
    """A /forecast/point query resolved to a place and its grid cell."""

    lat: float
    lon: float
    zip: str | None
    zip_area_km2: float | None
    cell_id: str


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def lat_lon(lat: float, lon: float) -> Body:
    return {"lat": round(lat, 5), "lon": round(lon, 5)}


def envelope(cycle: Cycle) -> Body:
    return {
        "issued_at": iso(cycle.issued_at),
        "model_key": cycle.model_key,
        "aqi_table_version": AQI_TABLE_VERSION,
    }


def forecast_value(row: Any) -> Body:
    return {
        "horizon_hours": row.horizon_hours,
        "target_time": iso(row.target_time),
        "pm25": truncate_pm25(row.pm25_predicted),
        "aqi_category": aqi_category(row.pm25_predicted),
        "method": "interpolated" if row.source == "idw" else "model",
        "source": row.source,
        "nearest_monitor_dist_km": round(row.nearest_monitor_dist_km, 1),
    }


def monitor_feature(rows: Iterable[Any]) -> Body:
    rows = list(rows)
    first = rows[0]
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(first.lon, 5), round(first.lat, 5)]},
        "properties": {
            "forecast_point_id": first.id,
            "aqs_code": first.aqs_code,
            "name": first.name,
            "forecasts": [forecast_value(row) for row in rows],
        },
    }


def fire_feature(row: Any) -> Body:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(row.lon, 5), round(row.lat, 5)]},
        "properties": {
            "detection_id": row.id,
            "detected_at": iso(row.detected_at),
            "satellite": row.satellite,
            "product": row.product,
            "confidence": row.confidence_level,
            "confidence_raw": row.confidence_raw,
            "frp_mw": None if row.frp_mw is None else round(row.frp_mw, 1),
            "daynight": row.daynight,
        },
    }


def observation_feature(row: Any) -> Body:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(row.lon, 5), round(row.lat, 5)]},
        "properties": {
            "monitor_id": row.monitor_id,
            "provider": row.provider,
            "station_code": row.aqs_code if row.provider == "airnow" else row.external_id,
            "name": row.name,
            "valid_at": iso(row.valid_at),
            "pm25": truncate_pm25(row.pm25),
            "aqi_category": aqi_category(row.pm25),
            "correction": row.correction,
        },
    }


class DatabaseRepository:
    def __init__(self, sessions: sessionmaker[Session], cache: CycleCache) -> None:
        self.sessions = sessions
        self.cache = cache

    def grid_cells(self, bbox: Bbox) -> Body:
        with self.sessions() as session:
            self._check_bbox(session, bbox)
            rows = session.execute(GRID_CELLS, bbox._asdict()).all()
        return {
            "type": "FeatureCollection",
            "grid_key": california_grid_key(),
            "cell_size_m": DEFAULT_CELL_SIZE_M,
            "bbox": list(bbox),
            "cell_count": len(rows),
            "features": [
                {
                    "type": "Feature",
                    "geometry": json.loads(row.geometry),
                    "properties": {"id": row.id},
                }
                for row in rows
            ],
        }

    def forecast_grid(self, bbox: Bbox) -> Body:
        with self.sessions() as session:
            self._check_bbox(session, bbox)
            cycle = self._latest_cycle(session)
            return self.cache.get_or_build(
                cycle, ("forecast_grid", bbox), lambda: self._grid_forecast(session, cycle, bbox)
            )

    def forecast_monitors(self, bbox: Bbox) -> Body:
        with self.sessions() as session:
            self._check_bbox(session, bbox)
            cycle = self._latest_cycle(session)
            return self.cache.get_or_build(
                cycle,
                ("forecast_monitors", bbox),
                lambda: self._monitor_forecasts(session, cycle, bbox),
            )

    def forecast_point(self, point: PointQuery) -> Body:
        with self.sessions() as session:
            location = self._resolve(session, point)
            cycle = self._latest_cycle(session)
            return {
                **envelope(cycle),
                "query": {
                    **lat_lon(location.lat, location.lon),
                    "zip": location.zip,
                    "zip_area_km2": location.zip_area_km2,
                },
                "cell": self._cell_forecast(session, cycle, location.cell_id),
                "nearest_monitor": self._nearest_monitor(session, cycle, location),
            }

    def active_fires(self, bbox: Bbox) -> Body:
        now = utc_now()
        window_start = now - timedelta(hours=FIRE_WINDOW_HOURS)
        params = {**bbox._asdict(), "window_start": window_start, "window_end": now}
        with self.sessions() as session:
            self._check_bbox(session, bbox)
            rows = session.execute(ACTIVE_FIRES, params).all()
        return {
            "type": "FeatureCollection",
            "generated_at": iso(now),
            "window_hours": FIRE_WINDOW_HOURS,
            "window_start": iso(window_start),
            "window_end": iso(now),
            "detection_count": len(rows),
            "features": [fire_feature(row) for row in rows],
        }

    def latest_pm25(self, bbox: Bbox) -> Body:
        now = utc_now()
        oldest = now - timedelta(hours=OBSERVATION_MAX_AGE_HOURS)
        with self.sessions() as session:
            self._check_bbox(session, bbox)
            rows = session.execute(
                LATEST_OBSERVATIONS, {**bbox._asdict(), "oldest": oldest, "now": now}
            ).all()
        return {
            "type": "FeatureCollection",
            "generated_at": iso(now),
            "max_age_hours": OBSERVATION_MAX_AGE_HOURS,
            "aqi_table_version": AQI_TABLE_VERSION,
            "features": [observation_feature(row) for row in rows],
        }

    def meta(self) -> Body:
        """Everything but mock_mode, which meta_service sets from the setting."""
        now = utc_now()
        with self.sessions() as session:
            cycle = self._find_cycle(session)
            model_key = cycle.model_key if cycle else session.scalar(PRODUCTION_MODEL)
            sources = source_freshness(session, now)
        age = None if cycle is None else max(0, int((now - cycle.issued_at).total_seconds() // 60))
        stale_after = settings.forecast_stale_after_minutes
        return {
            "generated_at": iso(now),
            "api_version": "v1",
            "model_key": model_key,
            "model_status": None if model_key is None else "production",
            "latest_issued_at": None if cycle is None else iso(cycle.issued_at),
            "forecast_age_minutes": age,
            "forecast_stale_after_minutes": stale_after,
            "forecast_stale": age is None or age > stale_after,
            "horizons": list(HORIZON_HOURS),
            "grid_key": california_grid_key(),
            "low_confidence_dist_km": LOW_CONFIDENCE_DIST_KM,
            "max_interpolation_dist_km": MAX_INTERPOLATION_DIST_KM,
            "aqi_category_label": AQI_CATEGORY_LABEL,
            "aqi_table_version": AQI_TABLE_VERSION,
            "aqi_categories": [category._asdict() for category in AQI_CATEGORIES],
            "sources": sources,
        }

    def _find_cycle(self, session: Session) -> Cycle | None:
        row = session.execute(LATEST_CYCLE).first()
        return None if row is None else Cycle(row.issued_at, row.model_key)

    def _latest_cycle(self, session: Session) -> Cycle:
        cycle = self._find_cycle(session)
        if cycle is None:
            raise ApiError(503, "forecast_unavailable", "No forecast cycle is available yet.")
        return cycle

    def _check_bbox(self, session: Session, bbox: Bbox) -> None:
        """CALIFORNIA_BBOX is a rough box, so a clipped bbox can still miss the state."""
        if bbox != CALIFORNIA_BBOX and not session.scalar(ANY_CELL_IN_BBOX, bbox._asdict()):
            raise ApiError(404, "out_of_scope", f"bbox {bbox} is outside California; {OUT_OF_SCOPE}")

    def _grid_forecast(self, session: Session, cycle: Cycle, bbox: Bbox) -> Body:
        cells: dict[int, list[Body]] = {hours: [] for hours in HORIZON_HOURS}
        for row in session.execute(GRID_VALUES, {**bbox._asdict(), **cycle._asdict()}):
            cells[row.horizon_hours].append(
                {
                    "id": row.id,
                    "pm25": truncate_pm25(row.pm25_predicted),
                    "aqi_category": aqi_category(row.pm25_predicted),
                    "nearest_monitor_dist_km": round(row.nearest_monitor_dist_km, 1),
                }
            )
        return {
            **envelope(cycle),
            "grid_key": california_grid_key(),
            "method": "interpolated",
            "source": "idw",
            "bbox": list(bbox),
            "horizons": [
                {
                    "horizon_hours": hours,
                    "target_time": iso(cycle.issued_at + timedelta(hours=hours)),
                    "cells": cells[hours],
                }
                for hours in HORIZON_HOURS
            ],
        }

    def _monitor_forecasts(self, session: Session, cycle: Cycle, bbox: Bbox) -> Body:
        rows = session.execute(MONITOR_VALUES, {**bbox._asdict(), **cycle._asdict()})
        return {
            **envelope(cycle),
            "type": "FeatureCollection",
            "features": [
                monitor_feature(group) for _, group in groupby(rows, key=lambda row: row.id)
            ],
        }

    def _resolve(self, session: Session, point: PointQuery) -> Location:
        if point.zip is not None:
            row = session.execute(ZIP_LOCATION, {"zip": point.zip}).first()
            if row is None:
                raise ApiError(404, "zip_not_found", f"No ZIP code area found for {point.zip}.")
            return Location(row.lat, row.lon, point.zip, row.area_km2, row.forecast_point_id)
        cell_id = session.scalar(CELL_AT_LOCATION, {"lat": point.lat, "lon": point.lon})
        if cell_id is None:
            raise ApiError(
                404,
                "out_of_scope",
                f"Point ({point.lat}, {point.lon}) is outside California; {OUT_OF_SCOPE}",
            )
        return Location(point.lat, point.lon, None, None, cell_id)

    def _cell_forecast(self, session: Session, cycle: Cycle, cell_id: str) -> Body:
        centroid = session.execute(CELL_CENTROID, {"id": cell_id}).one()
        rows = session.execute(POINT_VALUES, {"id": cell_id, **cycle._asdict()}).all()
        if rows:
            distance = min(row.nearest_monitor_dist_km for row in rows)
        else:
            distance = session.scalar(
                NEAREST_USABLE_MONITOR_KM, {"cell_id": cell_id, **cycle._asdict()}
            )
        return {
            "forecast_point_id": cell_id,
            "centroid": lat_lon(centroid.lat, centroid.lon),
            "has_forecast": bool(rows),
            "no_forecast_reason": None if rows else "no_monitor_within_50km",
            "nearest_monitor_dist_km": None if distance is None else round(distance, 1),
            "forecasts": [forecast_value(row) for row in rows],
        }

    def _nearest_monitor(self, session: Session, cycle: Cycle, location: Location) -> Body | None:
        params = {"lat": location.lat, "lon": location.lon, **cycle._asdict()}
        monitor = session.execute(NEAREST_MONITOR, params).first()
        if monitor is None:
            return None
        rows = session.execute(POINT_VALUES, {"id": monitor.id, **cycle._asdict()})
        return {
            "forecast_point_id": monitor.id,
            "aqs_code": monitor.aqs_code,
            "name": monitor.name,
            "location": lat_lon(monitor.lat, monitor.lon),
            "distance_km": round(monitor.km, 1),
            "forecasts": [forecast_value(row) for row in rows],
        }

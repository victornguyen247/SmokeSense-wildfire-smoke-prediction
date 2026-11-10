"""The real repository: forecasts from PostGIS, in the shapes of docs/api/openapi.yaml.

Every response comes from one forecast cycle, because the contract carries a single
`issued_at` and `model_key`. The cycle is the newest successful pipeline_runs row, the
same source as pipeline/status.py: the pipeline commits monitor and grid rows in
separate stages and marks a run successful only after both, so that cycle is complete.
A point left out of it has no forecast rather than an older one. If that run's model is
not production (the local stub is shadow), there is no forecast: older grid rows are
trimmed when a run succeeds, so falling back to an older run would serve an empty grid.

/fires, /observations and /meta are API-03. They raise here instead of falling back to
the fixtures, which would pass demo data off as live.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import groupby
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ApiError
from app.core.geo import DEFAULT_CELL_SIZE_M, california_grid_key
from app.core.scope import CALIFORNIA_BBOX, OUT_OF_SCOPE
from app.models.values import HORIZON_HOURS
from app.repositories.base import Body
from app.repositories.cache import CycleCache
from app.schemas.query import Bbox, PointQuery
from shared.aqi import AQI_TABLE_VERSION, aqi_category, truncate_pm25

ENVELOPE = "ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)"
QUERY_POINT = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography"
IN_CYCLE = "f.model_key = :model_key AND f.issued_at = :issued_at AND NOT f.is_shadow"

LATEST_CYCLE = text("""
    SELECT newest.issued_at, newest.model_key
    FROM (
        SELECT r.issued_at, r.model_key
        FROM pipeline_runs AS r
        WHERE r.status = 'success'
        ORDER BY r.issued_at DESC
        LIMIT 1
    ) AS newest
    JOIN model_versions AS m ON m.model_key = newest.model_key AND m.status = 'production'
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
        raise NotImplementedError("/fires/active needs API-03")

    def latest_pm25(self, bbox: Bbox) -> Body:
        raise NotImplementedError("/observations/pm25/latest needs API-03")

    def meta(self) -> Body:
        raise NotImplementedError("/meta needs API-03")

    def _latest_cycle(self, session: Session) -> Cycle:
        row = session.execute(LATEST_CYCLE).first()
        if row is None:
            raise ApiError(503, "forecast_unavailable", "No forecast cycle is available yet.")
        return Cycle(row.issued_at, row.model_key)

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

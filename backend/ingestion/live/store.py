"""Idempotent writes for live rows.

Every row is tagged with the run's ingestion_run_id (migration 0006). Re-running a
job over the same window upserts on the table's natural key, so it never adds rows.
A row with ingestion_run_id NULL is a historical (DATA-03 batch) row: these writes
never modify one, and retention never deletes one.

Rows go in chunks of CHUNK_ROWS so a statewide pull never builds one huge statement.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from ingestion.db import point_wkt

CHUNK_ROWS = 1000


def chunked(rows: Iterable[dict], size: int = CHUNK_ROWS) -> Iterator[list[dict]]:
    chunk: list[dict] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _executemany(session: Session, statement, params: list[dict]) -> int:
    """Run one statement per params dict; total rows inserted or updated."""
    written = 0
    for chunk in chunked(params):
        written += session.execute(statement, chunk).rowcount
    return written


# ---------------------------------------------------------------------------
# fire_detections
# ---------------------------------------------------------------------------

# Dedupe key is (satellite, detection time, exact pixel centre): the FIRMS
# (satellite, acq_date, acq_time, latitude, longitude). The NOT EXISTS enforces it
# against rows already stored, live or historical; the unique index on
# (satellite, external_id, detected_at) backs it up under concurrent runs.
_INSERT_FIRE = text("""
    INSERT INTO fire_detections (
        id, external_id, satellite, product, geom, detected_at, received_at,
        confidence_raw, confidence_level, frp_mw, bright_t31_k, scan_km, track_km,
        daynight, ingestion_run_id)
    SELECT :id, :external_id, :satellite, :product, ST_GeogFromText(:geom), :detected_at,
           :received_at, :confidence_raw, :confidence_level, :frp_mw, :bright_t31_k,
           :scan_km, :track_km, :daynight, :ingestion_run_id
    WHERE NOT EXISTS (
        SELECT 1 FROM fire_detections f
        WHERE f.satellite = :satellite AND f.detected_at = :detected_at
          AND ST_Y(f.geom::geometry) = :latitude AND ST_X(f.geom::geometry) = :longitude)
    ON CONFLICT (satellite, external_id, detected_at) DO NOTHING
""")


def fire_key(record: dict) -> tuple:
    """(satellite, detected_at, latitude, longitude): one FIRMS detection."""
    return (
        record["satellite"],
        record["detected_at"],
        record["latitude"],
        record["longitude"],
    )


def insert_fire_detections(
    session: Session, records: Iterable[dict], run_id: str
) -> int:
    """Insert detections not already stored; returns how many were new.

    First write wins: a detection already stored (live or historical) is left as it
    is, so a re-run over the same window writes nothing.
    """
    params = [
        {
            "id": uuid7(),
            "external_id": r["external_id"],
            "satellite": r["satellite"],
            "product": r["product"],
            "geom": point_wkt(r["latitude"], r["longitude"]),
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "detected_at": r["detected_at"],
            "received_at": r["received_at"],
            "confidence_raw": r["confidence_raw"],
            "confidence_level": r["confidence_level"],
            "frp_mw": r["frp_mw"],
            "bright_t31_k": r["bright_t31_k"],
            "scan_km": r["scan_km"],
            "track_km": r["track_km"],
            "daynight": r["daynight"],
            "ingestion_run_id": run_id,
        }
        for r in records
    ]
    return _executemany(session, _INSERT_FIRE, params)


# ---------------------------------------------------------------------------
# monitors + observations (AirNow, PurpleAir)
# ---------------------------------------------------------------------------

_SELECT_MONITORS = text(
    "SELECT external_id, id FROM monitors WHERE source = :source AND external_id IN :ids"
).bindparams(bindparam("ids", expanding=True))

_INSERT_MONITOR = text("""
    INSERT INTO monitors (id, source, external_id, aqs_code, name, location_type, geom,
                          elevation_m, active, first_seen_at, last_seen_at)
    VALUES (:id, :source, :external_id, :aqs_code, :name, :location_type,
            ST_GeogFromText(:geom), :elevation_m, :active, :first_seen_at, :last_seen_at)
    ON CONFLICT (source, external_id) DO NOTHING
""")

# Same rule as ingestion.db.get_or_create_monitor: an existing monitor only gains a
# missing aqs_code; last_seen_at moves forward.
_TOUCH_MONITOR = text("""
    UPDATE monitors
    SET last_seen_at = GREATEST(COALESCE(last_seen_at, :last_seen_at), :last_seen_at),
        aqs_code = COALESCE(aqs_code, :aqs_code)
    WHERE id = :id
      AND (last_seen_at IS NULL OR last_seen_at < :last_seen_at
           OR (aqs_code IS NULL AND CAST(:aqs_code AS TEXT) IS NOT NULL))
""")


def upsert_monitors(session: Session, monitors: Iterable[dict]) -> dict[str, str]:
    """Create unseen monitors and refresh last_seen_at; returns {external_id: monitors.id}.

    monitors are the "monitor" dicts the AirNow/PurpleAir normalizers build. One
    source per call. A monitor with no coordinates cannot be created and is left out.
    """
    by_external: dict[str, dict] = {}
    for m in monitors:
        by_external.setdefault(m["external_id"], m)
    if not by_external:
        return {}
    source = next(iter(by_external.values()))["source"]

    def existing() -> dict[str, str]:
        found: dict[str, str] = {}
        ids = list(by_external)
        for i in range(0, len(ids), CHUNK_ROWS):
            rows = session.execute(
                _SELECT_MONITORS, {"source": source, "ids": ids[i : i + CHUNK_ROWS]}
            )
            found.update(dict(rows.all()))
        return found

    ids = existing()
    new = [
        {
            "id": uuid7(),
            "source": m["source"],
            "external_id": ext,
            "aqs_code": m.get("aqs_code"),
            "name": m["name"],
            "location_type": m.get("location_type") or "outdoor",
            "geom": point_wkt(m["latitude"], m["longitude"]),
            "elevation_m": m.get("elevation_m"),
            "active": m.get("active", True),
            "first_seen_at": m["first_seen_at"],
            "last_seen_at": m["last_seen_at"],
        }
        for ext, m in by_external.items()
        if ext not in ids
        and m.get("latitude") is not None
        and m.get("longitude") is not None
    ]
    if new:
        _executemany(session, _INSERT_MONITOR, new)
        ids = existing()

    touched = [
        {
            "id": ids[ext],
            "last_seen_at": m["last_seen_at"],
            "aqs_code": m.get("aqs_code"),
        }
        for ext, m in by_external.items()
        if ext in ids
    ]
    _executemany(session, _TOUCH_MONITOR, touched)
    return ids


# A live row whose values changed (a late AirNow revision) is updated; an
# unchanged one is left alone, so a re-run writes nothing. Historical rows (ingestion_run_id NULL) are never touched.
_UPSERT_OBSERVATION = text("""
    INSERT INTO observations (monitor_id, valid_at, received_at, pm25, correction,
                              pm25_cf1_a, pm25_cf1_b, rh_pct, qa_flag, data_status,
                              ingestion_run_id)
    VALUES (:monitor_id, :valid_at, :received_at, :pm25, :correction, :pm25_cf1_a,
            :pm25_cf1_b, :rh_pct, :qa_flag, :data_status, :ingestion_run_id)
    ON CONFLICT (monitor_id, valid_at) DO UPDATE SET
        received_at = EXCLUDED.received_at,
        ingested_at = now(),
        pm25 = EXCLUDED.pm25,
        correction = EXCLUDED.correction,
        pm25_cf1_a = EXCLUDED.pm25_cf1_a,
        pm25_cf1_b = EXCLUDED.pm25_cf1_b,
        rh_pct = EXCLUDED.rh_pct,
        qa_flag = EXCLUDED.qa_flag,
        data_status = EXCLUDED.data_status,
        ingestion_run_id = EXCLUDED.ingestion_run_id
    WHERE observations.ingestion_run_id IS NOT NULL
      AND (observations.pm25, observations.correction, observations.pm25_cf1_a,
           observations.pm25_cf1_b, observations.rh_pct, observations.qa_flag,
           observations.data_status)
          IS DISTINCT FROM
          (EXCLUDED.pm25, EXCLUDED.correction, EXCLUDED.pm25_cf1_a, EXCLUDED.pm25_cf1_b,
           EXCLUDED.rh_pct, EXCLUDED.qa_flag, EXCLUDED.data_status)
""")


def upsert_observations(session: Session, records: Iterable[dict], run_id: str) -> int:
    """Upsert normalized AirNow/PurpleAir records (monitor + observation); rows written.

    Monitors are created or refreshed first. Records whose monitor could not be
    created (no coordinates) are skipped.
    """
    records = list(records)
    ids = upsert_monitors(session, (r["monitor"] for r in records))
    params = [
        {
            "monitor_id": ids[r["monitor"]["external_id"]],
            "valid_at": r["observation"]["valid_at"],
            "received_at": r["observation"]["received_at"],
            "pm25": r["observation"]["pm25"],
            "correction": r["observation"]["correction"],
            "pm25_cf1_a": r["observation"]["pm25_cf1_a"],
            "pm25_cf1_b": r["observation"]["pm25_cf1_b"],
            "rh_pct": r["observation"]["rh_pct"],
            "qa_flag": r["observation"]["qa_flag"],
            "data_status": r["observation"]["data_status"],
            "ingestion_run_id": run_id,
        }
        for r in records
        if r["monitor"]["external_id"] in ids
    ]
    return _executemany(session, _UPSERT_OBSERVATION, params)


# ---------------------------------------------------------------------------
# weather_observations (NWS)
# ---------------------------------------------------------------------------

_UPSERT_WEATHER = text("""
    INSERT INTO weather_observations (station_id, valid_at, received_at, geom, wind_speed_ms,
                                      wind_dir_deg, temp_c, rh_pct, pressure_hpa,
                                      precip_1h_mm, qc_flag, ingestion_run_id)
    VALUES (:station_id, :valid_at, :received_at, ST_GeogFromText(:geom), :wind_speed_ms,
            :wind_dir_deg, :temp_c, :rh_pct, :pressure_hpa, :precip_1h_mm, :qc_flag,
            :ingestion_run_id)
    ON CONFLICT (station_id, valid_at) DO UPDATE SET
        received_at = EXCLUDED.received_at,
        wind_speed_ms = EXCLUDED.wind_speed_ms,
        wind_dir_deg = EXCLUDED.wind_dir_deg,
        temp_c = EXCLUDED.temp_c,
        rh_pct = EXCLUDED.rh_pct,
        pressure_hpa = EXCLUDED.pressure_hpa,
        precip_1h_mm = EXCLUDED.precip_1h_mm,
        qc_flag = EXCLUDED.qc_flag,
        ingestion_run_id = EXCLUDED.ingestion_run_id
    WHERE weather_observations.ingestion_run_id IS NOT NULL
      AND (weather_observations.wind_speed_ms, weather_observations.wind_dir_deg,
           weather_observations.temp_c, weather_observations.rh_pct,
           weather_observations.pressure_hpa, weather_observations.precip_1h_mm,
           weather_observations.qc_flag)
          IS DISTINCT FROM
          (EXCLUDED.wind_speed_ms, EXCLUDED.wind_dir_deg, EXCLUDED.temp_c, EXCLUDED.rh_pct,
           EXCLUDED.pressure_hpa, EXCLUDED.precip_1h_mm, EXCLUDED.qc_flag)
""")


def upsert_weather(session: Session, records: Iterable[dict], run_id: str) -> int:
    """Upsert normalized weather records on (station_id, valid_at); rows written."""
    params = [
        {
            "station_id": r["station_id"],
            "valid_at": r["valid_at"],
            "received_at": r["received_at"],
            "geom": point_wkt(r["latitude"], r["longitude"]),
            "wind_speed_ms": r["wind_speed_ms"],
            "wind_dir_deg": r["wind_dir_deg"],
            "temp_c": r["temp_c"],
            "rh_pct": r["rh_pct"],
            "pressure_hpa": r["pressure_hpa"],
            "precip_1h_mm": r["precip_1h_mm"],
            "qc_flag": r["qc_flag"],
            "ingestion_run_id": run_id,
        }
        for r in records
    ]
    return _executemany(session, _UPSERT_WEATHER, params)

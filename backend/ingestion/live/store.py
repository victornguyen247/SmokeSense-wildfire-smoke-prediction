"""Idempotent writes for live rows.

Every row is tagged with the run's ingestion_run_id (migration 0006). Re-running a
job over the same window upserts on the table's natural key, so it never adds rows.
A row with ingestion_run_id NULL is a historical (DATA-03 batch) row: these writes
never modify one, and retention never deletes one.

Rows go in chunks of CHUNK_ROWS so a statewide pull never builds one huge statement.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from sqlalchemy import text
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

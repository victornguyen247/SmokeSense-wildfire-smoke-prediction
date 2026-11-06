"""Idempotent forecast writes: re-running an issue hour overwrites its rows."""

from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from ingestion.live.store import chunked

_UPSERT = text("""
    INSERT INTO forecasts (id, forecast_point_id, model_key, issued_at, horizon_hours,
        target_time, pm25_predicted, source, nearest_monitor_dist_km, is_shadow,
        feature_snapshot)
    VALUES (:id, :forecast_point_id, :model_key, :issued_at, :horizon_hours, :target_time,
        :pm25_predicted, :source, :nearest_monitor_dist_km, FALSE,
        CAST(:feature_snapshot AS jsonb))
    ON CONFLICT (forecast_point_id, model_key, issued_at, horizon_hours) DO UPDATE SET
        target_time = EXCLUDED.target_time,
        pm25_predicted = EXCLUDED.pm25_predicted,
        source = EXCLUDED.source,
        nearest_monitor_dist_km = EXCLUDED.nearest_monitor_dist_km,
        feature_snapshot = EXCLUDED.feature_snapshot
""")


def _snapshot(value) -> str | None:
    if value is None or (not isinstance(value, (dict, list, str)) and pd.isna(value)):
        return None
    return value if isinstance(value, str) else json.dumps(value)


def upsert_forecasts(session: Session, frame: pd.DataFrame) -> int:
    """Write rows shaped like serving-contract §5 (+ nearest_monitor_dist_km, optional
    feature_snapshot). Returns rows written. The caller commits."""
    written = 0
    rows = []
    for r in frame.to_dict("records"):
        rows.append({
            "id": uuid7(),
            "forecast_point_id": r["forecast_point_id"],
            "model_key": r["model_key"],
            "issued_at": pd.Timestamp(r["issued_at"]).to_pydatetime(),
            "horizon_hours": int(r["horizon_hours"]),
            "target_time": pd.Timestamp(r["target_time"]).to_pydatetime(),
            "pm25_predicted": float(r["pm25_predicted"]),
            "source": r["source"],
            "nearest_monitor_dist_km": float(r.get("nearest_monitor_dist_km", 0.0)),
            "feature_snapshot": _snapshot(r.get("feature_snapshot")),
        })
    for chunk in chunked(rows):
        written += session.execute(_UPSERT, chunk).rowcount
    return written

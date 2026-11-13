"""Stage implementations and the registry that picks one per stage from the environment.

A stage is `fn(ctx) -> StageResult`. It reads its input from the database or from the
previous stage's frame (ctx.load), writes its own output (committing it), and returns
row counts. Because stages hand work over through the database or a Parquet file, each
can be retried alone.

`stub` stages need no model or feature code (fake features, persistence). `real`
stages call serving.geo. PIPELINE_<STAGE>_STAGE may also be "package.module:callable".
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.freshness import max_data_age_minutes, source_freshness
from pipeline import settings
from pipeline.store import upsert_forecasts

logger = logging.getLogger("pipeline")

HORIZONS = (1, 3, 6, 12, 24)


class StageError(RuntimeError):
    """A stage could not do its job (message is stored on the run, so keep it safe)."""


@dataclass
class StageResult:
    rows_in: int = 0
    rows_out: int = 0
    model_key: str | None = None


@dataclass
class StageContext:
    session: Session
    run_id: str
    issued_at: datetime  # tz-aware UTC top of the hour

    def _path(self, name: str) -> Path:
        return settings.work_dir() / self.run_id / f"{name}.parquet"

    def save(self, name: str, frame: pd.DataFrame) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)

    def load(self, name: str) -> pd.DataFrame:
        path = self._path(name)
        if not path.is_file():
            raise StageError(f"missing input '{name}' for run {self.run_id}; the earlier stage did not finish")
        return pd.read_parquet(path)


Stage = Callable[[StageContext], StageResult]


# ---- check_ingest -------------------------------------------------------------------


def ingest_freshness(session: Session) -> dict[str, dict]:
    """{/meta source name: SourceFreshness item}, each source judged by its job alone.
    Unlike /meta, an old newest FIRMS detection does not make FIRMS stale here
    (decision #48): with no detection the features see "no fires"."""
    return {
        s["source"]: s for s in source_freshness(session, include_data_age=False)
    }


def ingest_status(session: Session) -> dict[str, bool]:
    """{/meta source name: stale?} from ingestion_runs, by job alone."""
    return {name: s["stale"] for name, s in ingest_freshness(session).items()}


def check_ingest(ctx: StageContext) -> StageResult:
    """Refuse to forecast when AirNow has not run recently. A stale NWS feed only warns:
    the serving contract has degrade rules for missing weather. The run is scheduled at
    :45 (the contract's H+45 cutoff), so a still-missing H-1 reading is a real gap: warn
    and go on with a null lag instead of waiting."""
    status = ingest_status(ctx.session)
    if status.get("airnow", True):
        raise StageError("ingest is stale or has never succeeded: airnow")
    if status.get("nws_obs", True):
        logger.warning("pipeline run %s: NWS observations are stale; weather features will be null", ctx.run_id)
    have_lag = ctx.session.execute(
        text("SELECT 1 FROM observations WHERE valid_at = :t - interval '1 hour' LIMIT 1"),
        {"t": ctx.issued_at},
    ).first()
    if not have_lag:
        logger.warning("pipeline run %s: no AirNow reading for %s h-1 yet; lag features will be null",
                       ctx.run_id, ctx.issued_at.isoformat())
    return StageResult(rows_in=len(status), rows_out=len(status))


# ---- features -----------------------------------------------------------------------

_STUB_FEATURES = text("""
    SELECT fp.id AS forecast_point_id, o.pm25 AS pm25_lag_1h
    FROM forecast_points fp
    JOIN monitors m ON m.id = fp.monitor_id
    JOIN LATERAL (
        SELECT pm25 FROM observations
        WHERE monitor_id = m.id AND pm25 IS NOT NULL
          AND valid_at >= :t - interval '24 hours' AND valid_at < :t
        ORDER BY valid_at DESC LIMIT 1
    ) o ON TRUE
    WHERE fp.kind = 'monitor' AND fp.active
    ORDER BY fp.id
""")


def features_stub(ctx: StageContext) -> StageResult:
    """Fake features: the newest reading in the 24 h before issue time, per monitor."""
    frame = pd.read_sql(_STUB_FEATURES, ctx.session.connection(), params={"t": ctx.issued_at})
    frame.insert(1, "issued_at", pd.Timestamp(ctx.issued_at))
    if frame.empty:
        raise StageError("no monitor has a reading in the last 24 h")
    ctx.save("features", frame)
    return StageResult(rows_out=len(frame))


def features_real(ctx: StageContext) -> StageResult:
    """GEO-03 Stage A features. A stale FIRMS job skips the cycle (rather than
    forecasting as if there were no fires). A running job with no detection in the
    data-age window only warns: that reads as "no fires", like a quiet period."""
    from serving.geo import build_monitor_features

    firms = ingest_freshness(ctx.session).get("firms")
    fire_ok = firms is not None and not firms["stale"]
    if fire_ok:
        age, limit = firms["age_minutes"], max_data_age_minutes()["firms"]
        if age is None or age > limit:
            logger.warning(
                "pipeline run %s: no FIRMS detection in the last %s min; fire features read no fires",
                ctx.run_id, limit,
            )
    frame = build_monitor_features(
        ctx.issued_at, connection=ctx.session.connection(), fire_feed_available=fire_ok
    )
    if frame.empty:
        raise StageError("no monitor has a reading in the last 24 h")
    ctx.save("features", frame)
    return StageResult(rows_out=len(frame))


# ---- predict ------------------------------------------------------------------------


def ensure_stub_model(session: Session, model_key: str) -> None:
    """forecasts.model_key is a foreign key, so the stub model needs a row. It is
    'shadow' so it can never collide with the one production model."""
    name, version = model_key.split("/", 1)
    session.execute(
        text("""
            INSERT INTO model_versions (model_key, model_name, version, algorithm,
                artifact_uri, artifact_sha256, feature_list, status, notes)
            VALUES (:k, :n, :v, 'persistence', 'none:', 'none', '["pm25_lag_1h"]'::jsonb,
                'shadow', 'OPS-04 stub model: persistence of the newest reading')
            ON CONFLICT (model_key) DO NOTHING
        """),
        {"k": model_key, "n": name, "v": version},
    )


def predict_stub(ctx: StageContext) -> StageResult:
    """Persistence at every horizon, at each monitor point (Stage A)."""
    features = ctx.load("features")
    model_key = settings.STUB_MODEL_KEY
    ensure_stub_model(ctx.session, model_key)
    base = features[["forecast_point_id", "issued_at", "pm25_lag_1h"]]
    frames = []
    for h in HORIZONS:
        f = base.assign(horizon_hours=h)
        f["pm25_predicted"] = f.pop("pm25_lag_1h").astype(float).clip(lower=0)
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out["issued_at"] = pd.to_datetime(out["issued_at"], utc=True)
    out["target_time"] = out["issued_at"] + pd.to_timedelta(out["horizon_hours"], unit="h")
    out["source"] = "persistence"
    out["model_key"] = model_key
    out["nearest_monitor_dist_km"] = 0.0
    out = out.dropna(subset=["pm25_predicted"]).reset_index(drop=True)
    written = upsert_forecasts(ctx.session, out)
    ctx.session.commit()
    ctx.save("monitor_forecasts", out)
    return StageResult(rows_in=len(features), rows_out=written, model_key=model_key)


def load_service():
    """The production model's InferenceService (ML-04), built from the registry. A hook
    so tests can supply a fake; the registry itself is built here, so ml/ never imports app/."""
    from ml.inference.service import InferenceService
    from mlops.registry import build_registry

    return InferenceService.from_registry(build_registry(), name=settings.model_name())


def predict_real(ctx: StageContext) -> StageResult:
    """Stage A with the registry's production model (v2 or persistence per release.json).
    Needs the full feature frame, so use it with PIPELINE_FEATURES_STAGE=real."""
    features = ctx.load("features")
    out = load_service().predict(features)
    if out.empty:
        raise StageError("the model produced no forecasts (all inputs missing)")
    written = upsert_forecasts(ctx.session, out)
    ctx.session.commit()
    ctx.save("monitor_forecasts", out)
    return StageResult(rows_in=len(features), rows_out=written, model_key=str(out["model_key"].iloc[0]))


# ---- interpolate --------------------------------------------------------------------


def interpolate_idw(ctx: StageContext) -> StageResult:
    """GEO-03 Stage B: IDW of the monitor forecasts onto the grid cells."""
    from serving.geo import interpolate_to_grid

    monitor = ctx.load("monitor_forecasts")
    grid = interpolate_to_grid(monitor, connection=ctx.session.connection())
    written = upsert_forecasts(ctx.session, grid)
    ctx.session.commit()
    return StageResult(rows_in=len(monitor), rows_out=written)


# ---- registry -----------------------------------------------------------------------

BUILTIN: dict[str, dict[str, Stage]] = {
    "check_ingest": {"real": check_ingest},
    "features": {"stub": features_stub, "real": features_real},
    "predict": {"stub": predict_stub, "real": predict_real},
    "interpolate": {"real": interpolate_idw},
}
STAGE_ORDER = ("check_ingest", "features", "predict", "interpolate")


def resolve(stage: str) -> Stage:
    """The implementation chosen by PIPELINE_<STAGE>_STAGE."""
    if stage == "check_ingest":
        return check_ingest
    choice = settings.stage_choice(stage)
    if ":" in choice:
        module, _, attr = choice.partition(":")
        return getattr(importlib.import_module(module), attr)
    try:
        return BUILTIN[stage][choice]
    except KeyError:
        raise StageError(
            f"{stage}: unknown implementation '{choice}' (use {', '.join(BUILTIN[stage])} or module:callable)"
        ) from None

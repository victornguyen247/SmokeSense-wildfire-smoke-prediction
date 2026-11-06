"""pipeline_runs bookkeeping and the stage runner, independent of Celery.

The Celery tasks (pipeline/tasks.py) and the CLI (python -m pipeline) both call these.
Failures are logged at ERROR with the run id and stage, and stored on the run row; no
forecast is ever deleted, so the last good one stays served (see pipeline/status.py).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import PipelineRun
from ingestion.live.common import floor_hour, safe_error, utc_now
from pipeline import settings
from pipeline.stages import STAGE_ORDER, StageContext, resolve

logger = logging.getLogger("pipeline")

RETENTION_DAYS = 90
WORKDIR_KEEP_HOURS = 24


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def start_run(session_factory, issued_at: datetime | None = None, now: datetime | None = None) -> str:
    """Open a run for the hour containing `issued_at` (default: now) and return its id."""
    now = now or utc_now()
    hour = floor_hour(issued_at or now)
    if hour.tzinfo is None:
        raise ValueError("issued_at must be timezone-aware")
    with session_factory() as session:
        run = PipelineRun(issued_at=hour, started_at=now, status="running", stages={})
        session.add(run)
        session.commit()
        logger.info("pipeline run %s started for %s", run.id, _iso(hour))
        return run.id


def _set_stage(session: Session, run: PipelineRun, stage: str, **fields) -> None:
    stages = dict(run.stages or {})
    stages[stage] = {**stages.get(stage, {}), **fields}
    run.stages = stages  # reassign: JSONB mutations are not tracked in place
    session.commit()


def run_stage(session_factory, run_id: str, stage: str, attempt: int = 0) -> dict:
    """Run one stage of a run. Raises on failure so Celery can retry it; the failure
    is recorded on the run and logged at ERROR."""
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise LookupError(f"no pipeline run {run_id}")
        issued_at = run.issued_at
        started = utc_now()
        _set_stage(session, run, stage, status="running", started_at=_iso(started),
                   attempts=attempt + 1, error=None)
        try:
            result = resolve(stage)(StageContext(session, run_id, issued_at))
        except Exception as exc:
            session.rollback()
            error = safe_error(exc)
            run = session.get(PipelineRun, run_id)
            _set_stage(session, run, stage, status="failed", finished_at=_iso(utc_now()), error=error)
            logger.error("pipeline run %s stage %s failed (attempt %d): %s", run_id, stage, attempt + 1, error)
            raise
        run = session.get(PipelineRun, run_id)
        _set_stage(session, run, stage, status="success", finished_at=_iso(utc_now()),
                   rows_in=result.rows_in, rows_out=result.rows_out)
        if result.model_key:
            run.model_key = result.model_key
            session.commit()
        return {"stage": stage, "rows_in": result.rows_in, "rows_out": result.rows_out}


def finish_run(session_factory, run_id: str, now: datetime | None = None) -> None:
    """Mark the run successful and tidy up (old work files, 90-day-old run rows)."""
    now = now or utc_now()
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        run.status, run.finished_at = "success", now
        session.execute(delete(PipelineRun).where(PipelineRun.started_at < now - timedelta(days=RETENTION_DAYS)))
        session.commit()
        logger.info("pipeline run %s succeeded: %s", run_id, {k: v.get("rows_out") for k, v in run.stages.items()})
    clean_work_dir(run_id, now)


def fail_run(session_factory, run_id: str, now: datetime | None = None) -> None:
    """Mark the run failed, from the stage error already recorded. This is the alert:
    one ERROR line, plus status='failed' on the row, which /meta turns into 'stale'."""
    now = now or utc_now()
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        if run is None or run.status != "running":
            return
        failed = [(name, s.get("error")) for name, s in run.stages.items() if s.get("status") == "failed"]
        stage, error = failed[-1] if failed else ("unknown", "run did not finish")
        run.status, run.finished_at, run.error = "failed", now, f"{stage}: {error}"[:500]
        session.commit()
        logger.error("pipeline run %s FAILED at %s for %s: %s (last good forecast stays served)",
                     run_id, stage, _iso(run.issued_at), error)


def clean_work_dir(run_id: str, now: datetime) -> None:
    """Remove this run's frames, and any folder left by a failed run over a day ago."""
    root = settings.work_dir()
    shutil.rmtree(root / run_id, ignore_errors=True)
    if root.is_dir():
        cutoff = now.timestamp() - WORKDIR_KEEP_HOURS * 3600
        for d in root.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


def run_all(session_factory, issued_at: datetime | None = None, now: datetime | None = None) -> dict:
    """Whole pipeline in-process, no retries (CLI, tests). Never raises."""
    run_id = start_run(session_factory, issued_at, now)
    try:
        for stage in STAGE_ORDER:
            run_stage(session_factory, run_id, stage)
    except Exception:
        fail_run(session_factory, run_id, now)
    else:
        finish_run(session_factory, run_id, now)
    with session_factory() as session:
        run = session.get(PipelineRun, run_id)
        return {"run_id": run_id, "status": run.status, "error": run.error, "stages": run.stages}

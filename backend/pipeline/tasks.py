"""Celery tasks: a chain of one task per stage, so each stage retries on its own.

pipeline.hourly (beat) opens a run, then runs
  check_ingest -> features -> predict -> interpolate -> finish
Each stage task retries with backoff; once its retries are spent, pipeline.fail marks the
run failed and logs the ERROR, and the rest of the chain does not run.
"""

from __future__ import annotations

from datetime import datetime

from celery import chain

from ingestion.db import SessionLocal
from ingestion.tasks import celery_app
from pipeline import runner, settings
from pipeline.stages import STAGE_ORDER


def _stage_task(stage: str):
    @celery_app.task(
        bind=True,
        name=f"pipeline.stage.{stage}",
        autoretry_for=(Exception,),
        retry_backoff=settings.retry_backoff_seconds(),
        retry_backoff_max=180,
        max_retries=settings.max_retries(),
    )
    def task(self, run_id: str) -> dict:
        return runner.run_stage(SessionLocal, run_id, stage, attempt=self.request.retries)

    return task


STAGE_TASKS = {stage: _stage_task(stage) for stage in STAGE_ORDER}


@celery_app.task(name="pipeline.finish")
def finish(run_id: str) -> None:
    runner.finish_run(SessionLocal, run_id)


@celery_app.task(name="pipeline.fail")
def fail(*_args, run_id: str) -> None:
    runner.fail_run(SessionLocal, run_id)


@celery_app.task(name="pipeline.hourly")
def hourly(issued_at: str | None = None) -> dict:
    """Start one pipeline run. `issued_at` (ISO, UTC) re-runs a past hour: its forecasts
    are overwritten, not duplicated."""
    when = datetime.fromisoformat(issued_at.replace("Z", "+00:00")) if issued_at else None
    run_id = runner.start_run(SessionLocal, when)
    steps = [STAGE_TASKS[s].si(run_id) for s in STAGE_ORDER] + [finish.si(run_id)]
    chain(*steps).apply_async(link_error=fail.si(run_id=run_id))
    return {"run_id": run_id}

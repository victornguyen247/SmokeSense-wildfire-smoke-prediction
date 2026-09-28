"""Celery tasks for SmokeSense data ingestion.

DATA-02 POC:
- Pull FIRMS fire detections
- Pull AirNow PM2.5 observations
- Normalize the records
- Persist them to PostgreSQL/PostGIS
- Record ingestion results in ingestion_runs
"""

import os
from datetime import datetime, timezone

from celery import Celery

from app.core.config import settings
from app.models import IngestionRun

from ingestion.connectors.airnow import (
    DEFAULT_BBOX,
    DEFAULT_END_DATE,
    DEFAULT_END_HOUR,
    DEFAULT_START_DATE,
    DEFAULT_START_HOUR,
    fetch_airnow_rows,
    normalize_airnow_row,
)
from ingestion.connectors.firms import (
    get_firms_records,
)
from ingestion.db import (
    SessionLocal,
    insert_airnow_observations,
    insert_fire_detections,
)

celery_app = Celery(
    "smokesense",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

app = celery_app

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def create_ingestion_run(
    session,
    source: str,
    started_at: datetime,
) -> IngestionRun:
    """Create a new ingestion run record."""
    run = IngestionRun(
        source=source,
        started_at=started_at,
        status="running",
        rows_fetched=0,
        rows_written=0,
    )

    session.add(run)
    session.flush()

    return run


@celery_app.task(name="ingestion.firms_poc")
def ingest_firms_poc() -> dict:
    """Run the DATA-02 FIRMS ingestion POC."""

    started_at = utc_now()

    session = SessionLocal()

    run = None

    try:
        run = create_ingestion_run(
            session=session,
            source="firms",
            started_at=started_at,
        )

        map_key = settings.firms_map_key

        source = os.getenv(
            "FIRMS_SOURCE",
            "VIIRS_SNPP_NRT",
        )

        bbox = os.getenv(
            "FIRMS_BBOX",
            "-122.5,38.0,-120.5,39.5",
        )

        day_range = int(
            os.getenv("FIRMS_DAY_RANGE", "1")
        )

        start_date = (
            os.getenv("FIRMS_START_DATE")
            or None
        )

        records = get_firms_records(
            map_key=map_key,
            source=source,
            bbox=bbox,
            day_range=day_range,
            start_date=start_date,
        )

        run.rows_fetched = len(records)

        written = insert_fire_detections(
            session,
            records,
        )

        run.rows_written = written
        run.status = "success"
        run.finished_at = utc_now()

        session.commit()

        return {
            "source": "firms",
            "status": "success",
            "rows_fetched": len(records),
            "rows_written": written,
        }

    except Exception as exc:
        session.rollback()
        if run is not None:
            run.status = "failed"
            run.finished_at = utc_now()
            run.error = str(exc)
            session.commit()
        raise

    finally:
        session.close()


@celery_app.task(name="ingestion.airnow_poc")
def ingest_airnow_poc() -> dict:
    """Run the DATA-02 AirNow ingestion POC."""

    started_at = utc_now()

    session = SessionLocal()

    run = None

    try:
        # ingestion_runs uses "airdata" for AirNow/AirData ingestion.
        run = create_ingestion_run(
            session=session,
            source="airdata",
            started_at=started_at,
        )

        rows = fetch_airnow_rows(
            settings.airnow_api_key,
            bbox=os.getenv("AIRNOW_BBOX", DEFAULT_BBOX),
            start_date=os.getenv("AIRNOW_START_DATE", DEFAULT_START_DATE),
            start_hour=os.getenv("AIRNOW_START_HOUR", DEFAULT_START_HOUR),
            end_date=os.getenv("AIRNOW_END_DATE", DEFAULT_END_DATE),
            end_hour=os.getenv("AIRNOW_END_HOUR", DEFAULT_END_HOUR),
        )

        records = [
            record
            for row in rows
            if (record := normalize_airnow_row(row)) is not None
        ]

        run.rows_fetched = len(records)

        written = insert_airnow_observations(
            session,
            records,
        )

        run.rows_written = written
        run.status = "success"
        run.finished_at = utc_now()

        session.commit()

        return {
            "source": "airdata",
            "status": "success",
            "rows_fetched": len(records),
            "rows_written": written,
        }

    except Exception as exc:
        session.rollback()
        if run is not None:
            run.status = "failed"
            run.finished_at = utc_now()
            run.error = str(exc)
            session.commit()
        raise

    finally:
        session.close()


@celery_app.task(name="ingestion.health")
def health() -> dict[str, str]:
    return {"status": "ok"}
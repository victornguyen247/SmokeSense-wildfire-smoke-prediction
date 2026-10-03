"""Operations: ingestion_runs audit log (90-day retention) and
batch_ingestion_progress completion tracker (permanent)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.models.base import Base, one_of
from app.models.values import INGESTION_SOURCES, INGESTION_STATUSES


class IngestionRun(Base):
    """One row per Celery ingestion job. Freshness = now() - max(watermark) of successes."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        one_of("source", INGESTION_SOURCES),
        one_of("status", INGESTION_STATUSES),
        CheckConstraint("rows_fetched >= 0"),
        CheckConstraint("rows_written >= 0"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    source: Mapped[str]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]  # NULL while running
    status: Mapped[str] = mapped_column(server_default="running")
    rows_fetched: Mapped[int | None]
    rows_written: Mapped[int | None]
    watermark: Mapped[datetime | None]  # newest data timestamp seen this run
    raw_path: Mapped[str | None]
    error: Mapped[str | None]  # summary only — never raw stack traces


Index("ix_ingestion_source_started", IngestionRun.source, IngestionRun.started_at.desc())
Index("ix_ingestion_status_started", IngestionRun.status, IngestionRun.started_at.desc())


class BatchIngestionProgress(Base):
    """Durable completion tracker for DATA-03 batch ingestion.

    One row per (pilot_event_id, source) pair, upserted in place as the
    source moves through running -> success/partial/failed. Unlike
    ingestion_runs (a 90-day audit log, one row per Celery job execution),
    this table never expires and never accumulates history -- it only
    ever answers "is this event/source pair done, right now."

    "partial" is reserved but not yet set by any code path -- no source
    currently models a partial-row-count outcome (e.g. an insert that
    fails halfway through a batch). Left in the schema deliberately for
    when that's needed, rather than added prematurely before a real use
    case exists.
    """

    __tablename__ = "batch_ingestion_progress"
    __table_args__ = (
        CheckConstraint(
            "source IN ('firms', 'airnow', 'ncei', 'purpleair')",
            name="ck_batch_progress_source",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_batch_progress_status",
        ),
        CheckConstraint(
            "rows_fetched IS NULL OR rows_fetched >= 0",
            name="ck_batch_progress_rows_fetched",
        ),
        CheckConstraint(
            "rows_written IS NULL OR rows_written >= 0",
            name="ck_batch_progress_rows_written",
        ),
        UniqueConstraint(
            "pilot_event_id", "source", name="uq_batch_progress_event_source"
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    pilot_event_id: Mapped[str] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(nullable=False, default="running")
    rows_fetched: Mapped[int | None] = mapped_column(default=None)
    rows_written: Mapped[int | None] = mapped_column(default=None)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=func.now()
    )


Index(
    "ix_batch_progress_event_source",
    BatchIngestionProgress.pilot_event_id,
    BatchIngestionProgress.source,
    BatchIngestionProgress.status,
)

"""Operations: ingestion_runs audit log (90-day retention)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index
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

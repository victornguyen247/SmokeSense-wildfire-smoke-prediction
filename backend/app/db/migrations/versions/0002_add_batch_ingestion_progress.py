"""Add batch_ingestion_progress table for DATA-03 event-level resumability

ingestion_runs (from DATA-02) is a 90-day rolling audit log built to power
a "data freshness" dashboard badge -- rows expire and get deleted. Batch
ingestion needs the opposite property: durable, permanent knowledge of
whether a given (pilot_event, source) pair has already been fully ingested,
so a --resume run doesn't re-pull data (and re-burn API quota) for events
that were already done weeks ago.

This is a separate, purpose-built table rather than adding columns to
ingestion_runs, to avoid conflating a freshness log with a completion
tracker -- two genuinely different concerns with different retention needs.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_ingestion_progress",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("pilot_event_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("rows_fetched", sa.Integer(), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IN ('firms', 'airnow', 'ncei', 'purpleair')",
            name="ck_batch_progress_source",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_batch_progress_status",
        ),
        sa.CheckConstraint(
            "rows_fetched IS NULL OR rows_fetched >= 0",
            name="ck_batch_progress_rows_fetched",
        ),
        sa.CheckConstraint(
            "rows_written IS NULL OR rows_written >= 0",
            name="ck_batch_progress_rows_written",
        ),
        sa.UniqueConstraint(
            "pilot_event_id", "source", name="uq_batch_progress_event_source"
        ),
    )
    op.create_index(
        "ix_batch_progress_event_source",
        "batch_ingestion_progress",
        ["pilot_event_id", "source", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_batch_progress_event_source", table_name="batch_ingestion_progress")
    op.drop_table("batch_ingestion_progress")

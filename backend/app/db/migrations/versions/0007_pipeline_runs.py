"""pipeline_runs: audit log of the hourly forecast pipeline (OPS-04)

One row per run: the forecast hour, start/end, status, the model that produced the
monitor forecasts and per-stage row counts. /meta derives forecast staleness from the
newest successful row, so a failed run never hides the last good forecast.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("model_key", sa.Text()),
        sa.Column("stages", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name="ck_pipeline_runs_status"),
    )
    op.create_index("ix_pipeline_runs_status_issued", "pipeline_runs", ["status", "issued_at"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_status_issued", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")

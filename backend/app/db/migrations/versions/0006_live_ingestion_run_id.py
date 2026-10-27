"""Mark live rows: ingestion_run_id on observations, fire_detections, weather_observations

DATA-06 keeps a rolling ~72 h window of live data, but the same tables also hold the
DATA-03 pilot-event rows that smokesense_v1 is built from, and those must never be
deleted. Nothing told the two apart: the batch writes no ingestion_runs row and its
timestamps can be anywhere in the past.

Live jobs now write the id of their ingestion_runs row here; batch rows keep NULL.
Retention deletes only rows with a non-NULL id, and live upserts never modify a row
whose id is NULL. No foreign key: ingestion_runs is pruned after 90 days, and an
ON DELETE SET NULL would turn old live rows into "historical" ones that are never
deleted. Nullable with no default, so on the partitioned parents this is a catalog-only
change that every partition inherits.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

LIVE_TABLES = ("observations", "fire_detections", "weather_observations")


def upgrade() -> None:
    for table in LIVE_TABLES:
        op.add_column(table, sa.Column("ingestion_run_id", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in LIVE_TABLES:
        op.drop_column(table, "ingestion_run_id")

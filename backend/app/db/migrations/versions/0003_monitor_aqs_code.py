"""Add monitors.aqs_code: the AirNow site's normalized 9-character AQS code

AirNow monitors are keyed by external_id = stable_external_id("airnow", code), a hash, so
the AQS code itself was not queryable. DATA-04 needs it for the California scope
(app/core/scope.py), so it is stored alongside. Nullable: PurpleAir monitors have none,
and existing AirNow rows are filled by backend/scripts/backfill_monitor_aqs_code.py.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("aqs_code", sa.String(9), nullable=True))
    op.create_index("ix_monitors_aqs_code", "monitors", ["aqs_code"])


def downgrade() -> None:
    op.drop_index("ix_monitors_aqs_code", table_name="monitors")
    op.drop_column("monitors", "aqs_code")

"""Indexes for the API-02 forecast reads.

ix_forecasts_serving finds a model's newest public cycle and reads that cycle's rows
without scanning 30 days of forecasts. ix_forecast_points_cell_geom_planar serves bbox
filters: a bbox is a lon/lat rectangle, but the edges of a geography polygon are great
circles, which would drop cells along the bbox's southern edge.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_forecasts_serving ON forecasts (model_key, issued_at DESC) "
        "WHERE NOT is_shadow"
    )
    op.execute(
        "CREATE INDEX ix_forecast_points_cell_geom_planar "
        "ON forecast_points USING gist ((cell_geom::geometry))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_forecast_points_cell_geom_planar")
    op.execute("DROP INDEX ix_forecasts_serving")

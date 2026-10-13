"""Serving-contract schema delta (PM-03, docs/ml/serving-contract.md)

Stage A of the serving pipeline forecasts at AirNow monitors; Stage B interpolates
those forecasts to grid cells. The schema needs three things it did not have:

1. forecast_points.kind = 'monitor', with forecast_points.monitor_id -> monitors(id).
   'grid_cell' is kept as is (no rename). Grid cells carry their polygon in cell_geom
   (populated by GEO-02); geom stays the cell centroid the model and IDW use.
2. forecasts.source: how the value was produced -- 'v2', 'persistence' or 'fallback'
   (Stage A, ml.inference.predict_v2) or 'idw' (Stage B).
3. forecasts.nearest_monitor_dist_km may be 0: a monitor forecast point is its own
   nearest monitor (the CHECK was > 0).

forecasts is written only by OPS-04, which does not exist yet, so source is added NOT
NULL without a default. If this fails on a database that already has forecasts rows,
decide their source by hand first.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE forecast_points DROP CONSTRAINT forecast_points_kind_check")
    op.execute("""
        ALTER TABLE forecast_points
            ADD CONSTRAINT forecast_points_kind_check
            CHECK (kind IN ('city','zip','grid_cell','adhoc','monitor'))
    """)
    op.execute("ALTER TABLE forecast_points ADD COLUMN monitor_id TEXT REFERENCES monitors(id)")
    op.execute("ALTER TABLE forecast_points ADD COLUMN cell_geom GEOGRAPHY(POLYGON, 4326)")
    op.execute("""
        ALTER TABLE forecast_points
            ADD CONSTRAINT forecast_points_monitor_id_check
            CHECK ((kind = 'monitor') = (monitor_id IS NOT NULL))
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_forecast_points_monitor_id
            ON forecast_points (monitor_id) WHERE monitor_id IS NOT NULL
    """)
    op.execute("CREATE INDEX ix_forecast_points_cell_geom ON forecast_points USING gist (cell_geom)")

    op.execute("ALTER TABLE forecasts ADD COLUMN source TEXT NOT NULL")
    op.execute("""
        ALTER TABLE forecasts
            ADD CONSTRAINT forecasts_source_check
            CHECK (source IN ('v2','persistence','fallback','idw'))
    """)
    op.execute("ALTER TABLE forecasts DROP CONSTRAINT forecasts_nearest_monitor_dist_km_check")
    op.execute("""
        ALTER TABLE forecasts
            ADD CONSTRAINT forecasts_nearest_monitor_dist_km_check
            CHECK (nearest_monitor_dist_km >= 0)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE forecasts DROP CONSTRAINT forecasts_nearest_monitor_dist_km_check")
    op.execute("""
        ALTER TABLE forecasts
            ADD CONSTRAINT forecasts_nearest_monitor_dist_km_check
            CHECK (nearest_monitor_dist_km > 0)
    """)
    op.execute("ALTER TABLE forecasts DROP CONSTRAINT forecasts_source_check")
    op.execute("ALTER TABLE forecasts DROP COLUMN source")

    op.execute("DROP INDEX ix_forecast_points_cell_geom")
    op.execute("DROP INDEX ux_forecast_points_monitor_id")
    op.execute("ALTER TABLE forecast_points DROP CONSTRAINT forecast_points_monitor_id_check")
    op.execute("ALTER TABLE forecast_points DROP COLUMN cell_geom")
    op.execute("ALTER TABLE forecast_points DROP COLUMN monitor_id")
    op.execute("ALTER TABLE forecast_points DROP CONSTRAINT forecast_points_kind_check")
    op.execute("""
        ALTER TABLE forecast_points
            ADD CONSTRAINT forecast_points_kind_check
            CHECK (kind IN ('city','zip','grid_cell','adhoc'))
    """)

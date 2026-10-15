"""Add indexed California grid point and ZIP centroid lookup.

PM-03 creates the forecast-point kind, monitor link, and cell polygon column.
GEO-02 only adds the lookup function that uses that schema.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION lookup_grid_forecast_point(
            p_longitude DOUBLE PRECISION,
            p_latitude DOUBLE PRECISION
        ) RETURNS TABLE (forecast_point_id TEXT)
        LANGUAGE SQL STABLE STRICT AS $$
            WITH query_point AS (
                SELECT ST_SetSRID(
                    ST_MakePoint(p_longitude, p_latitude), 4326
                )::geography AS geog
            )
            SELECT fp.id AS forecast_point_id
            FROM forecast_points AS fp
            CROSS JOIN query_point AS qp
            WHERE fp.kind = 'grid_cell'
              AND fp.active
              AND ST_Covers(fp.cell_geom, qp.geog)
            ORDER BY fp.id
            LIMIT 1
        $$
    """)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS lookup_grid_forecast_point("
        "DOUBLE PRECISION, DOUBLE PRECISION)"
    )

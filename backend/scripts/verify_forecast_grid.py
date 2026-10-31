"""Verify the seeded grid against real PostGIS (no persistent writes).

Run from backend: python scripts/verify_forecast_grid.py
Uses cached TIGER state data, or --state-file for an offline archive.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from pyproj import Transformer
from shapely import segmentize
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.geo import PROJECTED_EPSG, TIGER_VINTAGE  # noqa: E402
from app.db.seed_ca_forecast_grid import _read_california_boundary  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(tempfile.gettempdir())
        / f"smokesense-tiger-{TIGER_VINTAGE}"
        / f"tl_{TIGER_VINTAGE}_us_state.zip",
    )
    args = parser.parse_args()
    _, boundary = _read_california_boundary(args.state_file)
    transform = Transformer.from_crs(PROJECTED_EPSG, 4326, always_xy=True).transform
    # Coastal/state-border points one metre inside the original Albers boundary.
    inner = segmentize(boundary.buffer(-1).boundary, 1000)
    coastal_points = []
    for line in getattr(inner, "geoms", [inner]):
        coastal_points.extend(transform(x, y) for x, y in line.coords)

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        try:
            counts = (
                connection.execute(
                    text("""
                SELECT
                    (SELECT count(*) FROM forecast_points
                     WHERE kind = 'grid_cell' AND active) AS cells,
                    count(*) AS zctas, count(forecast_point_id) AS mapped
                FROM zip_codes WHERE state = 'CA'
            """)
                )
                .mappings()
                .one()
            )
            print(json.dumps(dict(counts)))
            assert 0 < counts["cells"] <= 3000, counts
            assert counts["zctas"] > 0 and counts["zctas"] == counts["mapped"], counts
            connection.execute(
                text("""
                CREATE TEMP TABLE grid_verification_samples (
                    category TEXT NOT NULL, geom GEOMETRY(POINT, 4326) NOT NULL
                ) ON COMMIT DROP
            """)
            )
            # Segmentize geography, not geometry: points follow the actual
            # stored geodesic edges, including shared edges and all vertices.
            connection.execute(
                text("""
                INSERT INTO grid_verification_samples
                SELECT 'stored_edge_vertex', (point).geom
                FROM forecast_points fp
                CROSS JOIN LATERAL ST_DumpPoints(
                    ST_Segmentize(fp.cell_geom, 1000)::geometry
                ) point
                WHERE kind = 'grid_cell' AND active
            """)
            )
            connection.execute(
                text("""
                INSERT INTO grid_verification_samples
                SELECT 'cell_interior', ST_PointOnSurface(cell_geom::geometry)
                FROM forecast_points WHERE kind = 'grid_cell' AND active
                UNION ALL
                SELECT 'zcta', geom::geometry FROM zip_codes WHERE state = 'CA'
            """)
            )
            connection.execute(
                text("""
                    INSERT INTO grid_verification_samples VALUES (
                        'state_border_inside_1m', ST_SetSRID(ST_MakePoint(:x, :y),4326)
                    )
                """),
                [{"x": x, "y": y} for x, y in coastal_points],
            )
            results = (
                connection.execute(
                    text("""
                SELECT category, count(*) AS samples,
                       count(*) FILTER (WHERE actual.id IS NULL) AS missing,
                       count(*) FILTER (WHERE actual.id IS DISTINCT FROM expected.id)
                           AS wrong_tiebreak,
                       count(*) FILTER (WHERE expected.matches > 1) AS shared_boundary
                FROM grid_verification_samples s
                LEFT JOIN LATERAL (
                    SELECT forecast_point_id AS id FROM lookup_grid_forecast_point(
                        ST_X(s.geom), ST_Y(s.geom)
                    )
                ) actual ON TRUE
                LEFT JOIN LATERAL (
                    SELECT min(id) AS id, count(*) AS matches FROM forecast_points fp
                    WHERE fp.kind = 'grid_cell' AND fp.active
                      AND ST_Covers(fp.cell_geom, s.geom::geography)
                ) expected ON TRUE
                GROUP BY category ORDER BY category
            """)
                )
                .mappings()
                .all()
            )
            for result in results:
                print(json.dumps(dict(result)))
            assert all(
                r["missing"] == r["wrong_tiebreak"] == 0 for r in results
            ), results
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM lookup_grid_forecast_point(0,0)
            """)
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("""
                SELECT count(*) FROM lookup_grid_forecast_point(NULL,38)
            """)
                ).scalar_one()
                == 0
            )
            plan = connection.execute(
                text("""
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT * FROM lookup_grid_forecast_point(-121.4944,38.5816)
            """)
            ).scalar_one()
            print(json.dumps(plan, indent=2))
            # STRICT SQL table functions are not necessarily inlined. EXPLAIN
            # their exact stored body as well, to expose the access path.
            body = connection.execute(
                text("""
                SELECT prosrc FROM pg_proc WHERE oid =
                'lookup_grid_forecast_point(double precision,double precision)'::regprocedure
            """)
            ).scalar_one()
            body = body.replace("p_longitude", ":longitude").replace(
                "p_latitude", ":latitude"
            )
            body_plan = connection.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + body),
                {"longitude": -121.4944, "latitude": 38.5816},
            ).scalar_one()
            print(json.dumps({"stored_function_body_plan": body_plan}, indent=2))
            assert "ix_forecast_points_cell_geom" in json.dumps(body_plan), body_plan
            durations = []
            for _ in range(100):
                start = time.perf_counter()
                connection.execute(
                    text("""
                    SELECT * FROM lookup_grid_forecast_point(-121.4944,38.5816)
                """)
                ).all()
                durations.append((time.perf_counter() - start) * 1000)
            print(
                json.dumps(
                    {
                        "lookup_median_ms": sorted(durations)[50],
                        "lookup_max_ms": max(durations),
                    }
                )
            )
            assert max(durations) < 50, durations
        finally:
            connection.rollback()


if __name__ == "__main__":
    main()

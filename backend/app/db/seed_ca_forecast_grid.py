"""Generate and seed California grid cells and Census ZCTA internal-point mappings.

Run in the backend environment:
    python -m app.db.seed_ca_forecast_grid

The 2025 TIGER/Line ZCTA archive is national and about 505 MB. The script
caches source archives under the OS temporary directory; --state-file and
--zcta-file allow pre-downloaded TIGER files to be used instead.
"""

from __future__ import annotations

import argparse
import logging
import math
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import httpx
from pyproj import Transformer
from shapely import make_valid, to_wkb
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from sqlalchemy import bindparam, create_engine, text

from app.core.geo import (
    DEFAULT_CELL_SIZE_M,
    PROJECTED_EPSG,
    TIGER_VINTAGE,
    california_grid_key,
)
from app.core.scope import CA_TRIBAL_SITES

LOGGER = logging.getLogger("smokesense.grid_seed")
GEOGRAPHIC_CRS = "EPSG:4326"
PROJECTED_CRS = f"EPSG:{PROJECTED_EPSG}"
TIMEZONE = "America/Los_Angeles"
STATE_URL = (
    f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/STATE/"
    f"tl_{TIGER_VINTAGE}_us_state.zip"
)
ZCTA_URL = (
    f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/ZCTA520/"
    f"tl_{TIGER_VINTAGE}_us_zcta520.zip"
)

GRID_INSERT = text("""
    INSERT INTO forecast_points (
        id, kind, label, h3_cell, city_id, monitor_id, geom, cell_geom,
        timezone, always_forecast, active
    ) VALUES (
        :id, 'grid_cell', :label, NULL, NULL, NULL,
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
        ST_GeomFromWKB(:cell_wkb, 4326)::geography,
        :timezone, TRUE, TRUE
    )
    ON CONFLICT (id) DO UPDATE SET
        kind = EXCLUDED.kind,
        label = EXCLUDED.label,
        h3_cell = NULL,
        city_id = NULL,
        monitor_id = NULL,
        geom = EXCLUDED.geom,
        cell_geom = EXCLUDED.cell_geom,
        timezone = EXCLUDED.timezone,
        always_forecast = TRUE,
        active = TRUE
""")

ZIP_INSERT = text("""
    INSERT INTO zip_codes (zcta, state, geom, area_km2, forecast_point_id)
    VALUES (
        :zcta, 'CA',
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
        :area_km2, NULL
    )
    ON CONFLICT (zcta) DO UPDATE SET
        state = EXCLUDED.state,
        geom = EXCLUDED.geom,
        area_km2 = EXCLUDED.area_km2
""")

ZIP_MAP = text("""
    UPDATE zip_codes AS z
    SET forecast_point_id = (
        SELECT match.forecast_point_id
        FROM lookup_grid_forecast_point(
            ST_X(z.geom::geometry), ST_Y(z.geom::geometry)
        ) AS match
    )
    WHERE z.zcta IN :zcta_ids
""").bindparams(bindparam("zcta_ids", expanding=True))


def _download(url: str, data_dir: Path) -> Path:
    """Download a Census archive once, keeping incomplete files out of cache."""
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / url.rsplit("/", 1)[-1]
    if destination.exists() and destination.stat().st_size:
        return destination

    partial = destination.with_suffix(destination.suffix + ".part")
    LOGGER.info("Downloading %s", url)
    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=httpx.Timeout(180.0, connect=30.0),
        headers={"User-Agent": "SmokeSense/1.0 (California forecast grid seed)"},
    ) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                output.write(chunk)
    partial.replace(destination)
    LOGGER.info("Cached %s (%0.1f MB)", destination, destination.stat().st_size / 1e6)
    return destination


def _read_california_boundary(state_file: Path) -> tuple[Any, Any]:
    states = gpd.read_file(state_file)
    if "STATEFP" not in states.columns:
        raise ValueError(f"{state_file} has no STATEFP column")
    california = states.loc[states["STATEFP"].astype(str).str.zfill(2) == "06"]
    if california.empty:
        raise ValueError(f"No California state boundary found in {state_file}")

    state_wgs84 = make_valid(unary_union(california.to_crs(GEOGRAPHIC_CRS).geometry))
    state_projected = make_valid(unary_union(california.to_crs(PROJECTED_CRS).geometry))
    if state_projected.is_empty or state_projected.area <= 0:
        raise ValueError("California boundary is empty after projection")
    return state_wgs84, state_projected


def _polygon_parts(geometry: Any) -> list[Polygon]:
    geometry = make_valid(geometry)
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for item in geometry.geoms:
            parts.extend(_polygon_parts(item))
        return parts
    return []


def generate_grid(
    state_projected: Any, cell_size_m: int
) -> tuple[list[dict[str, Any]], float]:
    if cell_size_m <= 0:
        raise ValueError("Cell size must be a positive number of meters")

    min_x, min_y, max_x, max_y = state_projected.bounds
    first_col = math.floor(min_x / cell_size_m)
    last_col = math.ceil(max_x / cell_size_m)
    first_row = math.floor(min_y / cell_size_m)
    last_row = math.ceil(max_y / cell_size_m)
    rows: list[dict[str, Any]] = []
    projected_geometries: list[Polygon] = []
    grid_prefix = f"grid-ca-epsg{PROJECTED_EPSG}-{cell_size_m}m"

    for row in range(first_row, last_row):
        for col in range(first_col, last_col):
            square = box(
                col * cell_size_m,
                row * cell_size_m,
                (col + 1) * cell_size_m,
                (row + 1) * cell_size_m,
            )
            parts = [
                orient(part, sign=1.0)
                for part in _polygon_parts(square.intersection(state_projected))
                if part.area > 0
            ]
            if not parts:
                continue
            parts = sorted(parts, key=lambda part: (part.bounds, part.wkb))
            for part_number, part in enumerate(parts):
                centroid = part.centroid
                rows.append(
                    {
                        "id": (
                            f"{grid_prefix}-r{row:+07d}-c{col:+07d}"
                            f"-p{part_number:02d}"
                        ),
                        "label": (
                            f"California grid r{row} c{col}"
                            if len(parts) == 1
                            else f"California grid r{row} c{col} part {part_number + 1}"
                        ),
                        "center_x": centroid.x,
                        "center_y": centroid.y,
                    }
                )
                projected_geometries.append(part)

    if not rows:
        raise ValueError("Grid generation produced no California cells")

    # Verify the clipped, non-overlapping squares cover the complete boundary.
    covered = unary_union(projected_geometries)
    uncovered_area_m2 = state_projected.symmetric_difference(covered).area
    tolerance_m2 = max(1.0, state_projected.area * 1e-10)
    if uncovered_area_m2 > tolerance_m2:
        raise ValueError(
            "Generated grid does not cover California boundary: "
            f"{uncovered_area_m2:,.2f} m^2 gap/overlap"
        )

    grid_wgs84 = gpd.GeoSeries(projected_geometries, crs=PROJECTED_CRS).to_crs(
        GEOGRAPHIC_CRS
    )
    to_wgs84 = Transformer.from_crs(
        PROJECTED_CRS, GEOGRAPHIC_CRS, always_xy=True
    ).transform
    cells: list[dict[str, Any]] = []
    for row, polygon in zip(rows, grid_wgs84, strict=True):
        longitude, latitude = to_wgs84(row.pop("center_x"), row.pop("center_y"))
        cells.append(
            {
                **row,
                "longitude": longitude,
                "latitude": latitude,
                "cell_wkb": to_wkb(polygon, output_dimension=2),
                "timezone": TIMEZONE,
            }
        )
    return cells, uncovered_area_m2


def _zcta_key_column(frame: gpd.GeoDataFrame) -> str:
    for column in ("ZCTA5CE20", "ZCTA5CE", "GEOID20", "GEOID"):
        if column in frame.columns:
            return column
    raise ValueError("Could not find a Census ZCTA GEOID column")


def _zcta_internal_point_columns(frame: gpd.GeoDataFrame) -> tuple[str, str]:
    for latitude, longitude in (
        ("INTPTLAT20", "INTPTLON20"),
        ("INTPTLAT", "INTPTLON"),
    ):
        if latitude in frame.columns and longitude in frame.columns:
            return latitude, longitude
    raise ValueError("Could not find Census ZCTA internal-point coordinates")


def generate_zcta_internal_points(
    zcta_file: Path, state_wgs84: Any
) -> list[dict[str, Any]]:
    # Read only ZCTAs whose bounding boxes meet California instead of keeping
    # the full national shapefile in memory.
    zctas = gpd.read_file(zcta_file, bbox=state_wgs84.bounds)
    if zctas.empty:
        raise ValueError("No ZCTAs intersect the California bounding box")
    key_column = _zcta_key_column(zctas)
    latitude_column, longitude_column = _zcta_internal_point_columns(zctas)
    if zctas.crs is None:
        raise ValueError("Census ZCTA input has no declared CRS")

    zctas_wgs84 = zctas.to_crs(GEOGRAPHIC_CRS)
    intersects_state = zctas_wgs84.geometry.intersects(state_wgs84)
    candidates = zctas_wgs84.loc[intersects_state].copy()
    candidates = candidates.to_crs(PROJECTED_CRS)

    records = []
    for _, zcta in candidates.iterrows():
        geometry = make_valid(zcta.geometry)
        longitude = float(zcta[longitude_column])
        latitude = float(zcta[latitude_column])
        census_point = Point(longitude, latitude)
        # Use the internal point shipped with TIGER/Line and include ZCTAs
        # whose Census point falls inside the supported California boundary.
        if not state_wgs84.covers(census_point):
            continue
        zcta_id = str(zcta[key_column]).strip().zfill(5)
        records.append(
            {
                "zcta": zcta_id,
                "longitude": longitude,
                "latitude": latitude,
                "area_km2": geometry.area / 1_000_000,
            }
        )

    records.sort(key=lambda item: item["zcta"])
    if not records:
        raise ValueError("No ZCTA internal points fall within California")
    return records


def sync_monitor_forecast_points(connection: Any) -> None:
    connection.execute(
        text("""
        UPDATE forecast_points SET active = FALSE
        WHERE kind = 'monitor'
    """)
    )
    connection.execute(
        text("""
        INSERT INTO forecast_points (
            id, kind, label, h3_cell, city_id, monitor_id, geom, cell_geom,
            timezone, always_forecast, active
        )
        SELECT
            m.external_id, 'monitor',
            COALESCE(NULLIF(m.name, ''), m.external_id),
            NULL, NULL, m.id, m.geom, NULL,
            COALESCE(c.timezone, :default_timezone), TRUE, TRUE
        FROM monitors AS m
        LEFT JOIN cities AS c ON c.id = m.city_id
        WHERE m.source = 'airnow'
          AND m.active
          AND m.location_type = 'outdoor'
          AND (
              replace(m.aqs_code, '-', '') LIKE '06%'
              OR replace(m.aqs_code, '-', '') IN :tribal_codes
          )
          AND EXISTS (
              SELECT 1 FROM observations AS o
              WHERE o.monitor_id = m.id
                AND o.correction = 'regulatory'
                AND o.valid_at >= now() - interval '24 hours'
                AND o.valid_at <= now()
          )
        ON CONFLICT (monitor_id) WHERE monitor_id IS NOT NULL DO UPDATE SET
            kind = EXCLUDED.kind,
            label = EXCLUDED.label,
            geom = EXCLUDED.geom,
            timezone = EXCLUDED.timezone,
            always_forecast = EXCLUDED.always_forecast,
            active = EXCLUDED.active
    """).bindparams(bindparam("tribal_codes", expanding=True)),
        {
            "default_timezone": TIMEZONE,
            "tribal_codes": list(CA_TRIBAL_SITES),
        },
    )


def seed(
    cells: list[dict[str, Any]],
    zctas: list[dict[str, Any]],
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    ids = [zcta["zcta"] for zcta in zctas]
    try:
        with engine.begin() as connection:
            # Retire legacy H3 grid rows and prior California cell sizes before
            # upserting this configuration. Other forecast points are untouched.
            connection.execute(
                text("""
                UPDATE forecast_points
                SET active = FALSE
                WHERE kind = 'grid_cell' AND cell_geom IS NULL
            """)
            )
            connection.execute(
                text("""
                UPDATE forecast_points
                SET active = FALSE
                WHERE kind = 'grid_cell' AND id LIKE 'grid-ca-epsg%'
            """)
            )
            connection.execute(GRID_INSERT, cells)
            connection.execute(ZIP_INSERT, zctas)
            connection.execute(ZIP_MAP, {"zcta_ids": ids})
            missing = (
                connection.execute(
                    text("""
                    SELECT zcta FROM zip_codes
                    WHERE zcta IN :zcta_ids AND forecast_point_id IS NULL
                    ORDER BY zcta
                """).bindparams(bindparam("zcta_ids", expanding=True)),
                    {"zcta_ids": ids},
                )
                .scalars()
                .all()
            )
            if missing:
                examples = ", ".join(missing[:10])
                raise RuntimeError(
                    f"{len(missing)} California ZCTAs did not map to a grid cell: "
                    f"{examples}"
                )
            sync_monitor_forecast_points(connection)
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    from app.core.config import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell-size-m", type=int, default=DEFAULT_CELL_SIZE_M)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--zcta-file", type=Path)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / f"smokesense-tiger-{TIGER_VINTAGE}",
    )
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and report grid/ZCTA counts without writing to PostGIS.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    state_file = args.state_file or _download(STATE_URL, args.data_dir)
    zcta_file = args.zcta_file or _download(ZCTA_URL, args.data_dir)
    state_wgs84, state_projected = _read_california_boundary(state_file)
    cells, uncovered_area_m2 = generate_grid(state_projected, args.cell_size_m)
    zctas = generate_zcta_internal_points(zcta_file, state_wgs84)

    LOGGER.info(
        "TIGER %s; EPSG:%s; cell size %s m; grid key %s; "
        "grid cells %s; California ZCTA internal points %s",
        TIGER_VINTAGE,
        PROJECTED_EPSG,
        args.cell_size_m,
        california_grid_key(args.cell_size_m),
        len(cells),
        len(zctas),
    )
    polygon_payload_bytes = sum(len(cell["cell_wkb"]) for cell in cells)
    LOGGER.info(
        "Grid polygon payload: %.2f MiB of WKB before database page compression",
        polygon_payload_bytes / (1024 * 1024),
    )
    LOGGER.info("Grid coverage symmetric-difference area: %.6f m^2", uncovered_area_m2)
    if args.dry_run:
        LOGGER.info("Dry run complete; PostGIS was not changed.")
        return

    seed(cells, zctas, args.database_url)
    LOGGER.info(
        "Seeded %s grid cells and mapped %s ZCTAs; synchronized eligible monitor points.",
        len(cells),
        len(zctas),
    )


if __name__ == "__main__":
    main()

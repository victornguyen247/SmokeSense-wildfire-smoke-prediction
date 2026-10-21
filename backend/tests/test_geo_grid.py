from pathlib import Path

import geopandas as gpd
import pytest
from shapely import from_wkb
from shapely.geometry import MultiPolygon, box

from app.core.geo import california_grid_key
from app.core.scope import in_california_scope
from app.db.seed_ca_forecast_grid import (
    generate_grid,
    generate_zcta_internal_points,
)
from ingestion.connectors.airnow import normalize_aqs_code


def test_grid_splits_disconnected_clipped_parts_with_stable_polygon_ids():
    california_piece = MultiPolygon(
        [box(1_000, 1_000, 2_000, 2_000), box(3_000, 1_000, 4_000, 2_000)]
    )

    first_run, uncovered_area = generate_grid(california_piece, 12_500)
    second_run, _ = generate_grid(california_piece, 12_500)

    assert uncovered_area == 0
    assert [cell["id"] for cell in first_run] == [cell["id"] for cell in second_run]
    assert [cell["id"].rsplit("-", 1)[-1] for cell in first_run] == ["p00", "p01"]
    assert all(cell["id"].startswith(california_grid_key() + "-") for cell in first_run)
    assert all(from_wkb(cell["cell_wkb"]).geom_type == "Polygon" for cell in first_run)


def test_california_grid_key_encodes_grid_configuration_and_tiger_vintage():
    assert california_grid_key() == "grid-ca-epsg3310-12500m-tiger2025"
    assert california_grid_key(10_000) == "grid-ca-epsg3310-10000m-tiger2025"
    with pytest.raises(ValueError, match="positive"):
        california_grid_key(0)


@pytest.mark.parametrize("source_crs", ["EPSG:4326", "EPSG:3310"])
def test_zcta_lookup_uses_census_internal_point(monkeypatch, caplog, source_crs):
    zctas = gpd.GeoDataFrame(
        {
            "GEOID20": ["06001", "97001"],
            "INTPTLAT20": ["38.25000", "41.00000"],
            "INTPTLON20": ["-122.75000", "-122.75000"],
        },
        geometry=[box(-122.1, 37.5, -121.1, 38.5), box(-123, 39.5, -122, 41.5)],
        crs="EPSG:4326",
    ).to_crs(source_crs)
    reads = []

    def read_file(_path, **kwargs):
        reads.append(kwargs)
        return zctas

    monkeypatch.setattr(
        "app.db.seed_ca_forecast_grid.gpd.read_file",
        read_file,
    )

    with caplog.at_level("INFO", logger="smokesense.grid_seed"):
        result = generate_zcta_internal_points(
            Path("unused-zctas.shp"), box(-123, 36, -120, 40)
        )

    assert len(result) == 1
    assert result[0]["zcta"] == "06001"
    assert result[0]["longitude"] == -122.75
    assert result[0]["latitude"] == 38.25
    assert "97001" in caplog.text
    assert "1 excluded" in caplog.text
    assert reads[0] == {"rows": 0}
    expected_bounds = (
        gpd.GeoSeries([box(-123, 36, -120, 40)], crs=4326)
        .to_crs(source_crs)
        .total_bounds
    )
    assert reads[1]["bbox"] == pytest.approx(expected_bounds)


def test_aqs_normalization_and_california_scope():
    assert normalize_aqs_code("840060072003") == "060072003"
    assert normalize_aqs_code("840TT5821016") == "TT5821016"
    assert in_california_scope("06-007-2003")
    assert in_california_scope("TT-582-1016")
    assert not in_california_scope("41-029-0203")
    assert not in_california_scope(None)

from shapely import from_wkb
from shapely.geometry import MultiPolygon, box

from app.core.scope import in_california_scope
from app.db.seed_ca_forecast_grid import generate_grid
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
    assert all(from_wkb(cell["cell_wkb"]).geom_type == "Polygon" for cell in first_run)


def test_aqs_normalization_and_california_scope():
    assert normalize_aqs_code("840060072003") == "060072003"
    assert normalize_aqs_code("840TT5821016") == "TT5821016"
    assert in_california_scope("06-007-2003")
    assert in_california_scope("TT-582-1016")
    assert not in_california_scope("41-029-0203")
    assert not in_california_scope(None)

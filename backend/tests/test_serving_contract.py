"""PM-03 serving contract: features.json follows ml.feature_columns, and migration 0004 follows the ORM."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.models.values import FORECAST_SOURCES, HORIZON_HOURS, KINDS
from ml.feature_columns import DERIVED, FEATURES, FEATURES_V2

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = (BACKEND / "app/db/migrations/versions/0004_serving_contract.py").read_text()


def _gen():
    spec = importlib.util.spec_from_file_location("gen_features_json", BACKEND / "scripts/gen_features_json.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_spec_covers_exactly_the_model_features():
    assert list(_gen().SPEC) == FEATURES_V2


def test_features_json_is_current():
    gen = _gen()
    assert gen.OUT.read_text() == json.dumps(gen.build(), indent=2, ensure_ascii=False) + "\n"


def test_features_json_order_and_inputs():
    doc = json.loads(_gen().OUT.read_text())
    assert [f["name"] for f in doc["features"]] == FEATURES_V2
    # the caller supplies FEATURES minus horizon_hours; the four derived columns come from add_derived
    assert doc["input_columns"] == [c for c in FEATURES if c != "horizon_hours"]
    assert [f["name"] for f in doc["features"] if f["kind"] == "derived"] == DERIVED
    assert set(doc["example_row"]) - {"forecast_point_id", "issued_at"} == set(doc["input_columns"])
    assert doc["horizons"] == list(HORIZON_HOURS)


def test_migration_matches_orm_values():
    for kind in KINDS:
        assert f"'{kind}'" in MIGRATION
    for source in FORECAST_SOURCES:
        assert f"'{source}'" in MIGRATION

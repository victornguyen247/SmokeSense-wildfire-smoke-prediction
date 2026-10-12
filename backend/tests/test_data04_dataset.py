"""DATA-04 focused offline tests; no live API/DB keys required."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from ml.datasets.build import assign_time_splits, build_versioned_dataset
from ml.datasets.loader import _quoted_identifier
from ml.datasets.schema import FLOAT32_COLUMNS, INTEGER_COLUMNS, cast_and_validate
from features.validation import REQUIRED_COLUMNS


def example_frame(hours: int = 90) -> pd.DataFrame:
    result = {}
    for col in REQUIRED_COLUMNS:
        if col in FLOAT32_COLUMNS:
            result[col] = [0.0] * hours
        elif col in INTEGER_COLUMNS:
            result[col] = [1] * hours
        elif col == "smoke_season":
            result[col] = [True] * hours
        elif col == "forecast_point_id":
            result[col] = ["point-1"] * hours
        elif col == "pilot_event_id":
            result[col] = [f"PE-{1 + min(2, (i * 3 // hours)):03d}" for i in range(hours)]
        elif col == "target_source":
            result[col] = ["regulatory"] * hours
        elif col in ("issue_time", "target_time"):
            continue
        else:
            raise AssertionError(col)
    t = pd.date_range("2026-01-01", periods=hours, freq="h", tz="UTC")
    result["issue_time"] = t
    result["target_time"] = t + pd.Timedelta(hours=1)
    result["horizon_hours"] = [1] * hours
    result["target_pm25"] = [42.0] * hours
    result["target_monitor_dist_km"] = [2.0] * hours
    result["nearest_fire_dist_km"] = [100.0] * hours
    result["location_lat"] = [40.0] * hours
    result["location_lon"] = [-120.0] * hours
    result["local_solar_hour"] = [12.0] * hours
    result["precip_prob_pct"] = [float("nan")] * hours
    result["month"] = [1] * hours
    result["day_of_year"] = [1] * hours
    return pd.DataFrame(result)


def test_cast_schema():
    result = cast_and_validate(example_frame())
    assert str(result["target_pm25"].dtype) == "float32"
    assert str(result["horizon_hours"].dtype) == "int8"
    assert str(result["smoke_season"].dtype) == "boolean"
    assert str(result["issue_time"].dt.tz) == "UTC"


def test_reject_unknown_column():
    with pytest.raises(ValueError, match="unexpected"):
        cast_and_validate(example_frame().assign(purpleair_raw=5))


def test_reject_purpleair_labels():
    df = example_frame()
    df.loc[0, "target_source"] = "purpleair_barkjohn"
    with pytest.raises(ValueError, match="PurpleAir"):
        cast_and_validate(df)


def test_reject_missing_label():
    df = example_frame()
    df.loc[0, "target_pm25"] = None
    with pytest.raises(ValueError, match="target_pm25"):
        cast_and_validate(df)


def test_reject_fractional_int():
    df = example_frame()
    df["horizon_hours"] = df["horizon_hours"].astype("float64")
    df.loc[0, "horizon_hours"] = 1.5
    with pytest.raises(ValueError, match="integer"):
        cast_and_validate(df)


def test_safe_sql_identifiers():
    assert _quoted_identifier("geo.features") == '"geo"."features"'
    with pytest.raises(ValueError, match="Unsafe"):
        _quoted_identifier("features;DROP TABLE users")


def test_grouped_event_split():
    result, details = assign_time_splits(cast_and_validate(example_frame()))
    assert set(result["split"]) == {"train", "val", "test"}
    assert details["unit"] == "pilot_event_id"
    assert len(result) == len(example_frame())
    assert result.groupby("pilot_event_id")["split"].nunique().eq(1).all()


def test_parquet_manifest_if_available(tmp_path: Path):
    pytest.importorskip("pyarrow")
    path = build_versioned_dataset(example_frame(), version="v1-smoke", output_root=tmp_path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rows"] > 0
    assert manifest["events"] == ["PE-001", "PE-002", "PE-003"]
    assert (path / "DATASET_CARD.md").exists()
    for item in manifest["files"]:
        actual = path / item["path"]
        assert hashlib.sha256(actual.read_bytes()).hexdigest() == item["sha256"]
    with pytest.raises(FileExistsError):
        build_versioned_dataset(example_frame(), version="v1-smoke", output_root=tmp_path)


def test_loader_reads_selected_events_from_sqlite(tmp_path: Path, monkeypatch):
    """SQLAlchemy expanding-bind behavior without any network or real secrets."""
    from sqlalchemy import create_engine, text
    from ml.datasets.loader import load_event_rows
    db = tmp_path / "geo01.sqlite"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE features (pilot_event_id TEXT, target_pm25 REAL)"))
        connection.execute(text("INSERT INTO features VALUES ('PE-001', 12), ('PE-002', 13), ('PE-003', 14)"))
    engine.dispose()
    monkeypatch.setenv("DATA04_TEST_DB_URL", url)
    result = load_event_rows(["PE-001", "PE-003"], table="features",
                             database_url_env="DATA04_TEST_DB_URL")
    assert sorted(result["pilot_event_id"].tolist()) == ["PE-001", "PE-003"]

"""DATA-04 acceptance tests from PM-01/schema.md and DATA-04 issue #7.

These tests use synthetic data only. Live PostgreSQL, exact label provenance,
20-event coverage, shared-storage publication, and performance are separate
release gates and are not claimed by this suite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from ml.datasets.build import assign_time_splits, build_versioned_dataset
from ml.datasets.loader import load_event_rows
from ml.datasets.schema import cast_and_validate
from test_data04_dataset import example_frame


def test_pm01_contract_integer_widths_and_utc():
    df = cast_and_validate(example_frame())
    for column, expected in {
        "horizon_hours": "int8",
        "month": "int8",
        "day_of_year": "int16",
        "active_fire_count_200km": "int16",
    }.items():
        assert str(df[column].dtype) == expected
    assert str(df["target_pm25"].dtype) == "float32"
    assert str(df["issue_time"].dt.tz) == "UTC"
    assert str(df["target_time"].dt.tz) == "UTC"


def test_complete_event_holdout_and_deterministic_order():
    data = cast_and_validate(example_frame(hours=180))
    split_1, metadata_1 = assign_time_splits(data)
    split_2, metadata_2 = assign_time_splits(data.sample(frac=1, random_state=33))
    assert metadata_1 == metadata_2
    assert set(split_1["split"]) == {"train", "val", "test"}
    assert split_1.groupby("pilot_event_id")["split"].nunique().eq(1).all()
    assert len(split_1) == len(data)
    assert (
        split_1.groupby("pilot_event_id")["split"].first().to_dict()
        == split_2.groupby("pilot_event_id")["split"].first().to_dict()
    )


def test_one_event_cannot_be_split_across_sets():
    df = cast_and_validate(example_frame())
    df["pilot_event_id"] = "PE-001"
    with pytest.raises(ValueError, match="at least 3 distinct pilot events"):
        assign_time_splits(df)


def test_reject_missing_pm01_column():
    with pytest.raises(ValueError, match="missing"):
        cast_and_validate(example_frame().drop(columns="wind_alignment"))


def test_reject_inconsistent_horizon_target_time():
    data = example_frame()
    data.loc[0, "target_time"] = data.loc[0, "issue_time"]
    with pytest.raises(ValueError, match="target_time"):
        cast_and_validate(data)


def test_v1_observed_weather_does_not_fabricate_precip():
    data = example_frame()
    data["precip_1h_mm"] = float("nan")
    data["precip_prob_pct"] = float("nan")
    checked = cast_and_validate(data)
    assert checked["precip_1h_mm"].isna().all()
    assert checked["precip_prob_pct"].isna().all()
    data.loc[0, "precip_prob_pct"] = 70.0
    with pytest.raises(ValueError, match="precip_prob_pct"):
        cast_and_validate(data)


def test_label_distance_must_be_present():
    data = example_frame()
    data.loc[0, "target_monitor_dist_km"] = float("nan")
    with pytest.raises(ValueError, match="target_monitor_dist_km"):
        cast_and_validate(data)


def test_integer_range_rejects_overflow():
    data = example_frame()
    data.loc[0, "active_fire_count_200km"] = 40000
    with pytest.raises(ValueError, match="integer"):
        cast_and_validate(data)


def test_manifest_roundtrip_partitions_and_checksum(tmp_path: Path):
    pytest.importorskip("pyarrow")
    path = build_versioned_dataset(example_frame(), version="v1-acceptance", output_root=tmp_path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "v1-acceptance"
    assert manifest["data_path"] == "data"
    assert manifest["rows"] == len(example_frame())
    assert set(manifest["splits"]["events"]) == {"train", "val", "test"}
    assert len(manifest["files"]) == len(manifest["events"]) == 3
    for file in manifest["files"]:
        local_file = path / file["path"]
        assert local_file.is_file()
        assert file["path"].startswith("data/event_id=")
        assert file["bytes"] == local_file.stat().st_size
        assert file["sha256"] == hashlib.sha256(local_file.read_bytes()).hexdigest()
        partition = pd.read_parquet(local_file)
        assert len(partition) == file["rows"]
        assert partition["pilot_event_id"].nunique() == 1
    assert sorted(p.name for p in (path / "data").iterdir()) == [
        "event_id=PE-001", "event_id=PE-002", "event_id=PE-003"
    ]
    data = pd.read_parquet(path / manifest["data_path"])
    assert len(data) == manifest["rows"]
    assert set(data["pilot_event_id"]) == set(manifest["events"])
    assert data.groupby("pilot_event_id")["split"].nunique().eq(1).all()
    assert str(data["horizon_hours"].dtype) == "int8"
    card = (path / "DATASET_CARD.md").read_text(encoding="utf-8")
    for clause in ("AirNow", "RawConcentration", "AQS", "Red Bluff", "Lone Pine", "Tahoe City", "PurpleAir", "NCEI"):
        assert clause in card
    assert "pending" in card.lower()  # source provenance is explicitly unresolved


def test_invalid_version_does_not_write_output(tmp_path: Path):
    with pytest.raises(ValueError, match="Invalid version"):
        build_versioned_dataset(example_frame(), version="../oops", output_root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_loader_rejects_missing_credentials_without_leaking_value(monkeypatch):
    monkeypatch.delenv("DATA04_ACCEPTANCE_DB", raising=False)
    with pytest.raises(RuntimeError, match="DATA04_ACCEPTANCE_DB") as err:
        load_event_rows(["PE-001"], table="feature_rows", database_url_env="DATA04_ACCEPTANCE_DB")
    assert "postgresql://" not in str(err.value)

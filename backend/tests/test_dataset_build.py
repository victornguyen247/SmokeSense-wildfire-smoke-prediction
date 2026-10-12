"""DATA-04 dataset build: assembly rules and leakage checks on small fixtures (no DB)."""

from __future__ import annotations

import pandas as pd
import pytest

from dataset_build import checks
from dataset_build.build_v1 import cast, dedupe, issue_times, overlap_groups
from features.alignment import build_feature_dataset
from ingestion.batch.batch_ingest import PilotEvent

T0 = pd.Timestamp("2020-09-01T00:00Z")
POINT = {"forecast_point_id": "airnow:p1", "location_lat": 39.0, "location_lon": -121.0}


def _event(eid, start, end):
    return PilotEvent(event_id=eid, name=eid, bbox="-122.00,38.50,-120.00,39.50", start_date=start, end_date=end)


# ---------------------------------------------------------------------------
# Assembly rules (entries 19 and 21)
# ---------------------------------------------------------------------------

def test_issue_times_cover_start_00_to_end_23_utc():
    t = issue_times("2020-09-01", "2020-09-02")
    assert len(t) == 48
    assert t.iloc[0] == pd.Timestamp("2020-09-01T00:00Z")
    assert t.iloc[-1] == pd.Timestamp("2020-09-02T23:00Z")


def test_overlap_groups_are_connected_components():
    events = [_event("PE-A", "2020-08-01", "2020-08-10"), _event("PE-B", "2020-08-10", "2020-08-20"),
              _event("PE-C", "2020-08-15", "2020-09-01"), _event("PE-D", "2021-01-01", "2021-01-02")]
    g = overlap_groups(events)
    assert g["PE-A"] == g["PE-B"] == g["PE-C"] == "G-PE-A"  # A-B touch, B-C overlap: one component
    assert g["PE-D"] == "G-PE-D"


def _rows(eid, value):
    return pd.DataFrame({"forecast_point_id": ["airnow:p1"], "issue_time": [T0], "horizon_hours": [1],
                         "pilot_event_id": [eid], "target_pm25": [value]})


def test_dedupe_keeps_one_row_and_lists_all_events():
    out = dedupe({"PE-B": _rows("PE-B", 2.0), "PE-A": _rows("PE-A", 1.0)},
                 tiers={"PE-A": "high", "PE-B": "low"}, groups={"PE-A": "G-PE-A", "PE-B": "G-PE-A"})
    assert len(out) == 1
    row = out.iloc[0]
    assert row["event_ids"] == ["PE-A", "PE-B"]
    assert row["pilot_event_id"] == "PE-A"
    assert row["target_pm25"] == 1.0  # the first event's row is kept
    assert (row["event_tier"], row["group_id"]) == ("high", "G-PE-A")


# ---------------------------------------------------------------------------
# Leakage checks (entry 20): build on a fixture, then prove each check catches a leak
# ---------------------------------------------------------------------------

@pytest.fixture
def built():
    hours = pd.date_range(T0 - pd.Timedelta(hours=24), T0 + pd.Timedelta(hours=30), freq="h")
    obs = pd.DataFrame({"monitor_id": "airnow:p1", "valid_at": hours, "pm25": range(len(hours)),
                        "correction": "regulatory", "qa_flag": None, "latitude": 39.0, "longitude": -121.0})
    history = obs.rename(columns={"monitor_id": "forecast_point_id", "valid_at": "issue_time"})[
        ["forecast_point_id", "issue_time", "pm25"]]
    fires = pd.DataFrame({
        "detected_at": [T0 - pd.Timedelta(hours=2), T0, T0 + pd.Timedelta(hours=1)],  # before / at / after
        "latitude": [39.1, 39.1, 39.1], "longitude": [-121.1, -121.1, -121.1], "frp_mw": [10.0, 50.0, 90.0]})
    weather = pd.DataFrame({
        "station_id": "KTST", "valid_at": [T0 - pd.Timedelta(hours=1), T0 + pd.Timedelta(minutes=30)],
        "latitude": 39.05, "longitude": -121.05, "wind_speed_ms": [2.0, 9.0], "wind_dir_deg": [270.0, 90.0],
        "temp_c": [20.0, 35.0], "rh_pct": [30.0, 10.0], "pressure_hpa": [1010.0, 1000.0], "precip_1h_mm": [0.0, 0.0]})
    rows = build_feature_dataset(
        forecast_points=pd.DataFrame([POINT]), issue_times=pd.Series([T0]), fire_detections=fires,
        pm25_history=history, weather_observations=weather, pm25_observations=obs, pilot_event_id="PE-T")
    return rows, {"fires": fires, "weather": weather, "pm25_history": history, "pm25_observations": obs}


def test_fixture_rows_pass_every_check(built):
    rows, frames = built
    r = rows.iloc[0]
    assert r["active_fire_count_200km"] == 1          # only the detection before issue_time
    assert r["temp_c"] == 20.0                        # the report at issue_time - 1 h, not the later one
    assert r["pm25_lag_1h"] == 23.0                   # history value at issue_time - 1 h
    assert checks.check_event(rows, frames) == {"fires": 5, "weather": 5, "lags": 5, "target": 5}


@pytest.mark.parametrize("column, value, check", [
    ("active_fire_count_200km", 2, "fires"),  # counting the detection at issue_time
    ("temp_c", 35.0, "weather"),              # the report after issue_time
    ("pm25_lag_1h", 24.0, "lags"),            # the value at issue_time itself
    ("target_pm25", -1.0, "target"),
])
def test_checks_catch_leaks(built, column, value, check):
    rows, frames = built
    leaked = rows.copy()
    leaked.loc[0, column] = value
    with pytest.raises(checks.LeakageError, match=check):
        checks.check_event(leaked, frames)


def test_target_time_must_be_issue_plus_horizon(built):
    rows, frames = built
    leaked = rows.copy()
    leaked.loc[0, "target_time"] = leaked.loc[0, "target_time"] + pd.Timedelta(hours=1)
    with pytest.raises(checks.LeakageError, match="target_time"):
        checks.check_targets(leaked, frames["pm25_observations"])


def test_cast_applies_contract_dtypes(built):
    rows, _ = built
    out = cast(rows.assign(event_tier="low", group_id="G-PE-T"))
    assert str(out["horizon_hours"].dtype) == "int8"
    assert str(out["active_fire_count_200km"].dtype) == "int16"
    assert str(out["target_pm25"].dtype) == "float32"
    assert str(out["issue_time"].dtype) == "datetime64[ns, UTC]"

"""Parity runner regressions: no live seeds, full coverage, explicit exclusions."""
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd
import pytest

from features.alignment import build_input_features
from ingestion.batch.batch_ingest import PilotEvent
from scripts import check_geo03 as check
from serving import geo

H = pd.Timestamp("2020-10-26T02:00Z")


@pytest.fixture
def historical_parity(tmp_path, monkeypatch):
    # Stale monitor has future/current readings too, neither available before H.
    points = pd.DataFrame({"forecast_point_id": ["airnow:good", "airnow:stale"],
                           "location_lat": 39., "location_lon": -121.})
    history = pd.DataFrame({
        "forecast_point_id": ["airnow:good", "airnow:stale", "airnow:stale", "airnow:stale"],
        "issue_time": [H - pd.Timedelta(hours=1), H - pd.Timedelta(hours=24, seconds=1),
                       H, H + pd.Timedelta(hours=1)], "pm25": 10.,
    })
    inputs = {
        "pm25_history": history,
        "fires": pd.DataFrame(columns=["detected_at", "latitude", "longitude", "frp_mw"]),
        "weather": pd.DataFrame(columns=["station_id", "valid_at", "latitude", "longitude",
                                          "wind_speed_ms", "wind_dir_deg", "temp_c", "rh_pct",
                                          "pressure_hpa", "precip_1h_mm"]),
    }
    event = PilotEvent("PE-001", "Parity", "-122,38,-120,40", "2020-10-25", "2020-10-26")
    calls = []

    def event_points(connection, ev, registry, row_scope):
        assert ev == event and row_scope == "historical"
        calls.append("points")
        return points, []

    def event_inputs(connection, ev, row_scope):
        assert ev == event and row_scope == "historical"
        calls.append("inputs")
        return inputs

    def unexpected_seed_read(connection):
        pytest.fail("Parity must not require live seeded points")

    disposed = []
    monkeypatch.setattr(check, "create_engine", lambda url: SimpleNamespace(
        connect=lambda: nullcontext(None), dispose=lambda: disposed.append(True)))
    monkeypatch.setattr(check, "load_pilot_events", lambda config: [event])
    monkeypatch.setattr(check, "load_registry", lambda: {})
    monkeypatch.setattr(check, "forecast_points", event_points)
    monkeypatch.setattr(check, "load_inputs", event_inputs)
    monkeypatch.setattr(geo, "load_monitor_points", unexpected_seed_read)
    artifact = tmp_path / "data.parquet"

    def write(hours=(H,)):
        frame = build_input_features(
            points, pd.Series(list(hours)), inputs["fires"], inputs["pm25_history"],
            inputs["weather"], horizons=(1,),
        ).assign(pilot_event_id=event.event_id)
        frame[["forecast_point_id", "issue_time", "pilot_event_id", *check.INPUT_COLUMNS]].to_parquet(artifact)
        return frame

    write()
    return SimpleNamespace(path=artifact, points=points, inputs=inputs, write=write,
                           calls=calls, disposed=disposed)


def summary(capsys):
    return json.loads(capsys.readouterr().out)


def test_full_parity_without_seeds_counts_only_verified_exclusions(historical_parity, capsys):
    check.parity(historical_parity.path)
    assert summary(capsys) == {
        "coverage": "full", "reference_rows": 2, "parity_rows": 1,
        "excluded_no_recent_reading": 1, "event_hours": 1,
    }
    assert historical_parity.disposed == [True]


def test_off_hour_reading_is_eligible_even_when_all_lags_are_null(historical_parity, capsys):
    history = historical_parity.inputs["pm25_history"]
    history.loc[history.forecast_point_id.eq("airnow:stale"), "issue_time"] = H - pd.Timedelta(minutes=150)
    historical_parity.write()
    check.parity(historical_parity.path)
    result = summary(capsys)
    assert result["parity_rows"] == 2 and result["excluded_no_recent_reading"] == 0


def test_eligible_missing_row_still_fails(historical_parity, monkeypatch):
    real_build = check.build_monitor_features

    def broken_build(*args, **kwargs):
        return real_build(*args, **kwargs).iloc[:0]

    monkeypatch.setattr(check, "build_monitor_features", broken_build)
    with pytest.raises(AssertionError, match="eligible Parquet rows missing.*airnow:good"):
        check.parity(historical_parity.path)
    assert historical_parity.disposed == [True]


def test_missing_historical_point_still_fails(historical_parity):
    historical_parity.points.loc[0, "forecast_point_id"] = "not-in-reference"
    with pytest.raises(AssertionError, match="Parquet point absent from historical"):
        check.parity(historical_parity.path)


def test_excluded_row_with_nonnull_reference_lag_fails(historical_parity):
    expected = pd.read_parquet(historical_parity.path)
    expected.loc[expected.forecast_point_id.eq("airnow:stale"), "pm25_lag_1h"] = 10.
    expected.to_parquet(historical_parity.path)
    with pytest.raises(AssertionError, match="excluded row has a non-null v1 lag"):
        check.parity(historical_parity.path)


def test_feature_mismatch_still_fails(historical_parity):
    expected = pd.read_parquet(historical_parity.path)
    expected.loc[expected.forecast_point_id.eq("airnow:good"), "pm25_lag_1h"] = 999.
    expected.to_parquet(historical_parity.path)
    with pytest.raises(AssertionError, match="pm25_lag_1h"):
        check.parity(historical_parity.path)


def test_sampled_smoke_check_is_labeled_and_full_default_checks_every_hour(historical_parity, capsys):
    hours = pd.date_range(H - pd.Timedelta(hours=1), H + pd.Timedelta(hours=4), freq="h")
    historical_parity.write(hours)
    check.parity(historical_parity.path, samples=5)
    assert summary(capsys)["coverage"] == "sampled"
    check.parity(historical_parity.path)
    result = summary(capsys)
    assert result["coverage"] == "full" and result["event_hours"] == 6
    # Source snapshots and v1 points are loaded once per event, not per hour.
    assert historical_parity.calls == ["points", "inputs", "points", "inputs"]

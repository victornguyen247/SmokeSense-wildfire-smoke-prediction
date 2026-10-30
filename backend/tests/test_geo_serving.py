"""GEO-03 parity, time boundaries, point identities and Stage B rules."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.scope import CALIFORNIA_BBOX
from features.alignment import build_feature_dataset
from features.idw import interpolate_to_grid
from features.spatial import EARTH_RADIUS_KM, haversine_distance_km
from serving import geo

H = pd.Timestamp("2020-09-01T12:00Z")


@pytest.fixture
def live_inputs(monkeypatch):
    points = pd.DataFrame([{"forecast_point_id": "seeded-point", "external_id": "airnow:site",
                            "aqs_code": "060070008", "location_lat": 39., "location_lon": -121.}])
    times = pd.date_range(H - pd.Timedelta(hours=24), H + pd.Timedelta(hours=24), freq="h")
    obs = pd.DataFrame({"monitor_id": "airnow:site", "valid_at": times, "pm25": np.arange(len(times)),
                        "correction": "regulatory", "qa_flag": None, "latitude": 39., "longitude": -121.})
    history = obs.rename(columns={"monitor_id": "forecast_point_id", "valid_at": "issue_time"})[
        ["forecast_point_id", "issue_time", "pm25"]]
    fires = pd.DataFrame({
        "detected_at": [H - pd.Timedelta(hours=72), H, H + pd.Timedelta(hours=1)],
        "latitude": 39.1, "longitude": -121.1, "frp_mw": [10., 100., 1000.]})
    weather = pd.DataFrame({
        "station_id": "KTST", "valid_at": [H - pd.Timedelta(minutes=7), H + pd.Timedelta(minutes=1)],
        "latitude": 39., "longitude": -121., "wind_speed_ms": 2., "wind_dir_deg": 270.,
        "temp_c": [20., 99.], "rh_pct": 30., "pressure_hpa": np.nan, "precip_1h_mm": np.nan})
    frames = {"fires": fires, "weather": weather, "pm25_history": history, "pm25_observations": obs}
    calls = []

    def load(connection, event, row_scope):
        calls.append((event, row_scope))
        return frames

    monkeypatch.setattr(geo, "load_inputs", load)
    monkeypatch.setattr(geo, "load_monitor_points", lambda connection: points)
    return points, frames, calls


def build(**kwargs):
    return geo.build_monitor_features(H, connection=None, fire_feed_available=True, **kwargs)


def test_live_matches_training_features_all_horizons(live_inputs):
    points, frames, calls = live_inputs
    live = build()
    training_points = points.assign(forecast_point_id=points.external_id)
    training = build_feature_dataset(
        training_points, pd.Series([H]), frames["fires"], frames["pm25_history"],
        frames["weather"], frames["pm25_observations"])
    assert len(training) == 5
    for _, row in training.iterrows():
        for column in geo.INPUT_COLUMNS:
            if pd.isna(row[column]):
                assert pd.isna(live.iloc[0][column])
            else:
                assert float(live.iloc[0][column]) == pytest.approx(float(row[column]), rel=1e-6)
    assert calls[0][1] == "live"
    assert calls[0][0].bbox == str(CALIFORNIA_BBOX)
    assert live.forecast_point_id.tolist() == ["seeded-point"]
    assert live.iloc[0].pm25_lag_1h == 23
    assert live.iloc[0].active_fire_count_200km == 1
    assert live.iloc[0].temp_c == 20
    assert live.pressure_hpa.isna().all() and live.precip_1h_mm.isna().all()
    assert list(live.columns) == geo.OUTPUT_COLUMNS
    assert live.temp_c.dtype == np.dtype("float32")
    assert live.active_fire_count_200km.dtype == np.dtype("int16")


def test_no_future_labels_needed_and_no_lag_imputation(live_inputs):
    _, frames, _ = live_inputs
    frames["pm25_observations"] = frames["pm25_observations"].iloc[:0]
    history = frames["pm25_history"]
    frames["pm25_history"] = history.loc[history.issue_time != H - pd.Timedelta(hours=1)]
    live = build()
    assert len(live) == 1
    assert pd.isna(live.iloc[0].pm25_lag_1h)
    assert live.iloc[0].pm25_lag_3h == 21


def test_no_recent_observations_returns_empty_schema(live_inputs):
    _, frames, _ = live_inputs
    frames["pm25_history"] = frames["pm25_history"].iloc[:0]
    result = build()
    assert result.empty and list(result.columns) == geo.OUTPUT_COLUMNS
    assert str(result.issued_at.dtype) == "datetime64[ns, UTC]"
    assert result.pressure_hpa.dtype == np.dtype("float32")


def test_input_order_matches_pm03_contract(live_inputs):
    contract = Path(__file__).resolve().parents[2] / "docs/ml/features.json"
    expected = json.loads(contract.read_text())["input_columns"]
    assert list(build().columns) == ["forecast_point_id", "issued_at", *expected]


def test_missing_monitor_seed_is_explicit(live_inputs, monkeypatch):
    monitor_points, _, _ = live_inputs
    monkeypatch.setattr(geo, "load_monitor_points", lambda connection: monitor_points.iloc[:0])
    with pytest.raises(RuntimeError, match="--sync-monitors"):
        build()


def test_missing_grid_seed_is_explicit(monkeypatch):
    monkeypatch.setattr(pd, "read_sql", lambda *args: pd.DataFrame(columns=[
        "forecast_point_id", "location_lat", "location_lon",
    ]))
    with pytest.raises(RuntimeError, match="No active seeded grid cells"):
        geo.interpolate_to_grid(forecasts(1), connection=None)


def test_weather_exact_three_hour_boundary_and_stale(live_inputs):
    _, frames, _ = live_inputs
    frames["weather"] = frames["weather"].iloc[:1].copy()
    frames["weather"]["valid_at"] = H - pd.Timedelta(hours=3)
    assert build().iloc[0].temp_c == 20
    frames["weather"]["valid_at"] -= pd.Timedelta(seconds=1)
    assert pd.isna(build().iloc[0].temp_c)


def test_historical_scope_forwarded(live_inputs):
    _, _, calls = live_inputs
    build(row_scope="historical")
    assert calls[0][1] == "historical"


@pytest.mark.parametrize("t", ["2020-09-01T12:00", "2020-09-01T12:01Z", None])
def test_reject_invalid_hour(t):
    with pytest.raises(ValueError):
        geo.build_monitor_features(t, connection=None, fire_feed_available=True)


def test_unavailable_fire_feed_skips_cycle():
    with pytest.raises(RuntimeError, match="skip"):
        geo.build_monitor_features(H, connection=None, fire_feed_available=False)


def points(distances):
    # Along the equator: chosen longitude differences give exact distances.
    return pd.DataFrame({"forecast_point_id": [f"p{i}" for i in range(len(distances))],
                         "location_lat": 0., "location_lon": np.degrees(np.array(distances) / EARTH_RADIUS_KM)})


def forecasts(n):
    return pd.DataFrame({"forecast_point_id": [f"p{i}" for i in range(n)], "issued_at": H,
                         "horizon_hours": 1, "pm25_predicted": np.arange(1, n + 1) * 10.,
                         "source": "v2", "model_key": "baseline/v2"})


def test_idw_four_nearest_floor_and_real_distance():
    monitors = points([0., .5, 2., 4., 5.])
    result = interpolate_to_grid(forecasts(5), monitors, points([0.]))
    row = result.iloc[0]
    weights = np.array([1., 1., 1/4, 1/16])
    assert row.pm25_predicted == pytest.approx(np.dot(weights, [10, 20, 30, 40]) / weights.sum())
    assert row.nearest_monitor_dist_km == 0
    assert row.source == "idw"
    neighbors = row.feature_snapshot["monitors"]
    assert len(neighbors) == 4
    assert sum(n["weight"] for n in neighbors) == pytest.approx(1.)
    assert neighbors[1]["distance_km"] == pytest.approx(.5)


def test_idw_excludes_fallback_nonfinite_and_outside_radius():
    prediction = forecasts(4)
    prediction.loc[0, "source"] = "fallback"
    prediction.loc[1, "pm25_predicted"] = np.nan
    prediction.loc[2, "source"] = "persistence"
    row = interpolate_to_grid(prediction, points([0, 1, 10, 51]), points([0])).iloc[0]
    assert row.pm25_predicted == 30
    assert row.nearest_monitor_dist_km == pytest.approx(10)
    assert row.feature_snapshot["monitors"][0]["source"] == "persistence"
    assert interpolate_to_grid(prediction.iloc[:2], points([0, 1]), points([0])).empty


def test_idw_radius_boundary_and_uncovered_cell():
    assert len(interpolate_to_grid(forecasts(1), points([50]), points([0]))) == 1
    assert interpolate_to_grid(forecasts(1), points([50.001]), points([0])).empty


def test_horizons_and_issue_times_stay_separate():
    one = forecasts(1)
    combined = pd.concat([one, one.assign(horizon_hours=3, pm25_predicted=70),
                          one.assign(issued_at=H + pd.Timedelta(hours=1), pm25_predicted=90)])
    result = interpolate_to_grid(combined, points([0]), points([0]))
    assert result.pm25_predicted.tolist() == [10, 70, 90]
    assert result.target_time.tolist() == [H + pd.Timedelta(hours=h) for h in (1, 3, 2)]


def test_ml04_target_time_is_preserved_and_validated():
    prediction = forecasts(1).assign(target_time=H + pd.Timedelta(hours=1))
    row = interpolate_to_grid(prediction, points([0]), points([0])).iloc[0]
    assert row.target_time == H + pd.Timedelta(hours=1)
    assert row.model_key == "baseline/v2"
    with pytest.raises(ValueError, match="target_time"):
        interpolate_to_grid(prediction.assign(target_time=H), points([0]), points([0]))
    with pytest.raises(ValueError, match="timezone-aware"):
        interpolate_to_grid(prediction.assign(target_time=H.tz_localize(None)), points([0]), points([0]))


def test_empty_interpolation_has_utc_forecast_times():
    result = interpolate_to_grid(forecasts(0), points([0]), points([0]))
    assert result.empty
    assert str(result.issued_at.dtype) == "datetime64[ns, UTC]"
    assert str(result.target_time.dtype) == "datetime64[ns, UTC]"


def test_ml04_adapter_accepts_features_and_grid_schema(live_inputs, monkeypatch):
    # Runs automatically once PR #92 lands, without needing any model artifacts.
    adapter = pytest.importorskip("ml.inference.service", reason="PR #92 is not merged yet")
    service = adapter.InferenceService("baseline/v2", Path("unused"), tuple(geo.INPUT_COLUMNS))

    def predict(frame, horizon, model_dir):
        return pd.DataFrame({"pm25": np.repeat(20., len(frame)),
                             "source": np.repeat("persistence" if horizon == 1 else "v2", len(frame))})

    monkeypatch.setattr(adapter.predict_v2, "predict", predict)
    prediction = service.predict(build())
    monitor_points, frames, _ = live_inputs
    result = interpolate_to_grid(prediction, monitor_points, monitor_points)
    assert len(result) == 5
    assert set(adapter.FORECAST_COLUMNS).issubset(result.columns)
    assert result.model_key.eq("baseline/v2").all()
    frames["pm25_history"] = frames["pm25_history"].iloc[:0]
    assert service.predict(build()).empty


def test_idw_haversine_matches_shared_distance():
    monitor, grid = points([0]), points([0])
    monitor.loc[0, ["location_lat", "location_lon"]] = [39, -121]
    grid.loc[0, ["location_lat", "location_lon"]] = [39.1, -121.1]
    row = interpolate_to_grid(forecasts(1), monitor, grid).iloc[0]
    assert row.nearest_monitor_dist_km == pytest.approx(haversine_distance_km(39, -121, 39.1, -121.1))


@pytest.mark.parametrize("mutation", ["duplicate", "model", "unknown", "negative", "horizon"])
def test_invalid_stage_a_inputs_are_rejected(mutation):
    prediction = forecasts(2)
    if mutation == "duplicate":
        prediction.loc[1, "forecast_point_id"] = "p0"
    elif mutation == "model":
        prediction.loc[1, "model_key"] = "other/1.0.0"
    elif mutation == "unknown":
        prediction.loc[1, "forecast_point_id"] = "unknown"
    elif mutation == "negative":
        prediction.loc[1, "pm25_predicted"] = -1
    else:
        prediction.loc[1, "horizon_hours"] = 2
    with pytest.raises(ValueError):
        interpolate_to_grid(prediction, points([0, 1]), points([0]))


def test_seeded_monitor_query_applies_contract_filters(monkeypatch):
    def read(query, connection):
        sql = str(query)
        for condition in ["fp.kind = 'monitor'", "fp.active", "m.active",
                          "m.source = 'airnow'", "m.location_type = 'outdoor'"]:
            assert condition in sql
        return pd.DataFrame({"aqs_code": ["060070008", "320000001"], "forecast_point_id": ["ca", "nv"]})
    monkeypatch.setattr(pd, "read_sql", read)
    assert geo.load_monitor_points(None).forecast_point_id.tolist() == ["ca"]

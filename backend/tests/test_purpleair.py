from datetime import datetime, timezone

import httpx
import pytest

from ingestion.connectors import purpleair

SENSOR = {
    "sensor_index": 12345,
    "name": "Chico Backyard",
    "latitude": 39.73,
    "longitude": -121.84,
    "altitude": 200,
    "location_type": 0,
    "date_created": 1577836800,  # 2020-01-01
    "last_seen": 1735689600,  # 2025-01-01
}

# 2021-08-05 12:00 UTC
TS = 1628164800


def row(a=40.0, b=42.0, humidity=30.0, ts=TS):
    return {
        "time_stamp": ts,
        "pm2.5_cf_1_a": a,
        "pm2.5_cf_1_b": b,
        "humidity": humidity,
    }


# --- Row normalization -------------------------------------------------------


def test_normalize_applies_barkjohn():
    record = purpleair.normalize_purpleair_row(row(), SENSOR)
    obs = record["observation"]

    # 0.524 * 41 - 0.0862 * 30 + 5.75
    assert obs["pm25"] == pytest.approx(24.65, abs=0.01)
    assert obs["correction"] == "purpleair_barkjohn"
    assert obs["qa_flag"] == "ok"
    assert obs["pm25_cf1_a"] == 40.0
    assert obs["pm25_cf1_b"] == 42.0
    assert obs["rh_pct"] == 30.0
    assert obs["valid_at"] == datetime(2021, 8, 5, 12, tzinfo=timezone.utc)


def test_monitor_matches_schema():
    monitor = purpleair.normalize_purpleair_row(row(), SENSOR)["monitor"]

    assert monitor["source"] == "purpleair"
    assert monitor["external_id"] == "12345"
    assert monitor["location_type"] == "outdoor"
    assert monitor["geom_wkt"] == "POINT(-121.84 39.73)"
    assert monitor["elevation_m"] == 61.0  # 200 ft
    assert monitor["first_seen_at"] == datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_missing_humidity_stores_raw_not_label_eligible():
    obs = purpleair.normalize_purpleair_row(row(humidity=None), SENSOR)["observation"]

    assert obs["correction"] == "purpleair_raw"
    assert obs["pm25"] == 41.0
    assert obs["rh_pct"] is None


def test_out_of_range_humidity_is_treated_as_missing():
    obs = purpleair.normalize_purpleair_row(row(humidity=120), SENSOR)["observation"]
    assert obs["correction"] == "purpleair_raw"


def test_disagreeing_channels_are_invalid():
    obs = purpleair.normalize_purpleair_row(row(a=10.0, b=200.0), SENSOR)["observation"]
    assert obs["qa_flag"] == "invalid"


def test_negative_channel_is_ignored():
    obs = purpleair.normalize_purpleair_row(row(a=-5.0, b=20.0), SENSOR)["observation"]

    assert obs["pm25_cf1_a"] is None
    assert obs["qa_flag"] == "suspect"


def test_no_channels_returns_none():
    assert purpleair.normalize_purpleair_row(row(a=None, b=None), SENSOR) is None


# --- HTTP --------------------------------------------------------------------


def columnar(fields, data):
    return {"fields": fields, "data": data}


def test_fetch_sensors_filters_to_active_window():
    fields = [
        "sensor_index",
        "name",
        "latitude",
        "longitude",
        "date_created",
        "last_seen",
    ]
    data = [
        [1, "active", 39.0, -121.0, 1577836800, 1735689600],
        [2, "created after window", 39.0, -121.0, 1700000000, 1735689600],
        [3, "dead before window", 39.0, -121.0, 1500000000, 1600000000],
        [4, "no coords", None, None, 1577836800, 1735689600],
    ]
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx.Response(200, json=columnar(fields, data))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sensors = purpleair.fetch_purpleair_sensors(
        "key", "-122.5,38.0,-120.5,39.5", "2021-08-05", "2021-08-05", client
    )

    assert [s["sensor_index"] for s in sensors] == [1]

    params = seen["request"].url.params
    assert seen["request"].headers["X-API-Key"] == "key"
    assert params["nwlng"] == "-122.5"
    assert params["nwlat"] == "39.5"
    assert params["selng"] == "-120.5"
    assert params["selat"] == "38.0"
    assert params["location_type"] == "0"
    assert params["max_age"] == "0"


def test_history_is_chunked_to_api_limit():
    requests = []

    def handler(request):
        requests.append(request)
        start = int(request.url.params["start_timestamp"])
        return httpx.Response(
            200,
            json=columnar(
                ["time_stamp", "pm2.5_cf_1_a", "pm2.5_cf_1_b", "humidity"],
                [[start, 1, 1, 50]],
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = purpleair.fetch_purpleair_history_rows(
        "key", 12345, "2021-08-01", "2021-08-31", client
    )

    # 31 days at a 14-day limit -> 3 requests
    assert len(requests) == 3
    assert requests[0].url.path == "/v1/sensors/12345/history"
    assert requests[0].url.params["average"] == "60"
    assert len(rows) == 3


def test_write_key_403_gets_a_hint():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(403, json={"error": "x"})
        )
    )

    with pytest.raises(RuntimeError, match="READ key"):
        purpleair.fetch_purpleair_sensors("key", client=client)


def test_unexpected_shape_raises():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": 1}))
    )

    with pytest.raises(RuntimeError, match="unexpected response shape"):
        purpleair.fetch_purpleair_sensors("key", client=client)


# --- Sensor cap default ------------------------------------------------------


def test_batch_cap_default_matches_connector_and_is_capped(monkeypatch):
    """The batch reads Settings; an old .env without the variable must stay capped."""
    from app.core.config import Settings

    monkeypatch.delenv("PURPLEAIR_MAX_SENSORS", raising=False)
    settings = Settings(_env_file=None)

    assert settings.purpleair_max_sensors == purpleair.DEFAULT_MAX_SENSORS
    assert settings.purpleair_max_sensors > 0


# --- Sensor cap keeps the sensors nearest the bbox center ---------------------
# bbox center is (39.5, -121.5). Distances are deliberately well separated.

CAP_BBOX = "-122.0,39.0,-121.0,40.0"

CAP_SENSORS = [
    {"sensor_index": 10, "latitude": 39.50, "longitude": -121.50},  # at center
    {"sensor_index": 20, "latitude": 39.60, "longitude": -121.50},  # 0.1 deg N
    {"sensor_index": 30, "latitude": 39.50, "longitude": -121.70},  # 0.2 deg W
    {"sensor_index": 40, "latitude": 39.95, "longitude": -121.05},  # NE corner
    {"sensor_index": 50, "latitude": 39.02, "longitude": -121.98},  # SW corner
]
NEAREST_3 = {10, 20, 30}


def _pulled_sensor_indexes(monkeypatch, sensors, max_sensors):
    """Run get_purpleair_pm25_records with the API mocked; return which
    sensors had their history pulled."""
    pulled = []

    def fake_sensors(api_key, bbox, start_date, end_date, client):
        return [dict(s) for s in sensors]

    def fake_history(api_key, sensor_index, start_date, end_date, client):
        pulled.append(sensor_index)
        return []

    monkeypatch.setattr(purpleair, "fetch_purpleair_sensors", fake_sensors)
    monkeypatch.setattr(purpleair, "fetch_purpleair_history_rows", fake_history)

    purpleair.get_purpleair_pm25_records(
        "key", CAP_BBOX, "2021-08-05", "2021-08-05", max_sensors=max_sensors
    )
    return pulled


def test_cap_keeps_nearest_sensors_whatever_the_api_order(monkeypatch):
    from itertools import permutations

    for order in permutations(CAP_SENSORS):
        pulled = _pulled_sensor_indexes(monkeypatch, list(order), max_sensors=3)
        assert set(pulled) == NEAREST_3, [s["sensor_index"] for s in order]


def test_cap_pulls_nearest_first(monkeypatch):
    farthest_first = list(reversed(CAP_SENSORS))
    assert _pulled_sensor_indexes(monkeypatch, farthest_first, max_sensors=5) == [
        10, 20, 30, 40, 50,
    ]


def test_no_cap_pulls_every_sensor(monkeypatch):
    pulled = _pulled_sensor_indexes(monkeypatch, CAP_SENSORS, max_sensors=None)
    assert sorted(pulled) == [10, 20, 30, 40, 50]


def test_ranking_scales_longitude_by_latitude():
    """At ~40N a degree of longitude is ~0.77 of a degree of latitude, so a
    sensor 0.5 deg east is nearer than one 0.45 deg north."""
    east = {"sensor_index": 1, "latitude": 39.5, "longitude": -121.0}
    north = {"sensor_index": 2, "latitude": 39.95, "longitude": -121.5}

    ranked = purpleair.nearest_to_bbox_center([north, east], CAP_BBOX)
    assert [s["sensor_index"] for s in ranked] == [1, 2]


def test_ranking_ties_break_on_sensor_index():
    a = {"sensor_index": 7, "latitude": 39.6, "longitude": -121.5}
    b = {"sensor_index": 3, "latitude": 39.4, "longitude": -121.5}

    ranked = purpleair.nearest_to_bbox_center([a, b], CAP_BBOX)
    assert [s["sensor_index"] for s in ranked] == [3, 7]

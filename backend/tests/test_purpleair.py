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

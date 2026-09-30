import pandas as pd
import pytest

from features.spatial import (
    aggregate_fire_features_200km,
    angular_difference_degrees,
    bearing_degrees,
    haversine_distance_km,
    wind_alignment_degrees,
)

def test_same_point_distance_is_zero():
    distance = haversine_distance_km(
        38.0,
        -121.0,
        38.0,
        -121.0,
    )

    assert distance == pytest.approx(0.0)


def test_known_distance():
    # Approximately 111 km per degree of latitude.
    distance = haversine_distance_km(
        0.0,
        0.0,
        1.0,
        0.0,
    )

    assert distance == pytest.approx(111.2, abs=0.5)


def test_bearing_north():
    bearing = bearing_degrees(
        0.0,
        0.0,
        1.0,
        0.0,
    )

    assert bearing == pytest.approx(0.0)


def test_bearing_east():
    bearing = bearing_degrees(
        0.0,
        0.0,
        0.0,
        1.0,
    )

    assert bearing == pytest.approx(90.0)


def test_bearing_south():
    bearing = bearing_degrees(
        1.0,
        0.0,
        0.0,
        0.0,
    )

    assert bearing == pytest.approx(180.0)


def test_bearing_west():
    bearing = bearing_degrees(
        0.0,
        1.0,
        0.0,
        0.0,
    )

    assert bearing == pytest.approx(270.0)


def test_angular_difference_wraps_at_360():
    assert angular_difference_degrees(350, 10) == pytest.approx(20)


def test_wind_alignment_zero_degrees():
    # Fire -> location = east (90°).
    # Wind comes FROM west (270°), therefore travels east (90°).
    assert wind_alignment_degrees(90, 270) == pytest.approx(0)


def test_wind_alignment_90_degrees():
    # Fire -> location = east.
    # Wind comes from north, therefore travels south.
    assert wind_alignment_degrees(90, 0) == pytest.approx(90)


def test_wind_alignment_180_degrees():
    # Fire -> location = east.
    # Wind comes from east, therefore travels west.
    assert wind_alignment_degrees(90, 90) == pytest.approx(180)

def test_aggregate_fire_features_200km():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 10:00:00+00:00",
                    "2026-09-25 11:00:00+00:00",
                    "2026-09-25 11:30:00+00:00",
                ]
            ),
            "latitude": [
                0.0,
                0.0,
                1.0,
            ],
            "longitude": [
                1.0,
                0.5,
                0.0,
            ],
            "frp_mw": [
                100.0,
                50.0,
                200.0,
            ],
        }
    )

    result = aggregate_fire_features_200km(
        location_latitude=0.0,
        location_longitude=0.0,
        fire_detections=fire_detections,
        issue_time=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
    )

    # The 0.5-degree fire is approximately 55.6 km away
    # and is the nearest fire.
    assert result["nearest_fire_dist_km"] == pytest.approx(
        55.6,
        abs=1.0,
    )

    # From (0, 0.5) to (0, 0) is west.
    assert result["fire_bearing_deg"] == pytest.approx(
        270.0
    )

    assert result["fire_bearing_sin"] == pytest.approx(
        -1.0,
        abs=0.01,
    )

    assert result["fire_bearing_cos"] == pytest.approx(
        0.0,
        abs=0.01,
    )

    # All three fires are within 200 km.
    assert result["active_fire_count_200km"] == 3

    assert result["total_frp_200km"] > 0.0


def test_aggregate_fire_features_excludes_future_fires():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 11:00:00+00:00",
                    "2026-09-25 12:00:00+00:00",
                    "2026-09-25 13:00:00+00:00",
                ]
            ),
            "latitude": [
                0.0,
                0.0,
                0.0,
            ],
            "longitude": [
                1.0,
                0.5,
                0.25,
            ],
            "frp_mw": [
                100.0,
                200.0,
                300.0,
            ],
        }
    )

    result = aggregate_fire_features_200km(
        location_latitude=0.0,
        location_longitude=0.0,
        fire_detections=fire_detections,
        issue_time=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
    )

    # Only the 11:00 fire is available.
    assert result["active_fire_count_200km"] == 1
    assert result["total_frp_200km"] > 0.0


def test_aggregate_fire_features_returns_sentinels_when_no_nearby_fire():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 10:00:00+00:00",
                ]
            ),
            "latitude": [10.0],
            "longitude": [10.0],
            "frp_mw": [100.0],
        }
    )

    result = aggregate_fire_features_200km(
        location_latitude=0.0,
        location_longitude=0.0,
        fire_detections=fire_detections,
        issue_time=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
    )

    assert result["nearest_fire_dist_km"] == 9999.0
    assert result["fire_bearing_deg"] is None
    assert result["fire_bearing_sin"] == 0.0
    assert result["fire_bearing_cos"] == 0.0
    assert result["total_frp_200km"] == 0.0
    assert result["active_fire_count_200km"] == 0


def test_aggregate_fire_features_returns_sentinels_when_no_previous_fire():
    fire_detections = pd.DataFrame(
        {
            "detected_at": pd.to_datetime(
                [
                    "2026-09-25 13:00:00+00:00",
                ]
            ),
            "latitude": [0.0],
            "longitude": [1.0],
            "frp_mw": [100.0],
        }
    )

    result = aggregate_fire_features_200km(
        location_latitude=0.0,
        location_longitude=0.0,
        fire_detections=fire_detections,
        issue_time=pd.Timestamp(
            "2026-09-25 12:00:00+00:00"
        ),
    )

    assert result["nearest_fire_dist_km"] == 9999.0
    assert result["fire_bearing_deg"] is None
    assert result["total_frp_200km"] == 0.0
    assert result["active_fire_count_200km"] == 0
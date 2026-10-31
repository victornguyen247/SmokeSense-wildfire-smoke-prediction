"""Spatial feature calculations for GEO-01."""

from __future__ import annotations

import math

import numpy as np

import pandas as pd

EARTH_RADIUS_KM = 6371.008


def haversine_distance_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """Return great-circle distance between two WGS84 coordinates in km."""
    lat1 = math.radians(latitude_1)
    lat2 = math.radians(latitude_2)

    delta_lat = math.radians(latitude_2 - latitude_1)
    delta_lon = math.radians(longitude_2 - longitude_1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def bearing_degrees(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """
    Return initial bearing from point 1 to point 2.

    Bearing convention:
        0   = north
        90  = east
        180 = south
        270 = west
    """
    lat1 = math.radians(latitude_1)
    lat2 = math.radians(latitude_2)

    delta_lon = math.radians(longitude_2 - longitude_1)

    x = math.sin(delta_lon) * math.cos(lat2)

    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1)
        * math.cos(lat2)
        * math.cos(delta_lon)
    )

    bearing = math.degrees(math.atan2(x, y))

    return (bearing + 360) % 360


def angular_difference_degrees(
    angle_1: float,
    angle_2: float,
) -> float:
    """Return the smallest absolute difference between two bearings."""
    difference = abs(angle_1 - angle_2) % 360

    return min(difference, 360 - difference)


def wind_alignment_degrees(
    fire_to_location_bearing: float,
    wind_from_direction: float,
) -> float:
    """
    Return angular alignment between smoke transport and fire-to-location.

    Weather wind direction normally describes where the wind comes FROM.
    Smoke transport therefore travels in the opposite direction.

    0°   = wind transports smoke directly toward the location
    90°  = perpendicular
    180° = wind transports smoke directly away
    """
    wind_to_direction = (wind_from_direction + 180) % 360

    return angular_difference_degrees(
        fire_to_location_bearing,
        wind_to_direction,
    )

def nearest_previous_fire_features(
    location_latitude: float,
    location_longitude: float,
    fire_detections,
    timestamp,
) -> dict:
    """Return spatial features for the nearest fire available before timestamp."""

    fires = fire_detections[
        fire_detections["detected_at"] < timestamp
    ].copy()

    if fires.empty:
        return {
            "fire_distance_km": None,
            "fire_bearing_deg": None,
            "fire_frp_mw": None,
        }

    distances = []

    for _, fire in fires.iterrows():
        distance = haversine_distance_km(
            location_latitude,
            location_longitude,
            fire["latitude"],
            fire["longitude"],
        )
        distances.append(distance)

    fires["distance_km"] = distances

    nearest = fires.loc[
        fires["distance_km"].idxmin()
    ]

    bearing = bearing_degrees(
        location_latitude,
        location_longitude,
        nearest["latitude"],
        nearest["longitude"],
    )

    return {
        "fire_distance_km": nearest["distance_km"],
        "fire_bearing_deg": bearing,
        "fire_frp_mw": nearest["frp_mw"],
    }

def aggregate_fire_features_200km(
    location_latitude: float,
    location_longitude: float,
    fire_detections,
    issue_time,
    radius_km: float = 200.0,
    lookback_hours: float = 72.0,
) -> dict:
    """ 
    Aggregate recent fire detections before issue_time within radius_km.

    Only fire detections within lookback_hours before issue_time
    are included. Detections at or after issue_time are excluded
    to prevent future leakage.

    Returns:
        nearest_fire_dist_km:
            Distance to the nearest available fire.

        fire_bearing_deg:
            Bearing from the forecast location to the nearest fire.
        fire_bearing_sin / fire_bearing_cos:
            Circular encoding of the nearest fire bearing.

        total_frp_200km:
            Distance-decayed FRP from all fires within radius_km.

        active_fire_count_200km:
            Number of recent fire detections within radius_km
            and within the lookback window.

    Only detections within lookback_hours before issue_time are included.
    Detections at or after issue_time are excluded to prevent future leakage.

    Distance-decay:
        weight = 1 - distance_km / radius_km

    Therefore:
        0 km   -> 100% FRP
        50 km  -> 75% FRP
        100 km -> 50% FRP
        150 km -> 25% FRP
        200 km -> 0% FRP
    """
    lookback_start = issue_time - pd.Timedelta(hours=lookback_hours)

    fires = fire_detections[
        (fire_detections["detected_at"] >= lookback_start)
        & (fire_detections["detected_at"] < issue_time)
    ].copy()

    if fires.empty:
        return {
            "nearest_fire_dist_km": 9999.0,
            "fire_bearing_deg": None,
            "fire_bearing_sin": 0.0,
            "fire_bearing_cos": 0.0,
            "total_frp_200km": 0.0,
            "active_fire_count_200km": 0,
        }

    location_lat = math.radians(location_latitude)
    fire_lats = np.radians(fires["latitude"].to_numpy(dtype=float))
    delta_lats = fire_lats - location_lat
    delta_lons = np.radians(
        fires["longitude"].to_numpy(dtype=float) - location_longitude
    )
    a = (
        np.sin(delta_lats / 2) ** 2
        + math.cos(location_lat)
        * np.cos(fire_lats)
        * np.sin(delta_lons / 2) ** 2
    )
    distances = 2 * EARTH_RADIUS_KM * np.arctan2(
        np.sqrt(a), np.sqrt(1 - a)
    )
    nearby_positions = np.flatnonzero(distances <= radius_km)

    if not len(nearby_positions):
        return {
            "nearest_fire_dist_km": 9999.0,
            "fire_bearing_deg": None,
            "fire_bearing_sin": 0.0,
            "fire_bearing_cos": 0.0,
            "total_frp_200km": 0.0,
            "active_fire_count_200km": 0,
        }

    nearest_position = nearby_positions[
        np.argmin(distances[nearby_positions])
    ]
    nearest = fires.iloc[nearest_position]
    nearest_distance = distances[nearest_position]

    nearest_bearing = bearing_degrees(
        location_latitude,
        location_longitude,
        nearest["latitude"],
        nearest["longitude"],
    )

    bearing_radians = math.radians(nearest_bearing)

    nearby_distances = distances[nearby_positions]
    nearby_frp = (
        fires.iloc[nearby_positions]["frp_mw"].fillna(0.0).to_numpy()
    )
    total_frp = np.sum(
        nearby_frp * (1.0 - nearby_distances / radius_km)
    )

    return {
        "nearest_fire_dist_km": nearest_distance,
        "fire_bearing_deg": nearest_bearing,
        "fire_bearing_sin": math.sin(bearing_radians),
        "fire_bearing_cos": math.cos(bearing_radians),
        "total_frp_200km": total_frp,
        "active_fire_count_200km": len(nearby_positions),
    }

"""Leakage and sanity checks for DATA-04 rows, run against the input frames they came from.

Each check recomputes a feature independently on a sample of rows and raises
LeakageError on any mismatch:

  fires    active_fire_count_200km = detections with issue_time - 72 h <= detected_at < issue_time
           within 200 km (a detection at or after issue_time must never count)
  weather  values come from the point's nearest station, latest valid_at <= issue_time, <= 3 h old
  lags     pm25_lag_Nh = the point's own monitor at exactly issue_time - N h (strictly before)
  target   target_time = issue_time + horizon, target_pm25 = the target monitor at target_time
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LAGS = (1, 3, 6, 12, 24)
FIRE_RADIUS_KM = 200.0
WEATHER_MAX_AGE = pd.Timedelta(hours=3)
EARTH_KM = 6371.008


class LeakageError(AssertionError):
    pass


def _km(lat, lon, lats, lons):
    p1, p2 = np.radians(lat), np.radians(lats)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lons - lon) / 2) ** 2
    return 2 * EARTH_KM * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def _same(a, b) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) < 1e-4


def check_fires(rows: pd.DataFrame, fires: pd.DataFrame, lookback_hours: float = 72.0) -> int:
    det = pd.to_datetime(fires["detected_at"], utc=True)
    lat, lon = fires["latitude"].to_numpy(float), fires["longitude"].to_numpy(float)
    for r in rows.itertuples(index=False):
        t = r.issue_time
        in_time = ((det >= t - pd.Timedelta(hours=lookback_hours)) & (det < t)).to_numpy()
        n = int((_km(r.location_lat, r.location_lon, lat[in_time], lon[in_time]) <= FIRE_RADIUS_KM).sum())
        if n != int(r.active_fire_count_200km):
            raise LeakageError(f"fires: {r.forecast_point_id} {t}: count {r.active_fire_count_200km}, "
                               f"recomputed from detections before issue_time {n}")
    return len(rows)


def check_weather(rows: pd.DataFrame, weather: pd.DataFrame) -> int:
    if weather.empty:
        bad = rows[rows["temp_c"].notna()]
        if len(bad):
            raise LeakageError("weather: values present without any weather input")
        return len(rows)
    stations = weather.dropna(subset=["latitude", "longitude"]).drop_duplicates("station_id")
    w = weather.assign(valid_at=pd.to_datetime(weather["valid_at"], utc=True)).sort_values("valid_at")
    nearest = {}
    for r in rows.itertuples(index=False):
        if r.forecast_point_id not in nearest:
            d = _km(r.location_lat, r.location_lon, stations["latitude"].to_numpy(float),
                    stations["longitude"].to_numpy(float))
            nearest[r.forecast_point_id] = stations.iloc[int(np.argmin(d))]["station_id"]
        s = w[(w["station_id"] == nearest[r.forecast_point_id]) & (w["valid_at"] <= r.issue_time)]
        last = s.iloc[-1] if len(s) else None
        if last is None or r.issue_time - last["valid_at"] > WEATHER_MAX_AGE:
            if pd.notna(r.temp_c) or pd.notna(r.wind_speed_ms):
                raise LeakageError(f"weather: {r.forecast_point_id} {r.issue_time}: value without a report "
                                   "in the 3 h before issue_time")
            continue
        for col in ("temp_c", "wind_speed_ms", "rh_pct"):
            if not _same(getattr(r, col), last[col]):
                raise LeakageError(f"weather: {r.forecast_point_id} {r.issue_time}: {col} {getattr(r, col)} "
                                   f"!= latest report at or before issue_time ({last['valid_at']}) {last[col]}")
    return len(rows)


def check_lags(rows: pd.DataFrame, history: pd.DataFrame) -> int:
    h = history.assign(issue_time=pd.to_datetime(history["issue_time"], utc=True))
    h = h.drop_duplicates(["forecast_point_id", "issue_time"]).set_index(["forecast_point_id", "issue_time"])["pm25"]
    for r in rows.itertuples(index=False):
        for lag in LAGS:
            want = h.get((r.forecast_point_id, r.issue_time - pd.Timedelta(hours=lag)), np.nan)
            got = getattr(r, f"pm25_lag_{lag}h")
            if not _same(got, want):
                raise LeakageError(f"lags: {r.forecast_point_id} {r.issue_time}: pm25_lag_{lag}h {got} != "
                                   f"own monitor at issue_time - {lag} h ({want})")
    return len(rows)


def check_targets(rows: pd.DataFrame, observations: pd.DataFrame) -> int:
    issue = pd.to_datetime(rows["issue_time"], utc=True)
    target = pd.to_datetime(rows["target_time"], utc=True)
    if not (target == issue + pd.to_timedelta(rows["horizon_hours"].astype(int), unit="h")).all():
        raise LeakageError("target: target_time != issue_time + horizon_hours")
    o = observations.assign(valid_at=pd.to_datetime(observations["valid_at"], utc=True))
    o = o.drop_duplicates(["monitor_id", "valid_at"]).set_index(["monitor_id", "valid_at"])["pm25"]
    for r in rows.itertuples(index=False):
        want = o.get((r.target_monitor_id, r.target_time), np.nan)
        if not _same(r.target_pm25, want):
            raise LeakageError(f"target: {r.forecast_point_id} {r.target_time}: target_pm25 {r.target_pm25} "
                               f"!= {r.target_monitor_id} at target_time ({want})")
    return len(rows)


def check_event(rows: pd.DataFrame, frames: dict, sample: int = 400, seed: int = 0) -> dict:
    """Run every check on a sample of one event's rows; returns rows checked per check."""
    s = rows.sample(min(sample, len(rows)), random_state=seed) if len(rows) else rows
    return {
        "fires": check_fires(s, frames["fires"]),
        "weather": check_weather(s, frames["weather"]),
        "lags": check_lags(s, frames["pm25_history"]),
        "target": check_targets(s, frames["pm25_observations"]),
    }

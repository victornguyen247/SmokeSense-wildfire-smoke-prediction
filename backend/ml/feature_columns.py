"""Model input columns for the baseline v1 models (docs/data-decisions.md #23).

FEATURES is the only list the training and inference code read. EXCLUDED lists
the dataset columns that must never be a feature, with the reason.
"""

FIRE = ["nearest_fire_dist_km", "fire_bearing_sin", "fire_bearing_cos", "total_frp_200km",
        "active_fire_count_200km"]
WEATHER = ["wind_alignment", "wind_speed_ms", "wind_dir_sin", "wind_dir_cos", "temp_c", "rh_pct",
           "pressure_hpa", "precip_1h_mm"]
PM25_LAGS = ["pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h"]
CALENDAR = ["day_of_year", "month", "smoke_season", "local_solar_hour"]

FEATURES = [*FIRE, *WEATHER, *PM25_LAGS, *CALENDAR, "horizon_hours"]

EXCLUDED = {
    "target_pm25": "the label",
    "target_time": "label timing; issue_time + horizon",
    "target_source": "label provenance",
    "target_monitor_id": "label provenance",
    "target_monitor_dist_km": "label provenance",
    "forecast_point_id": "identifier; would memorise sites",
    "location_lat": "site position; would memorise sites across events",
    "location_lon": "site position; would memorise sites across events",
    "event_ids": "event bookkeeping",
    "pilot_event_id": "event bookkeeping; unknown at inference",
    "event_tier": "derived from the labels (max in-box peak)",
    "group_id": "CV grouping",
    "precip_prob_pct": "always null (observed weather has no probability)",
    "fire_bearing_deg": "kept as fire_bearing_sin / fire_bearing_cos (circular)",
    "issue_time": "timestamp; calendar features carry its signal",
}

TARGET = "target_pm25"

# Baseline v2 (docs/data-decisions.md #29): v1 features plus persistence-derived features,
# computed by ml.features.add_derived in both training and inference.
DERIVED = ["persistence", "trend_1_3", "trend_1_6", "ratio_1_24"]
FEATURES_V2 = [*FEATURES, *DERIVED]

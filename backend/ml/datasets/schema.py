"""Strict DATA-04 dtypes and GEO-01 v1 label policy."""
from __future__ import annotations

import numpy as np
import pandas as pd

from features.validation import REQUIRED_COLUMNS, validate_feature_dataset

# Keep in sync with the PM-01 contract before releasing v1.
FLOAT32_COLUMNS = (
    "location_lat", "location_lon", "target_pm25", "target_monitor_dist_km",
    "nearest_fire_dist_km", "fire_bearing_deg", "fire_bearing_sin",
    "fire_bearing_cos", "total_frp_200km", "wind_alignment", "wind_speed_ms",
    "wind_dir_sin", "wind_dir_cos", "temp_c", "rh_pct", "pressure_hpa",
    "precip_1h_mm", "precip_prob_pct", "pm25_lag_1h", "pm25_lag_3h",
    "pm25_lag_6h", "pm25_lag_12h", "pm25_lag_24h", "local_solar_hour",
)
INTEGER_COLUMNS = (
    "horizon_hours", "active_fire_count_200km", "day_of_year", "month",
)
STRING_COLUMNS = ("forecast_point_id", "pilot_event_id", "target_source")
TIMESTAMP_COLUMNS = ("issue_time", "target_time")
OPTIONAL_COLUMNS = {"target_monitor_id"}  # GEO-01 currently emits this extra field.
ALLOWED_COLUMNS = set(REQUIRED_COLUMNS) | OPTIONAL_COLUMNS


def cast_and_validate(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert to explicit types, reject drift, and apply v1 regulatory-only policy."""
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    unexpected = set(frame.columns) - ALLOWED_COLUMNS
    if missing or unexpected:
        raise ValueError(f"Schema mismatch: missing={sorted(missing)}, unexpected={sorted(unexpected)}")
    if frame.empty:
        raise ValueError("Feature dataset is empty")
    result = frame.copy()
    for col in TIMESTAMP_COLUMNS:
        try:
            result[col] = pd.to_datetime(result[col], utc=True, errors="raise")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid UTC timestamp in {col}") from exc
    for col in FLOAT32_COLUMNS:
        try:
            numeric = pd.to_numeric(result[col], errors="raise")
            if np.isinf(numeric.to_numpy(dtype="float64", na_value=np.nan)).any():
                raise ValueError("Infinity is not a valid feature")
            result[col] = numeric.astype("float32")
            if np.isinf(result[col].to_numpy(dtype="float64", na_value=np.nan)).any():
                raise ValueError("Out of float32 range")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid float32 values in {col}: {exc}") from exc
    for col in INTEGER_COLUMNS:
        try:
            numeric = pd.to_numeric(result[col], errors="raise")
            finite = numeric.dropna().astype("float64")
            if not np.isfinite(finite.to_numpy()).all() or (finite % 1 != 0).any():
                raise ValueError("Not finite integral values")
            result[col] = numeric.astype("Int32")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid integer values in {col}: {exc}") from exc
    for col in STRING_COLUMNS:
        result[col] = result[col].astype("string")
    if "target_monitor_id" in result.columns:
        result["target_monitor_id"] = result["target_monitor_id"].astype("string")
    # Source GEO-01 emits boolean June–October smoke_season values.
    if not result["smoke_season"].dropna().isin([True, False, 0, 1]).all():
        raise ValueError("smoke_season must be boolean")
    result["smoke_season"] = result["smoke_season"].astype("boolean")
    required_nonnull = ("forecast_point_id", "pilot_event_id", "issue_time",
                        "target_time", "horizon_hours", "target_pm25", "target_source")
    for col in required_nonnull:
        if result[col].isna().any():
            raise ValueError(f"Nulls not allowed in {col}")
    for col in ("forecast_point_id", "pilot_event_id", "target_source"):
        if result[col].str.strip().eq("").any():
            raise ValueError(f"Blank values not allowed in {col}")
    if not result["target_source"].eq("regulatory").all():
        raise ValueError("DATA-04 v1: PurpleAir labels are prohibited; target_source must be regulatory")
    if not np.isfinite(result["target_pm25"].to_numpy(dtype="float64")).all():
        raise ValueError("Non-finite target_pm25 label")
    if result["target_pm25"].lt(0).any():
        raise ValueError("Negative target_pm25 label")
    # Match the shared GEO-01 structural checks after dtype casting.
    validate_feature_dataset(result)
    return result

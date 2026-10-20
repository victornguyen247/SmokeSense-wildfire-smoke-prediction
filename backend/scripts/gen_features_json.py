"""Write docs/ml/features.json: the baseline_v2 serving feature contract (PM-03).

    python scripts/gen_features_json.py            # rewrite docs/ml/features.json
    python scripts/gen_features_json.py --check    # exit 1 if the file is stale

The feature list and its order come from ml.feature_columns.FEATURES_V2, so the file
cannot drift from the model. SPEC below adds what that module does not carry (dtype, unit,
null rule, training and live definitions); tests/test_serving_contract.py fails if SPEC
and FEATURES_V2 disagree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from ml.feature_columns import DERIVED, EXCLUDED, FEATURES_V2  # noqa: E402

OUT = BACKEND.parent / "docs" / "ml" / "features.json"
HORIZONS = [1, 3, 6, 12, 24]

FIRES = "fire_detections, satellite = 'VIIRS_SNPP' (live rows come from VIIRS_SNPP_NRT, normalised to the same tag)"
FIRE_WINDOW = ("detections with issue_time - 72 h <= detected_at < issue_time, within 200 km "
               "(haversine) of the forecast point")
NO_FIRE = "no fire in the window: 9999.0 / 0.0 / 0.0 / 0.0 / 0 (see null_rule)"
WX = "nearest weather station to the point (fixed per point); latest report with issue_time - 3 h <= valid_at <= issue_time"
WX_TRAIN = f"weather_observations (NCEI Global Hourly, ingestion/connectors/ncei.py); {WX}"
WX_LIVE = f"weather_observations (NWS station observations, DATA-06); {WX}; same station ids (ICAO)"
LAG_TRAIN = ("AirNow regulatory RawConcentration at the point's own monitor, observation valid_at exactly "
             "issue_time - {h} h (time offsets applied at ingest, values in [-5, 0) clamped to 0); null if no such hour")
LAG_LIVE = ("same query against observations (correction = 'regulatory'); for a grid cell there is no monitor, so grid "
            "cells are never fed to the model (Stage B interpolates forecasts, not features)")

# name -> (dtype, unit, null_rule, training definition, live definition)
SPEC: dict[str, tuple[str, str, str, str, str]] = {
    "nearest_fire_dist_km": ("float32", "km", "never null; 9999.0 when no fire in the window",
                             f"distance to the closest of the {FIRE_WINDOW}", f"identical; source {FIRES}"),
    "fire_bearing_sin": ("float32", "unitless", "never null; 0.0 when no fire in the window",
                         "sin of the initial bearing (deg from north) point -> nearest fire",
                         "identical"),
    "fire_bearing_cos": ("float32", "unitless", "never null; 0.0 when no fire in the window",
                         "cos of the initial bearing (deg from north) point -> nearest fire", "identical"),
    "total_frp_200km": ("float32", "MW", "never null; 0.0 when no fire in the window",
                        f"sum over the {FIRE_WINDOW} of frp_mw (null frp = 0) x (1 - distance_km / 200)",
                        "identical"),
    "active_fire_count_200km": ("int16", "count", "never null; 0 when no fire in the window",
                                f"number of {FIRE_WINDOW}", "identical"),
    "wind_alignment": ("float32", "unitless, -1..1", "null when wind direction or fire bearing is null",
                       f"cos(fire_bearing_deg - wind_dir_deg); {WX_TRAIN}",
                       f"identical formula; {WX_LIVE}"),
    "wind_speed_ms": ("float32", "m/s", "null when no report in the 3 h window",
                      f"wind speed of the selected report; {WX_TRAIN}",
                      f"NWS windSpeed, converted to m/s from its unitCode (wmoUnit:km_h-1 divides by 3.6); {WX_LIVE}"),
    "wind_dir_sin": ("float32", "unitless", "null when direction is null (calm wind, speed 0, has no direction)",
                     "sin(wind_dir_deg), direction the wind blows FROM", "identical; NWS windDirection; "
                     "set direction null whenever wind_speed_ms == 0, as NCEI does for calm"),
    "wind_dir_cos": ("float32", "unitless", "null when direction is null (calm wind)",
                     "cos(wind_dir_deg)", "identical; same calm rule"),
    "temp_c": ("float32", "degC", "null when no report in the 3 h window", f"air temperature; {WX_TRAIN}",
               f"NWS temperature (degC); {WX_LIVE}"),
    "rh_pct": ("float32", "%", "null when temperature or dew point is null",
               "relative_humidity_from_dewpoint(temp_c, dewpoint_c) in ingestion/normalize.py",
               "same function applied to NWS temperature and dewpoint; do not use NWS relativeHumidity"),
    "pressure_hpa": ("float32", "hPa", "null when the report has no sea-level pressure (~54% of training rows)",
                     "sea-level pressure (ISD SLP); null if <= 800", "NWS seaLevelPressure / 100 (Pa -> hPa); "
                     "never barometricPressure (station pressure); null if missing or <= 800"),
    "precip_1h_mm": ("float32", "mm", "null when the report has no 1 h accumulation (~59% of training rows); "
                     "null is not 0", "ISD AA1-AA4 1 h accumulation", "NWS precipitationLastHour in mm; keep "
                     "null as null"),
    "pm25_lag_1h": ("float32", "ug/m3", "null when the monitor has no reading at that hour", LAG_TRAIN.format(h=1),
                    LAG_LIVE),
    "pm25_lag_3h": ("float32", "ug/m3", "null when the monitor has no reading at that hour", LAG_TRAIN.format(h=3),
                    "identical to pm25_lag_1h"),
    "pm25_lag_6h": ("float32", "ug/m3", "null when the monitor has no reading at that hour", LAG_TRAIN.format(h=6),
                    "identical to pm25_lag_1h"),
    "pm25_lag_12h": ("float32", "ug/m3", "null when the monitor has no reading at that hour",
                     LAG_TRAIN.format(h=12), "identical to pm25_lag_1h"),
    "pm25_lag_24h": ("float32", "ug/m3", "null when the monitor has no reading at that hour",
                     LAG_TRAIN.format(h=24), "identical to pm25_lag_1h"),
    "day_of_year": ("int16", "day", "never null", "issue_time (UTC) day of year", "identical"),
    "month": ("int8", "month", "never null", "issue_time (UTC) month", "identical"),
    "smoke_season": ("bool", "flag", "never null", "month in 6..10 (June to October)", "identical"),
    "local_solar_hour": ("float32", "hour, [0, 24)", "never null",
                         "(UTC hour + minute / 60 + second / 3600 + longitude / 15) mod 24, longitude of the "
                         "forecast point", "identical, using the monitor's longitude"),
    "horizon_hours": ("int8", "hour", "never null", f"one of {HORIZONS}; set by the caller per model",
                      "predict_v2.predict sets it from its horizon argument; do not supply it"),
    "persistence": ("float64", "ug/m3", "null only when lag_1h, lag_3h and lag_6h are all null",
                    "ml.features.persistence: lag_1h, else lag_3h, else lag_6h", "derived by add_derived; do not supply"),
    "trend_1_3": ("float64", "ug/m3", "null when lag_1h or lag_3h is null", "pm25_lag_1h - pm25_lag_3h",
                  "derived by add_derived; do not supply"),
    "trend_1_6": ("float64", "ug/m3", "null when lag_1h or lag_6h is null", "pm25_lag_1h - pm25_lag_6h",
                  "derived by add_derived; do not supply"),
    "ratio_1_24": ("float64", "unitless", "null when lag_1h or lag_24h is null",
                   "(pm25_lag_1h + 1) / (pm25_lag_24h + 1)", "derived by add_derived; do not supply"),
}


def build() -> dict:
    features = []
    for position, name in enumerate(FEATURES_V2):
        dtype, unit, null_rule, training, live = SPEC[name]
        features.append({
            "position": position, "name": name, "dtype": dtype, "unit": unit,
            "kind": "derived" if name in DERIVED else ("caller_sets_horizon" if name == "horizon_hours" else "input"),
            "null_rule": null_rule, "training_definition": training, "live_definition": live,
        })
    return {
        "contract": "baseline_v2 serving features",
        "generated_from": "backend/ml/feature_columns.py (FEATURES_V2); regenerate with backend/scripts/gen_features_json.py",
        "horizons": HORIZONS,
        "input_columns": [f["name"] for f in features if f["kind"] == "input"],
        "features": features,
        "excluded": EXCLUDED,
        "example_row": {
            "forecast_point_id": "<forecast_points.id of a monitor point>", "issued_at": "2026-10-13T18:00:00Z",
            "nearest_fire_dist_km": 34.2, "fire_bearing_sin": 0.64, "fire_bearing_cos": -0.77, "total_frp_200km": 812.5,
            "active_fire_count_200km": 143, "wind_alignment": 0.91, "wind_speed_ms": 3.6, "wind_dir_sin": -0.5,
            "wind_dir_cos": 0.866, "temp_c": 29.4, "rh_pct": 18.0, "pressure_hpa": None, "precip_1h_mm": None,
            "pm25_lag_1h": 62.0, "pm25_lag_3h": 48.0, "pm25_lag_6h": 35.0, "pm25_lag_12h": 22.0, "pm25_lag_24h": 18.0,
            "day_of_year": 286, "month": 10, "smoke_season": True, "local_solar_hour": 10.2,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if ap.parse_args().check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is stale; run python scripts/gen_features_json.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

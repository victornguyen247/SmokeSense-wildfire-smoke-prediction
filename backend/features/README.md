# Feature dataset

`alignment.py` builds one row per forecast point, issue time, and forecast
horizon. It combines temporal features, recent fire detections, PM2.5 history,
weather, and a PM2.5 target label. The resulting dataframe is checked against
the GEO-01 Parquet contract in `validation.py`.

## Inputs and timing

- Fire detections are filtered to the 200 km radius and the 72 hours before
  `issue_time`. A detection at `issue_time` or later is excluded. Callers can
  override the `lookback_hours` parameter when a different window is needed.
- PM2.5 lag features use observations before `issue_time`.
- Labels match `target_time` and select the nearest eligible monitor within
  25 km. Regulatory observations are eligible for any `qa_flag`; a
  `purpleair_barkjohn` observation requires `qa_flag == "ok"`. Raw PurpleAir
  observations are not eligible.
- Weather features use the nearest NCEI station, selected by distance from the
  forecast point to station coordinates included with `weather_observations`.
  For that station, the latest `valid_at` at or before `issue_time` is used;
  an exact-time observation is allowed. This mapping is derived during feature
  building, so the empty `point_weather_map` table is not needed for DATA-04.
- NCEI precipitation is measured in millimeters (`precip_1h_mm`). It is kept
  separate from `precip_prob_pct`, which remains null because observations do
  not provide forecast probabilities. Station coordinates should be selected
  from each observation's stored geometry when loading the dataframe.

## Main entry point

Use `build_feature_dataset(...)` from `alignment.py`. Supply forecast points,
issue times, fire detections, PM2.5 history, NCEI weather observations, and
target observations as dataframes. The weather observation dataframe needs
station ID, timestamp, station latitude and longitude, and the measured
weather columns. `horizons` defaults to the supported
GEO-01 horizons, while `lookback_hours` defaults to 72.

The output includes weather columns even when no weather match is available;
unmatched weather values remain null. Rows without an eligible PM2.5 target
are dropped.

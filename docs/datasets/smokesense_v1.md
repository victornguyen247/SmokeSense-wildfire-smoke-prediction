# Dataset card: smokesense_v1

| | |
|---|---|
| Version | 1.0.0 |
| Built | 2026-10-12, by `python -m dataset_build.build_v1` (backend/) |
| Files | `backend/data/datasets/smokesense_v1/data.parquet` and `manifest.json` (not in git; the manifest holds the git commit and SHA-256 of the data and of `backend/docs/pilot_events.json`) |
| Rows | 141,954 |
| Rules | `docs/data-decisions.md` #11–#22, #32 |
| Models | [baseline_v1](../models/baseline_v1.md) (direct XGBoost) and [baseline_v2](../models/baseline_v2.md) (persistence-anchored; the released model) |
| Reproduce | `backend/scripts/reproduce_data04.sh` rebuilds the dataset, checks its sha256, retrains v1 and v2, and compares metrics ([DATA-04 acceptance](DATA-04-acceptance.md)) |

## Purpose

Training and evaluation data for the SmokeSense PM2.5 forecaster (DATA-04). Each row is one prediction moment: a California AirNow monitor (the forecast point), an hourly issue time, and a horizon of 1, 3, 6, 12 or 24 h. The features are fire, weather, PM2.5-lag and calendar features, all known at the issue time. The label is the regulatory PM2.5 at `issue_time + horizon`.

The columns follow the Parquet contract in `docs/schema.md` and `backend/features/validation.py`, with these additions: `precip_1h_mm`, `target_monitor_id`, `event_ids`, `event_tier` and `group_id`. Every row passed `validate_feature_dataset`. Each event's rows were also checked for leakage on a sample of up to 400 rows (`backend/dataset_build/checks.py`):
- fires counted only if detected before `issue_time`;
- weather from the nearest station's latest report at or before `issue_time`, at most 3 h old;
- lags taken strictly before `issue_time`;
- `target_time = issue_time + horizon`, and the label matches the target monitor at `target_time`.

## How it is built

- **Forecast points (#18):** per event, AirNow monitors with valid regulatory PM2.5 inside the tight bbox during the event, and in California scope (#17). Ashland Fire Dept (Oregon, PE-011) is excluded. Morongo School (tribal, California) is kept. AQS codes come from `monitors.aqs_code` (#32, migration 0003). Older rows were filled by `scripts/backfill_monitor_aqs_code.py`. `backend/dataset_build/airnow_sites.csv` is only a fallback, used with a warning. Rebuilding from the DB column gave a byte-identical file (sha256 `6799c405…`).
- **Issue times (#19):** every UTC hour from the event's start 00:00 to its end 23:00.
- **Inputs (#20):**
  - VIIRS SNPP fire detections over bbox + 200 km, from 72 h before the start.
  - Regulatory AirNow PM2.5 over the tight bbox, from 24 h before the start to 24 h after the end.
  - NCEI weather over bbox + 50 km, from 24 h before the start.
- **Dedupe (#21):** one row per (point, issue time, horizon). 1,873 rows came from two events; they keep the first event's features, and `event_ids` lists both.
- **Groups (#21):** `group_id` joins events whose windows overlap, for leave-one-group-out CV (#22).

## Events

| Event | Tier | Group | Forecast points | Rows built | Rows kept (as `pilot_event_id`) |
|---|---|---|---|---|---|
| PE-001 August Complex | high | G-PE-001 | 2 | 19,673 | 19,673 |
| PE-002 Dixie | high-medium | G-PE-002 | 1 | 12,047 | 12,047 |
| PE-003 Mendocino Complex | high-medium | G-PE-003 | 1 | 6,250 | 6,250 |
| PE-004 Park | high | G-PE-004 | 3 | 32,809 | 32,809 |
| PE-005 SCU Lightning Complex | high-medium | G-PE-001 | 6 | 11,469 | 11,469 |
| PE-006 Soberanes | high-medium | G-PE-006 | 2 | 3,315 | 3,315 |
| PE-007 Glass | high-medium | G-PE-001 | 1 | 2,855 | 2,855 |
| PE-008 Carr | high | G-PE-003 | 1 | 3,507 | 3,507 |
| PE-009 Rabbit | high-medium | G-PE-009 | 2 | 2,400 | 2,400 |
| PE-010 Woolsey | medium-low | G-PE-010 | 6 | 10,075 | 10,075 |
| PE-011 Klamathon | medium-low | G-PE-011 | 1 | 1,675 | 1,675 |
| PE-012 Creek | high | G-PE-001 | 2 | 26,655 | 26,655 |
| PE-013 Zogg | high | G-PE-001 | 2 | 3,863 | 1,990 (Red Bluff rows kept under PE-001) |
| PE-014 River | low | G-PE-002 | 2 | 480 | 480 |
| PE-015 Sheep | low | G-PE-015 | 2 | 720 | 720 |
| PE-016 Chimney | low | G-PE-016 | 1 | 1,626 | 1,626 |
| PE-017 Mosquito | low | G-PE-017 | 1 | 360 | 360 |
| PE-018 Lake | low | G-PE-018 | 1 | 1,675 | 1,675 |
| PE-019 LNU Complex | medium-low | G-PE-001 | 1 | 240 | 240 |
| PE-020 Crews | low | G-PE-020 | 2 | 2,133 | 2,133 |

Rows built are short of points × hours × 5 wherever the label is missing: no reading from the point's own monitor, and no other monitor within 25 km, at `target_time`.

## Row counts

| Group | Events | Rows | Share |
|---|---|---|---|
| G-PE-001 | PE-001, PE-005, PE-007, PE-012, PE-013, PE-019 | 62,882 | 44.3% |
| G-PE-004 | PE-004 | 32,809 | 23.1% |
| G-PE-002 | PE-002, PE-014 | 12,527 | 8.8% |
| G-PE-010 | PE-010 | 10,075 | 7.1% |
| G-PE-003 | PE-003, PE-008 | 9,757 | 6.9% |
| G-PE-006 | PE-006 | 3,315 | 2.3% |
| G-PE-009 | PE-009 | 2,400 | 1.7% |
| G-PE-020 | PE-020 | 2,133 | 1.5% |
| G-PE-011 | PE-011 | 1,675 | 1.2% |
| G-PE-018 | PE-018 | 1,675 | 1.2% |
| G-PE-016 | PE-016 | 1,626 | 1.1% |
| G-PE-015 | PE-015 | 720 | 0.5% |
| G-PE-017 | PE-017 | 360 | 0.3% |

| Horizon | 1 h | 3 h | 6 h | 12 h | 24 h |
|---|---|---|---|---|---|
| Rows | 28,384 | 28,385 | 28,388 | 28,396 | 28,401 |

## Labels

`target_pm25`, in µg/m³, AirNow `RawConcentration`. 35.5 is the EPA 2024 "Unhealthy for Sensitive Groups" breakpoint.

| Tier | Rows | Mean | p50 | p95 | % rows ≥ 35.5 |
|---|---|---|---|---|---|
| high | 84,634 | 26.35 | 10.0 | 99.0 | 19.99 |
| high-medium | 38,336 | 22.09 | 12.0 | 76.0 | 16.96 |
| medium-low | 11,990 | 12.43 | 8.0 | 37.0 | 5.52 |
| low | 6,994 | 9.95 | 7.0 | 23.0 | 2.49 |
| **all** | 141,954 | 23.21 | 10.0 | 84.0 | 17.09 |

97.8% of labels come from the forecast point's own monitor (distance 0). The rest come from the nearest other monitor within 25 km.

## Null rate per feature

| Feature | Null % | Why |
|---|---|---|
| `precip_prob_pct` | 100.0 | Observations carry no forecast probability (by design, `features/README.md`). |
| `precip_1h_mm` | 58.71 | NCEI has no 1-hour precipitation group in dry hours; stored as null, not 0. |
| `pressure_hpa` | 53.91 | Many stations do not report sea-level pressure. |
| `wind_alignment` | 35.46 | Needs a wind direction and a fire bearing. |
| `wind_dir_sin`, `wind_dir_cos` | 34.73 | Calm (speed 0, no direction: 87% of these when speed is present) and variable winds. |
| `rh_pct` | 7.30 | No report in the 3 h before issue time, or no dew point. |
| `temp_c` | 7.16 | No report in the 3 h before issue time. |
| `wind_speed_ms` | 4.59 | No report in the 3 h before issue time. |
| `pm25_lag_24h` / `12h` / `6h` / `3h` / `1h` | 4.38 / 4.09 / 3.96 / 3.86 / 3.76 | Missing hours at the point's monitor (e.g. PE-008's lead day). |
| `fire_bearing_deg` | 1.07 | No fire within 200 km in the last 72 h: 1,512 rows, with `nearest_fire_dist_km` = 9999. |
| `nearest_fire_dist_km`, `total_frp_200km`, `active_fire_count_200km`, `fire_bearing_sin`, `fire_bearing_cos`, `local_solar_hour`, `day_of_year`, `month`, `smoke_season` | 0.0 | Sentinels or zeros when there is no fire. |

## Caveats

- **Preliminary labels.** Labels are AirNow preliminary data (`RawConcentration`), not validated AQS values.
- **Timing at Red Bluff.** Red Bluff (06-103-0007) time offsets are applied (`airnow_time_offsets.py`). PE-001 and PE-013 are stored at label − 1 h. PE-004 has no offset.
- **Unverified timing elsewhere.** The Lone Pine and Tahoe City offsets are unverified (`docs/data-sources.md`, "seen but not encoded"); neither site is a forecast point in v1. Sites without an AQS counterpart, for example the tribal site Morongo School, have unverified timing.
- **No PurpleAir.** PurpleAir labels come in v1.1 (#12).
- **SNPP-only fire features.** Fire features use VIIRS SNPP only (#11, #13), the sensor live inference uses. NOAA-20 and MODIS rows are in the DB but not in these features.
- **PE-008 starts without lags.** Weaverville has no AirNow values on 2018-07-30, so the first 24 h of PE-008 have null `pm25_lag_*`.
- **The 2020 group dominates.** G-PE-001 holds 44% of rows. Weight or stratify accordingly.
- **Intended CV.** Use leave-one-group-out on `group_id` (#22). Events in one group share hours and smoke.
- **Observed weather, not forecasts.** Weather features are observed NCEI weather at or before the issue time, from the nearest station (DATA-04, #31). They are not NWS forecasts valid at the target time. `docs/schema.md` now says so (#33).
- **File location.** The Parquet file lives in `backend/data/datasets/smokesense_v1/`, as `docs/schema.md` now documents (#33).

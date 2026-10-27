# Scope freeze (PM-04)

Status: DRAFT for team review and the advisor. Owner: Tin. Issue: #51. Plan: #62.

## 1. The rule
This is what ships on 12/8. After the freeze, any new request needs something else cut (section 8).

## 2. MVP
A person enters a California ZIP, or clicks the map, and sees a 1-24 h PM2.5 smoke forecast computed from live data, with active fires, sensors and wind on the map. The app says it is an experimental model, not an official warning.

Serving approach (MVP): monitor-first plus interpolation. baseline_v2 runs at California AirNow monitors exactly as trained (its lags are the monitor's own readings). A grid cell's forecast is an inverse-distance-weighted blend of nearby monitor forecasts, shown with its distance to the nearest monitor. Details: docs/ml/serving-contract.md. A grid-native model (ML-02, #43) replaces interpolation only if it wins on held-out monitors.

## 3. In scope: Phases 2-3 (gate 11/6)
Status as of 2026-10-27.

| Item | Issue | Owner | Status |
|---|---|---|---|
| API contract | #41 | Shresta | closed |
| Serving contract | #42 | Miaoqing, Phuong, Vuong | closed |
| Grid-native experiment (time-boxed; if unfinished, keep interpolation) | #43 | Miaoqing | open |
| Error analysis and poster figures, plus a breakdown of errors by recent rain | #44 | Miaoqing | open |
| Inference adapter (wraps predict_v2) | #45 | Miaoqing | open |
| Register baseline_v2 and pass the model gate | #46 | Miaoqing (sign-off Tin) | open |
| California grid and ZIP lookup | #47 | Phuong | closed |
| Live monitor features and interpolation to grid | #48 | Phuong | open |
| Model registry (S3/R2 and local) | #49 | Vuong | open, PR #68 |
| Staging environment | #50 | Vuong | open |
| Live ingestion (FIRMS SNPP, AirNow, NWS) | #52 | Tin | closed |
| Hourly forecast pipeline | #53 | Vuong | open |
| API skeleton, forecast, fires, observations, /meta | #54, #55, #56 | Shresta | #54 open, PRs #82, #83; #55 open; #56 open |
| Map shell, forecast layer, fires/sensors/wind layers, location search | #57, #58, #59, #60 | Malije | #57 closed; #58, #59, #60 open |
| Vertical-slice demo on staging | #61 | Vuong, Tin | open |

## 4. In scope after Phase 3 (Phases 4-5): proposals, owners to confirm
| Item | What | Owner (proposed) | Supports |
|---|---|---|---|
| City AQ History | A secondary view: a city's multi-year PM2.5 trend, seasonal smoke pattern and unhealthy-air days per year; needs a backfill of past years from EPA AQS (the rollup tables exist but are empty; today we hold only the pilot-event windows and the ~72 h live window). Fallback if the backfill doesn't fit: show only the cities and years covered by the pilot events | Tin (data), Malije (UI) | Problem and data |
| Alerts (in-app) | A flag when a forecast exceeds 35.5 ug/m3 (provisional threshold). Email/SMS delivery is stretch | Shresta (API), Malije (UI) | Live demo |
| HRRR-Smoke benchmark | An offline comparison with NOAA's HRRR-Smoke forecast for a few events, for the report and poster, not a live feature | Miaoqing, Phuong (grid matching) | Model and evaluation |

Each gets an issue before the freeze is announced (drafts are in the PR description).

## 5. Out of scope
- EV feature (the electric-vehicle feature from the original proposal [ADD ONE LINE ON WHAT IT WAS]). One line for the advisor: it is outside the core question (smoke forecasts for California 1-24 h ahead) and would need data sources and design we don't have, with no owner and no time before the 11/29 code freeze.
- Live PurpleAir (dropped 2026-10-26, decision #41). It is not a model input and not served live. A one-off historical pull for training labels stays a stretch item.
- MLflow or a model-serving platform. Models are versioned in S3/R2 plus model_versions (OPS-02, #49).
- Anywhere outside California. Horizons other than 1, 3, 6, 12 and 24 h.
- Official or regulatory use of the forecasts.
- [PROPOSED] Hosting after Senior Design Day. Record the demo (PM-05) instead; revisit if someone funds it.

## 6. Stretch (dropped before any in-scope item; if time is short, drop in this order)
1. Gridded rain source (radar or HRRR): needs a 2016+ archive and the same source live.
2. Email/SMS alert delivery.
3. Rain accumulation features in a v2.1 experiment, only if the rain breakdown in ML-03 shows errors in rain hours.
4. Dataset v1.1: PurpleAir labels to fill monitor gaps, more high-smoke events outside 2020, validated AQS labels.
5. Model v2.1: wider alert cut-off grid, max(persistence, v2) for alerts, a loss that targets severe smoke (v2 under-predicts at 125.5 ug/m3 and above, and 2020 is 44% of the rows).
6. HRRR-Smoke benchmark, if the team moves it here from section 4.
7. Grid-native model replacing interpolation, only if ML-02 wins.

## 7. Traceability: poster and demo
| Poster / demo section | Items |
|---|---|
| Problem and data | DATA-03/04 (done), DATA-06, City AQ History |
| Model and evaluation | baseline_v2, ML-01 as Baseline B (PR #66 merged, PR #87 open), ML-03 figures, ML-05 gate. Headline: 6 h, 13-fold leave-one-group-out, against persistence |
| Live system demo | Staging, API, map, pipeline, alerts, the recorded demo (PM-05) |
| Limits we state | Severe smoke is under-predicted, 2020 is 44% of the rows, AirNow labels are preliminary, the ML-01 test split is thin (94.6% one event (PR #87, open)) |

## 8. Change control
A new request becomes an issue labelled scope-change that names what gets cut or moved. Tin and Vuong decide in the weekly meeting and the advisor is told in writing. If it is not approved, it goes to stretch.

## 9. Dates and gates
10/30 Phase 2 due. 11/6 Phase 3 gate (PM-05, #61: at least 24 consecutive hourly pipeline runs on staging, a ZIP gives a real forecast, no mock data). About 11/29 code freeze. 12/4 poster, slides and script. 12/8 project complete. 12/9 final report. 12/11 Senior Design Day.

## 10. Risks
- The 11/6 gate needs 24 consecutive hourly runs, so the pipeline (#53) must be running on staging by about 11/4-11/5.
- The live chain depends on merges: DATA-06 (#85) and GEO-02 (#65) are merged; what is left is #48 (GEO-03) then #53, with #68 before #45 and #46.
- Cost: staging on AWS with short test deploys, and the Neon free-tier size. Store grid forecasts for the latest run only. Open decision for Vuong before OPS-04: forecast retention 7-14 days (proposed, for the Neon free tier) vs 30 days (docs/schema.md).
- Review capacity: 17 open issues, and pair reviews are needed.
- City AQ History depends on an EPA AQS multi-year backfill (owner Tin); if it is not done by about 11/20, use the fallback.

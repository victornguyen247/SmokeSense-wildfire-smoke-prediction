# Scope freeze (PM-04)

Status: FROZEN 2026-10-27 (decided by Tin with Vuong's delegation). Changes go through section 8.

Owner: Tin. Issue: #51. Plan: #62.

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

## 4. In scope after Phase 3 (Phases 4-5)
| Item | Issue | What | Owner | Supports |
|---|---|---|---|---|
| Email alerts | #90 | Email alerts for registered users: a user registers an email and location; the system emails them when their location is forecast Unhealthy for Sensitive Groups (PM2.5 >= 35.5 ug/m3, EPA 2024 AQI) at 1, 3, 6, 12 or 24 h. Alert category: Unhealthy for Sensitive Groups (PM2.5 >= 35.5 ug/m3, EPA 2024 AQI). Trigger: the forecast passes that horizon's served cut-off in the active model's release.json (baseline_v2: 35.5 / 29.5 / 25.5 / 21.5 / 20.0 ug/m3 at 1 / 3 / 6 / 12 / 24 h; 1 h uses persistence). Chosen because it catches about 74% of real events at 6 h vs about 57% with a fixed 35.5 (baseline_v2 gate note); cut-offs update when the model is retrained. Minimal design: a subscriptions table (email, ZIP or rounded point, confirmed, token); subscribe, double opt-in confirm, one-click unsubscribe; one job after each hourly run, at most one email per user per episode; console mail backend on staging and the demo, a real provider only if time allows; subscriber data deleted at teardown; fallback: an in-app warning on the location card. The public statewide map stays. | Tin (backend), Malije (UI) | Live demo |

Issues filed 2026-10-27 (DATA-07, API-08, ML-06).

## 5. Out of scope
- EV feature (the electric-vehicle feature in the original proposal): out. It is outside the core question (smoke forecasts for California 1-24 h ahead), would need data sources and design we don't have, and has no owner or time before the 11/29 code freeze.
- SMS alerts.
- Live PurpleAir (dropped 2026-10-26, decision #41). It is not a model input and not served live. A one-off historical pull for training labels stays a stretch item.
- MLflow or a model-serving platform. Models are versioned in S3/R2 plus model_versions (OPS-02, #49).
- Anywhere outside California. Horizons other than 1, 3, 6, 12 and 24 h.
- Official or regulatory use of the forecasts.
- Hosting after Senior Design Day: out. The demo is recorded (PM-05) instead.

## 6. Stretch (dropped before any in-scope item; if time is short, drop in this order)
1. City AQ History (#89): monthly average PM2.5 per city from grid points (Tin, Malije). Moved 2026-10-31: a live-only view would hold about 1 month of model estimates by 12/8, and the poster's "Problem and data" uses the observed pilot-event AirNow data.
2. HRRR-Smoke benchmark (#91): an offline comparison with NOAA's HRRR-Smoke forecast for a few events, for the report and poster (Miaoqing, Phuong). Moved 2026-10-30 to make room for email alerts (change rule, section 8).
3. Gridded rain source (radar or HRRR): needs a 2016+ archive and the same source live.
4. Rain accumulation features in a v2.1 experiment, only if the rain breakdown in ML-03 shows errors in rain hours.
5. Dataset v1.1: PurpleAir labels to fill monitor gaps, more high-smoke events outside 2020, validated AQS labels.
6. Model v2.1: wider alert cut-off grid, max(persistence, v2) for alerts, a loss that targets severe smoke (v2 under-predicts at 125.5 ug/m3 and above, and 2020 is 44% of the rows).
7. Grid-native model replacing interpolation, only if ML-02 wins.

## 7. Traceability: poster and demo
| Poster / demo section | Items |
|---|---|
| Problem and data | DATA-03/04 (done), DATA-06, observed AirNow data for the pilot events |
| Model and evaluation | baseline_v2, ML-01 as Baseline B (PR #66 merged, PR #87 open), ML-03 figures, ML-05 gate. Headline: 6 h, 13-fold leave-one-group-out, against persistence |
| Live system demo | Staging, API, map, pipeline, alerts, the recorded demo (PM-05) |
| Limits we state | Severe smoke is under-predicted, 2020 is 44% of the rows, AirNow labels are preliminary, the ML-01 test split is thin: 94.6% of test rows are one event (PR #87, open) |

## 8. Change control
A new request becomes an issue labelled scope-change that names what gets cut or moved. Tin and Vuong decide in the weekly meeting and the advisor is told in writing. If it is not approved, it goes to stretch.

## 9. Dates and gates
10/30 Phase 2 due. 11/6 Phase 3 gate (PM-05, #61: at least 24 consecutive hourly pipeline runs on staging, a ZIP gives a real forecast, no mock data). About 11/29 code freeze. 12/4 poster, slides and script. 12/8 project complete. 12/9 final report. 12/11 Senior Design Day.

## 10. Risks
- The 11/6 gate needs 24 consecutive hourly runs, so the pipeline (#53) must be running on staging by about 11/4-11/5.
- The live chain depends on merges: DATA-06 (#85) and GEO-02 (#65) are merged; what is left is #48 (GEO-03) then #53, with #68 before #45 and #46.
- Cost: staging on AWS with short test deploys, and the Neon free-tier size. Decided: monitor forecasts are kept 30 days (docs/schema.md; needed to score forecasts against observations); grid forecasts keep only the latest run (about 354k rows a day otherwise). OPS-04 (#53) implements this.
- Review capacity: 17 open issues, and pair reviews are needed.
- Email alerts store personal data (email + location): minimal design, delete on teardown.
- If email slips: in-app warning fallback.

## 11. Decisions taken with this freeze
- Forecast retention: monitor forecasts are kept 30 days (docs/schema.md; needed to score forecasts against observations); grid forecasts keep only the latest run (about 354k rows a day otherwise). OPS-04 (#53) implements this.
- Phase 4-5 owners: City AQ History: Tin, Malije; Alerts: Shresta, Malije; HRRR-Smoke benchmark: Miaoqing, Phuong.
- No hosting after Senior Design Day; the demo is recorded.
- Scope is frozen; changes go through section 8.
- Rain: the error breakdown by rain in ML-03 (#44) comes first; rain features go into a v2.1 experiment only if that shows an effect.
- ML-01 trees are re-saved with scikit-learn 1.6.0 (release v1.0.1, not yet published); the repo pin stays.
- 2026-10-30 (Vuong's review of #88): email alerts for registered users are in scope (SMS out); City AQ History uses monthly city averages from grid points, no EPA AQS backfill; the HRRR-Smoke benchmark moves to stretch.
- 2026-10-31 (agreed with Vuong): City AQ History moves to stretch; email alerts get the minimal design in section 4, owners Tin (backend) and Malije (UI); the alert threshold is to be decided by team vote.
- 2026-11-02 (team vote, option B; team delegated the decision to Tin): email alerts trigger when the forecast passes that horizon's served cut-off in the active model's release.json, not a fixed 35.5 (section 4).
- Merge order: #86 (merged), then #68, #87, #88.

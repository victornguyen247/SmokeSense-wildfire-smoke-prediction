# Data decisions

A dated log of decisions about training data for the pilot events. The evidence for
each entry is in `backend/scripts/pilot_verification/` (`rules_final.py`,
`events_final.py`, `reports/final_check.md`, `reports/candidates_check.md`).

## 2026-10-10 — pilot event rules (owner: Tin, data)

| # | Decision | Reason |
|---|---|---|
| 1 | **Monitor scope.** Training labels come from AirNow sites inside each event's bbox. The AQS sites within 50 km listed in PR #21's check are a reference only. | Training rows need hourly labels from sites inside the event's box; a peak at an AQS site 50 km away does not describe the box. |
| 2 | **40 km rule.** The nearest in-box AirNow site must be ≤ 40 km from the event's own FIRMS detections. | Beyond 40 km the box has no monitor close enough to see this fire's smoke. |
| 3 | **Widening rule.** If the nearest AirNow site within 40 km of the fire is outside the computed bbox, the bbox widens symmetrically along the needed axis or axes, just enough to include it plus 0.05°. The site and its distance are recorded as `bbox_adjust`. There are no hand-set bboxes. | This replaces the hand widening PE-001 needed in PR #26 with a rule that applies to every event. |
| 4 | **Tier rule.** The tier comes from the max peak daily mean over in-box sites (LST days with ≥ 18 h), against the EPA 2024 AQI PM2.5 breakpoints (`TIER_RANGES`). That site is the tier site. | The tier should reflect the worst smoke any in-box monitor measured, not the site with the most hours or a reputation. |
| 5 | **Elevation rule.** For non-Low tiers, the tier site's peak must be ≥ 2× its baseline and ≥ 10 µg/m³ above it. The baseline is the median of the 7 pre-start LST days with ≥ 18 h. With fewer than 3 such days, it is the 20th percentile of the site's in-window daily means. | A high tier has to come from this fire raising PM2.5, not from an already-smoky background. |
| 6 | **75% hours rule.** The best in-box site must report ≥ 75% of the window's hours. | Below that, too many hours have no label. |
| 7 | **20% other-fire rule.** Less than 20% of in-box FRP may come from other fires. | Above that, labels in the box can't be attributed to this fire.<br>PE-009 (18.3%) and PE-020 (19.2%) are near the limit; accepted because FIRMS `_SP` is final reprocessed data. |
| 8 | **PE-008 Carr window is 2018-07-31 → 2018-08-30** (was from 2018-07-23). | Weaverville was dark on the top-quartile days 07-26, 07-28, 07-29 and 07-30. The later start raises its hours from 74.0% to 93.1%. |
| 9 | **Relabels:** PE-002 Dixie High → High-Medium; PE-004 Park High-Medium → High; PE-007 Glass High → High-Medium; PE-013 Zogg Medium-Low → High; PE-019 LNU Low → Medium-Low. | These are the tiers the max in-box AirNow peaks give under rule 4. PE-013's regional-smoke exception in PR #21 doesn't survive a computed tier. |
| 10 | **Replacements:** PE-016 Rim (2013) → Chimney Fire (2016-08-13 → 08-26, San Luis Obispo). PE-017 Caldor early phase → Mosquito Fire first three days (2022-09-06 → 09-08, Placer/El Dorado). | Rim and Caldor have no AirNow site inside their tight box (nearest: San Andreas, 49.7 and 40.8 km). Chimney and Mosquito were the picks of `screen_candidates.py`: they pass every rule with tier Low and clash with no other event's window within 200 km. |
| 11 | **NOAA-21 and MODIS are excluded from fire features.** | The only live FIRMS path, `ingestion.firms_poc` (`backend/ingestion/tasks.py:96-99`), requests `VIIRS_SNPP_NRT` only, so training must use the same sensor. |
| 12 | **PurpleAir is deferred to v1.1.** v1 uses regulatory labels only. | PurpleAir point balance is unknown and an event listing costs ~5k points; v1 ships on regulatory labels and PurpleAir Barkjohn labels come in v1.1. |
| 13 | **Fire features use VIIRS SNPP only:** `_SP` archive in training, NRT in live inference. Ingestion keeps storing every `_SP` product tagged by satellite; the DATA-04 loader filters to SNPP. | Train/serve parity; SNPP is the only VIIRS sensor covering every event (SP from 2012); adding NOAA-20 later needs no re-ingest. |

## 2026-10-12 — ingestion windows, AQS codes and forecast-point scope (owner: Tin, data)

| # | Decision | Reason |
|---|---|---|
| 14 | **AirNow pulls the tight bbox over [start − 24 h, end + 24 h]** (`AIRNOW_LEAD_HOURS`, `AIRNOW_TAIL_HOURS`), with the existing time-offset padding. | The first hours of an event need PM2.5 lags back to `pm25_lag_24h`, and the last hours need labels up to the 24 h horizon (`max(ALLOWED_HORIZONS)`). |
| 15 | **NCEI pulls bbox + 50 km over [start − 24 h, end]** (`NCEI_MARGIN_KM`, `NCEI_LEAD_HOURS`). | Live inference uses the nearest station wherever it is, so training must see stations just outside the box. The weather join needs reports from before the first issue time. |
| 16 | **AirNow AQS codes are normalized to 9 digits** (`normalize_aqs_code`) before the monitor id and the time-offset lookup. | AirNow sends some sites with an `840` country prefix (Paradise, Auburn). Without normalization, a site could split into two monitors, and Red Bluff's offset would not apply to a prefixed code. |
| 17 | **DATA-04 forecast points are California AirNow monitors only (AQS state code 06).** Out-of-state in-box sites stay in the DB but are not forecast points. | The project scope is California, and live inference serves California points. |


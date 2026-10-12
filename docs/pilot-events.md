# SmokeSense — Pilot Fire Events
**docs/pilot-events.md** · PM-01 deliverable

The event config, `backend/docs/pilot_events.json`, is the source of truth for event ids, windows, tiers, bboxes and monitors. The rules it was built under are in [`docs/data-decisions.md`](data-decisions.md) (cited below as #1–#13), and the evidence for each event is in `backend/scripts/pilot_verification/reports/final_check.md`. This doc describes the same 20 events; where the two disagree, the config wins.

---

## Selection criteria

Events were selected to satisfy the PM-01 acceptance criteria:

- **≥ 3 geographic regions** within California: Northern CA, Sierra Nevada / Foothills, Bay Area / Central Coast, Southern CA
- **All four intensity tiers** represented: high, high-medium, medium-low, low
- **Data availability** for FIRMS, AirNow and NWS across each event's date window — tracked per event in the [Data-availability verification](#data-availability-verification) table below. PurpleAir is deferred to v1.1 (#12); v1 labels come from regulatory monitors only.
- **Bbox**: each event's bbox is centred on the FRP-weighted centroid of its FIRMS `_SP` cluster, with the cluster's FRP-weighted 98th-percentile extent plus a 25 km buffer. It is widened only to reach the nearest AirNow site within 40 km of the fire (#3). The config holds each bbox and how it was derived.
- **Monitor rules** (#1, #2, #6): training labels come from AirNow sites **inside the event's bbox**. The nearest in-box site must be ≤ 40 km from the event's own FIRMS detections, and the best in-box site must report ≥ 75% of the window's hours.
- **Other fires** (#7): less than 20% of in-box FRP may come from other fires, so labels in the box can be attributed to this fire.
- **Label-level proximity rule**: individual training rows still follow `docs/schema.md` — a label is only used when its monitor is **≤ 25 km** from the forecast point (`target_monitor_dist_km ≤ 25`). Forecast points for each event must therefore be placed near the in-box monitors, not at the fire.
- **FIRMS products** (#11, #13): fire features use **VIIRS-SNPP only** — the `_SP` archive in training, NRT in live inference — because the live FIRMS path requests `VIIRS_SNPP_NRT` only. Ingestion still stores MODIS and VIIRS-NOAA20 `_SP` detections, tagged by satellite, but the training loader filters to SNPP. VIIRS-NOAA21 is excluded.
- **NWS offices** below are the Weather Forecast Office (WFO) IDs whose grids cover the affected counties: EKA = Eureka, STO = Sacramento, REV = Reno, MFR = Medford, MTR = San Francisco Bay Area/Monterey, HNX = Hanford/San Joaquin Valley, LOX = Los Angeles/Oxnard, SGX = San Diego.

---

## Intensity definitions

Tiers are assigned by **observed smoke impact at in-box AirNow monitors**, not by fire size — acreage is shown only as typical context (some low-impact events, such as PE-016 Chimney and PE-018 Lake, are mid-sized fires whose smoke barely registered at monitors). PM2.5 thresholds use the **EPA 2024 AQI breakpoints**, matching `shared/aqi.py` and `docs/schema.md`.

| Tier | Peak AQI impact (in-box monitors) | Peak PM2.5 daily avg (EPA 2024) | Typical acreage (context only) |
|---|---|---|---|
| **High** | AQI > 200 (Very Unhealthy or worse), multi-county | > 125.4 µg/m³ | > 300,000 acres |
| **High-Medium** | AQI 151–200 (Unhealthy), regional | 55.5 – 125.4 µg/m³ | 50,000 – 300,000 acres |
| **Medium-Low** | AQI 101–150 (Unhealthy for Sensitive Groups), localised | 35.5 – 55.4 µg/m³ | 10,000 – 80,000 acres |
| **Low** | AQI ≤ 100 (Moderate or better at most monitors) | ≤ 35.4 µg/m³ | any — small fires, or large fires with limited smoke reaching monitors |

The tier is computed, not assigned (#4): it comes from the highest peak daily mean (local-standard-time days with ≥ 18 valid hours) at any in-box AirNow site, against the breakpoints above. That site is the event's **tier site**. For non-Low tiers, the tier site's peak must also be ≥ 2× its pre-event baseline and ≥ 10 µg/m³ above it (#5), so a high tier comes from this fire and not from an already-smoky background. An event that fails a rule is replaced. So is an event whose computed tier would leave a tier with fewer than 3 events, or would defeat the reason it was chosen (e.g. a "low impact" case that measures High). Every swap is recorded in the [replacement log](#replacements).

---

## Tier 1 — High Impact (5 events)

### PE-001 · August Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-001` |
| **Region** | Northern California (Trinity, Tehama, Glenn, Lake, Mendocino counties) |
| **Start date** | 2020-08-16 (CAL FIRE alarm date; was 2020-08-17) |
| **End date** | 2020-11-12 |
| **Acres burned** | ~1,032,648 (California's first gigafire) |
| **FIRMS archive** | VIIRS-SNPP SP: 66,359 detections in the bbox and window. Also stored, not used for features: MODIS SP 14,134, VIIRS-NOAA20 SP 67,600 |
| **AirNow sites in box** | Willows-Colusa `06-021-0003` — tier site (peak 145.2 µg/m³, 2020-09-11), nearest site (18.9 km from the fire detections) and best site (99.4% of hours). Also in box: Red Bluff - Walnut office. The bbox was widened to reach Willows-Colusa (#3) |
| **PurpleAir density** | Moderate (2020 — density growing in NorCal) |
| **NWS grid** | EKA (Eureka — Trinity, Mendocino, Lake), STO (Sacramento — Tehama, Glenn) |
| **NWS station** | KRDD (Redding) |
| **Why chosen** | California's largest recorded fire by area. Smoke affected the entire state for weeks. Extreme FRP and extended duration make this the hardest training case. Multi-county, multi-NWS-grid coverage tests the spatial interpolation logic. |

---

### PE-004 · Park Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-004` |
| **Region** | Northern California (Butte, Tehama counties) |
| **Start date** | 2024-07-24 |
| **End date** | 2024-10-24 |
| **Acres burned** | ~429,603 (4th largest CA fire on record) |
| **FIRMS archive** | VIIRS-SNPP SP: 3,685 detections in the bbox and window. Also stored, not used for features: MODIS SP 2,839, VIIRS-NOAA20 SP 9,630 |
| **AirNow sites in box** | Paradise - Clark Road `06-007-2003` — tier site (peak 138.1 µg/m³, 2024-07-31). Chico - East `06-007-0008` — nearest site (4.1 km from the fire detections) and best site (99.1% of hours). Also in box: Red Bluff - Walnut office |
| **PurpleAir density** | Excellent (2024 — dense coverage) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Most recent major fire in the dataset, so it checks the pipeline on current-era FIRMS and AirNow data. Three AirNow sites sit in the box, one only 4 km from the fire, giving dense labels close to a very large fire. Best PurpleAir density in the set, for when PurpleAir labels arrive in v1.1. *(Re-tiered from High-Medium to High on 2026-10-10, #9: the in-box tier site, Paradise - Clark Road, peaked at 138.1 µg/m³. PR #21's High-Medium came from Chico-East alone, 85.2 µg/m³ in AQS. The earlier reason for choosing it — all three VIIRS sensors, with NOAA-21 from the NRT archive — no longer applies, since fire features use VIIRS-SNPP only, #11 and #13.)* |

---

### PE-008 · Carr Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-008` |
| **Region** | Northern California (Shasta, Trinity counties) |
| **Start date** | 2018-07-31 (was 2018-07-23; see below) |
| **End date** | 2018-08-30 |
| **Acres burned** | ~229,651 |
| **FIRMS archive** | VIIRS-SNPP SP: 9,758 detections in the bbox and window. Also stored, not used for features: MODIS SP 2,583, VIIRS-NOAA20 SP 9,471 |
| **AirNow sites in box** | Weaverville `06-105-0002` — tier site (peak 134.0 µg/m³, 2018-08-08), nearest site (11.9 km from the fire detections) and best site (93.1% of hours). The only in-box AirNow site |
| **PurpleAir density** | Sparse (2018) |
| **NWS grid** | STO (Sacramento — Shasta), EKA (Eureka — Trinity) |
| **Why chosen** | Generated a rare fire tornado (pyrotornado). Extreme fire behaviour makes FRP readings unusually high — tests model robustness to outlier fire intensity values. Also concurrent with Mendocino Complex, providing another multi-fire test case. *(Start moved from 2018-07-23 to 2018-07-31 on 2026-10-10, #8: Weaverville was dark on the top-quartile days 07-26 and 07-28 to 07-30, and the later start raises its hours from 74.0% to 93.1%. The baseline for the elevation rule is the 20th percentile of in-window daily means, since no pre-start day had ≥ 18 hours.)* |

---

### PE-012 · Creek Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-012` |
| **Region** | Sierra Nevada (Fresno, Madera counties) |
| **Start date** | 2020-09-04 |
| **End date** | 2020-12-24 |
| **Acres burned** | ~379,895 |
| **FIRMS archive** | VIIRS-SNPP SP: 40,517 detections in the bbox and window. Also stored, not used for features: MODIS SP 7,518, VIIRS-NOAA20 SP 41,094 |
| **AirNow sites in box** | Yosemite Village - Visitor Center `06-043-1001` — tier site (peak 613.2 µg/m³, 2020-09-17) and nearest site (28.1 km from the fire detections). Clovis - N. Villa Ave `06-019-5001` — best site (99.6% of hours) |
| **PurpleAir density** | Moderate (Central Valley growing by 2020) |
| **NWS grid** | HNX (Hanford/Central Valley) |
| **Why chosen** | Sierra Nevada fire — different terrain and smoke channelling than valley or coastal fires. Smoke funnelled into the San Joaquin Valley, producing sustained Unhealthy-or-worse concentrations in Fresno rather than a single acute peak. Tests the model on valley-trapped smoke scenarios. *(Moved from Medium-Low during review, then to High on 2026-10-09; the in-box tier site, Yosemite Village, peaked at 613.2 µg/m³.)* |

---

### PE-013 · Zogg Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-013` |
| **Region** | Northern California (Shasta, Trinity counties) |
| **Start date** | 2020-09-27 |
| **End date** | 2020-10-15 |
| **Acres burned** | ~56,338 |
| **FIRMS archive** | VIIRS-SNPP SP: 1,681 detections in the bbox and window. Also stored, not used for features: MODIS SP 374, VIIRS-NOAA20 SP 1,396 |
| **AirNow sites in box** | Weaverville `06-105-0002` — tier site (peak 125.8 µg/m³, 2020-10-02), nearest site (31.7 km from the fire detections) and best site (87.5% of hours). Also in box: Red Bluff - Walnut office |
| **PurpleAir density** | Sparse (rural Shasta area) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Moderate-size fire burning at the same time as the Glass and August Complex fires — a three-fire concurrent case. Important for testing `total_frp_200km` (the weighted multi-fire feature) as the model must attribute smoke to the correct source. *(Re-tiered from Medium-Low to High on 2026-10-10, #9. Weaverville's peak, 125.8 µg/m³, is 6.8× its pre-event baseline of 18.5, and other fires account for 0.6% of in-box FRP. PR #21 had kept Medium-Low because the High readings coincided with a regional smoke rise; that exception does not survive a computed tier. Separating Zogg's share from the regional smoke remains the point of the event.)* |

---

## Tier 2 — High-Medium Impact (6 events)

### PE-002 · Dixie Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-002` |
| **Region** | Northern California (Plumas, Butte, Lassen, Shasta, Tehama counties) |
| **Start date** | 2021-07-13 |
| **End date** | 2021-10-25 |
| **Acres burned** | ~963,309 (California's largest single-ignition fire) |
| **FIRMS archive** | VIIRS-SNPP SP: 62,382 detections in the bbox and window. Also stored, not used for features: MODIS SP 13,870, VIIRS-NOAA20 SP 66,054 |
| **AirNow sites in box** | Chico - East `06-007-0008` — tier site (peak 102.8 µg/m³, 2021-08-07), nearest site (34.6 km from the fire detections) and best site (95.6% of hours). The only in-box AirNow site |
| **PurpleAir density** | Good (2021 — dense coverage in Chico / Sacramento corridor) |
| **NWS grid** | STO (Sacramento — Butte, Shasta, Tehama, western Plumas), REV (Reno — Lassen, eastern Plumas) |
| **Why chosen** | California's largest single-ignition fire. Smoke plume reached the East Coast. Strong HRRR-Smoke benchmark data available for this period. Good for testing the model against the operational benchmark (proposal §6.3). *(Re-tiered from High to High-Medium on 2026-10-10, #9: the only in-box AirNow site, Chico - East, peaked at 102.8 µg/m³. PR #21's High came from AQS sites next to the fire, such as Chester, which are not in-box AirNow sites.)* |

---

### PE-003 · Mendocino Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-003` |
| **Region** | Northern California (Mendocino, Lake, Colusa, Glenn counties) |
| **Start date** | 2018-07-27 |
| **End date** | 2018-09-18 |
| **Acres burned** | ~459,123 (largest CA fire at the time) |
| **FIRMS archive** | VIIRS-SNPP SP: 16,272 detections in the bbox and window. Also stored, not used for features: MODIS SP 4,597, VIIRS-NOAA20 SP 16,310 |
| **AirNow sites in box** | Ukiah Library `06-045-0006` — tier site (peak 59.5 µg/m³, 2018-08-08), nearest site (9.4 km from the fire detections) and best site (96.5% of hours). The only in-box AirNow site |
| **PurpleAir density** | Sparse (2018 — limited NorCal density, rely on AirNow) |
| **NWS grid** | EKA (Eureka — Mendocino, Lake), STO (Sacramento — Colusa, Glenn), MTR (Bay Area — downwind impact) |
| **Why chosen** | Pre-PurpleAir-density era (2018) — tests model performance with regulatory-only labels. Smoke heavily impacted the Bay Area, providing urban downwind impact case. *(Re-tiered from High to High-Medium on 2026-10-09; the in-box tier site, Ukiah Library, peaked at 59.5 µg/m³.)* |

---

### PE-005 · SCU Lightning Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-005` |
| **Region** | Bay Area / Diablo Range (Santa Clara, Alameda, Contra Costa, San Joaquin, Stanislaus counties) |
| **Start date** | 2020-08-16 (CAL FIRE alarm date; was 2020-08-18) |
| **End date** | 2020-08-31 (shortened from 2020-09-22; see below) |
| **Acres burned** | ~396,624 |
| **FIRMS archive** | VIIRS-SNPP SP: 9,601 detections in the bbox and window. Also stored, not used for features: MODIS SP 2,261, VIIRS-NOAA20 SP 9,412 |
| **AirNow sites in box** | TracyAP `06-077-3005` — tier site (peak 117.5 µg/m³, 2020-08-24). San Jose - Knox Ave `06-085-0006` — nearest site (5.8 km from the fire detections). Modesto - 14th Street `06-099-0005` — best site (99.7% of hours). Also in box: San Jose - Jackson St., Gilroy - 9th Street, Santa Cruz AMS |
| **PurpleAir density** | Excellent (Bay Area has highest PurpleAir density in California) |
| **NWS grid** | MTR (Bay Area — Santa Clara, Alameda, Contra Costa), STO (Sacramento — San Joaquin, Stanislaus) |
| **Why chosen** | Urban interface fire directly adjacent to the Bay Area. Six in-box AirNow sites, the most of any event, give the richest label set and test urban dispersion patterns. Concurrent with August Complex — tests multi-fire interaction features. *(Window shortened to 08-16–08-31 and re-tiered from High to High-Medium on 2026-10-09: in the old window, the High readings came from other fires — CZU smoke near San Lorenzo Valley and Bay Area–wide regional smoke on 2020-09-11, when SCU was largely burned out. Within the shortened window, other fires account for 0.1% of in-box FRP.)* |

---

### PE-006 · Soberanes Fire (first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-006` |
| **Region** | Central Coast (Monterey County — Big Sur / Carmel Valley) |
| **Start date** | 2016-07-22 |
| **End date** | 2016-08-04 (training window; the fire burned until 2016-10-13) |
| **Acres burned** | ~132,104 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP SP: 3,005 detections in the bbox and window. Also stored, not used for features: MODIS SP 792 |
| **AirNow sites in box** | Carmel Valley AMS `06-053-0002` — tier site (peak 63.8 µg/m³, 2016-07-26), nearest site (5.9 km from the fire detections) and best site (98.8% of hours). Also in box: Salinas AMS |
| **PurpleAir density** | Sparse (2016 — pre-density era; regulatory labels only) |
| **NWS grid** | MTR (Bay Area / Monterey) |
| **Why chosen** | Coastal-mountain fire with a monitor sitting in the downwind valley: Carmel Valley peaked at 63.8 µg/m³ on 2016-07-26, inside the High-Medium band. Other fires account for 0.0% of in-box FRP, so the peak is attributable to this fire. Adds Central Coast coverage and a pre-PurpleAir baseline. *(Replaces the original PE-006, Valley Fire 2015, whose measured impact was Low, not High-Medium. See the replacement log below.)* |

---

### PE-007 · Glass Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-007` |
| **Region** | Northern California (Napa, Sonoma counties) |
| **Start date** | 2020-09-27 |
| **End date** | 2020-10-20 |
| **Acres burned** | ~67,484 |
| **FIRMS archive** | VIIRS-SNPP SP: 2,431 detections in the bbox and window. Also stored, not used for features: MODIS SP 659, VIIRS-NOAA20 SP 2,099 |
| **AirNow sites in box** | Sebastopol `06-097-0004` — tier site (peak 58.9 µg/m³, 2020-10-01), nearest site (15.5 km from the fire detections) and best site (99.1% of hours). The only in-box AirNow site |
| **PurpleAir density** | Good (Wine Country has moderate PurpleAir density by 2020) |
| **NWS grid** | MTR (Bay Area) |
| **Why chosen** | Autumn fire in wine country during extreme dry/wind conditions. Concurrent with other 2020 fires — tests multi-fire feature aggregation. North Bay urban interface impact. *(Re-tiered from High to High-Medium on 2026-10-10, #9: the only in-box AirNow site, Sebastopol, peaked at 58.9 µg/m³. PR #21's High came from an AQS site, Napa Valley College, that is not an in-box AirNow site.)* |

---

### PE-009 · Rabbit Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-009` |
| **Region** | Southern California (Riverside County — Badlands between Moreno Valley and Beaumont) |
| **Start date** | 2023-07-14 |
| **End date** | 2023-07-23 (contained) |
| **Acres burned** | ~8,355 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP SP: 87 detections in the bbox and window. Also stored, not used for features: MODIS SP 35, VIIRS-NOAA20 SP 68 |
| **AirNow sites in box** | Banning - South Hathaway Street `06-065-0012` — tier site (peak 68.2 µg/m³, 2023-07-15), nearest site (11.7 km from the fire detections) and best site (100.0% of hours). Also in box: Morongo School |
| **PurpleAir density** | Not yet checked (Inland Empire, 2023) |
| **NWS grid** | SGX (San Diego — covers western Riverside County) |
| **Why chosen** | Small inland Southern California fire with a sharp one-day smoke hit: Banning peaked at 68.2 µg/m³ on 2023-07-15, inside the High-Medium band. Morongo, 3 km further out, is also in the box, so the event tests how sharply impact falls off between nearby monitors. Summer onshore-wind case, complementing Woolsey's (PE-010) Santa Ana case. Other fires account for 18.3% of in-box FRP, near the 20% limit; accepted because FIRMS `_SP` is final reprocessed data (#7). *(Replaces the original PE-009, Witch Fire 2007. See the replacement log below.)* |

---

## Tier 3 — Medium-Low Impact (3 events)

### PE-010 · Woolsey Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-010` |
| **Region** | Southern California (Los Angeles, Ventura counties) |
| **Start date** | 2018-11-08 |
| **End date** | 2018-11-21 |
| **Acres burned** | ~96,949 |
| **FIRMS archive** | VIIRS-SNPP SP: 1,824 detections in the bbox and window. Also stored, not used for features: MODIS SP 515, VIIRS-NOAA20 SP 2,291 |
| **AirNow sites in box** | Reseda `06-037-1201` — tier site (peak 42.1 µg/m³, 2018-11-10). Thousand Oaks - Moorpark Road `06-111-0007` — nearest site (2.2 km from the fire detections). El Rio - Rio Mesa School #2 `06-111-3001` — best site (99.7% of hours). Also in box: Simi Valley - Cochran Street, Piru - Pacific, Santa Clarita |
| **PurpleAir density** | Moderate (LA metro beginning to densify by 2018) |
| **NWS grid** | LOX (Los Angeles) |
| **Why chosen** | LA metro fire during Santa Ana wind event. Tests the model on Southern California's wind-driven fire regime and dense urban downwind monitoring. Concurrent with the Camp Fire in NorCal — two major simultaneous fires testing feature isolation. *(Re-tiered from High-Medium to Medium-Low on 2026-10-09; the in-box tier site, Reseda, peaked at 42.1 µg/m³.)* |

---

### PE-011 · Klamathon Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-011` |
| **Region** | Northern California (Siskiyou County — near Hornbrook, I-5 corridor) |
| **Start date** | 2018-07-05 |
| **End date** | 2018-07-18 (training window; contained 2018-07-21) |
| **Acres burned** | ~38,009 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP SP: 954 detections in the bbox and window. Also stored, not used for features: MODIS SP 222, VIIRS-NOAA20 SP 746 |
| **AirNow sites in box** | Yreka `06-093-2001` — tier site (peak 47.5 µg/m³, 2018-07-07), nearest site (17.4 km from the fire detections) and best site (99.7% of hours). Also in box: Ashland Fire Dept (Oregon; the bbox crosses the state line) |
| **PurpleAir density** | Very sparse (rural Siskiyou, 2018) |
| **NWS grid** | MFR (Medford) |
| **Why chosen** | Mid-sized fire whose smoke reached the nearest monitor at moderate levels: Yreka peaked at 47.5 µg/m³ on 2018-07-07, inside the Medium-Low band. Other fires account for 3.1% of in-box FRP. Tests the case where one California site carries nearly all the labels for an event. *(Replaces the original PE-011, Kincade Fire 2019, whose measured impact was Low, not Medium-Low. See the replacement log below.)* |

---

### PE-019 · LNU Lightning Complex (perimeter section only)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-019` |
| **Region** | Bay Area / Wine Country (Lake, Napa, Sonoma, Yolo, Colusa counties) |
| **Start date** | 2020-08-17 |
| **End date** | 2020-08-18 |
| **Acres burned** | ~8,200 (first 48 hours, before major escalation) |
| **FIRMS archive** | VIIRS-SNPP SP: 385 detections in the bbox and window. Also stored, not used for features: MODIS SP 33, VIIRS-NOAA20 SP 260 |
| **AirNow sites in box** | Vacaville `06-095-3003` — tier site (peak 52.9 µg/m³, 2020-08-18), nearest site (28.6 km from the fire detections) and best site (100.0% of hours). The only in-box AirNow site |
| **PurpleAir density** | Good (Bay Area) |
| **NWS grid** | MTR (Bay Area — Napa, Sonoma), EKA (Eureka — Lake), STO (Sacramento — Yolo, Colusa) |
| **Why chosen** | The first 48 hours of the LNU Complex, before it became a major event. Marine layer suppressed daytime PM2.5 at coastal monitors even as the fire grew. Nighttime detections show high FRP but low observed PM2.5. Tests diurnal patterns and the `local_solar_hour` feature. *(Re-tiered from Low to Medium-Low on 2026-10-10, #9: the in-box tier site, Vacaville, peaked at 52.9 µg/m³, 12× its pre-event baseline of 4.3. PR #21's Low came from AQS sites near the ignition points, which peaked at 35.3.)* |

---

## Tier 4 — Low Impact (6 events)

### PE-014 · River Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-014` |
| **Region** | Sierra Nevada Foothills (Nevada, Placer counties) |
| **Start date** | 2021-08-04 |
| **End date** | 2021-08-05 (shortened from 2021-08-08; see below) |
| **Acres burned** | ~2,600 (short duration, localised) |
| **FIRMS archive** | VIIRS-SNPP SP: 47 detections in the bbox and window. Also stored, not used for features: MODIS SP 14, VIIRS-NOAA20 SP 73 |
| **AirNow sites in box** | Auburn `06-061-0003` — tier site (peak 6.9 µg/m³, 2021-08-05) and best site (100.0% of hours). Colfax `06-061-0004` — nearest site (1.5 km from the fire detections) |
| **PurpleAir density** | Good (Sacramento metro area has strong coverage) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Small fire right next to a monitor that barely registered it: Colfax is 1.5 km from the fire detections, and no in-box site's daily mean passed 6.9 µg/m³. Tests the near-zero case at very short distance. *(Window shortened from 08-04–08-08 to 08-04–08-05 on 2026-10-09: on 08-06 regional smoke from the Dixie Fire arrived, so later days would carry High labels from a different fire.)* |

---

### PE-015 · Sheep Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-015` |
| **Region** | Southern California (San Bernardino County — near Wrightwood, San Gabriel Mountains) |
| **Start date** | 2022-06-12 (CAL FIRE alarm date; was 2022-06-11, a day before the fire) |
| **End date** | 2022-06-14 |
| **Acres burned** | ~990 |
| **FIRMS archive** | VIIRS-SNPP SP: 42 detections in the bbox and window. Also stored, not used for features: MODIS SP 17, VIIRS-NOAA20 SP 58 |
| **AirNow sites in box** | Victorville - Park Avenue `06-071-0306` — tier site (peak 12.4 µg/m³, 2022-06-14), nearest site (29.1 km from the fire detections) and best site (100.0% of hours). Also in box: Glendora - Laurel |
| **PurpleAir density** | Moderate (Victor Valley / Wrightwood) |
| **NWS grid** | SGX (San Diego — its warning area covers the San Bernardino County mountains and Victor Valley; verified via `api.weather.gov/points`: Wrightwood → SGX zone CAZ055, Victorville → SGX zone CAZ060) |
| **Why chosen** | Very small fire in the high desert with dry, windy conditions. Originally chosen for localised AQI spikes, but daily means stayed in the Low band (Victorville peaked at 12.4 µg/m³). Now a small-fire near-zero case; whether hourly values spiked is for the DATA-03 run to show. *(Re-tiered from Medium-Low to Low on 2026-10-09.)* |

---

### PE-016 · Chimney Fire (first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-016` |
| **Region** | Central Coast (San Luis Obispo County) |
| **Start date** | 2016-08-13 |
| **End date** | 2016-08-26 (training window; contained 2016-09-06) |
| **Acres burned** | ~46,344 (final; acreage at the end of the window to be confirmed from CAL FIRE incident reports) |
| **FIRMS archive** | VIIRS-SNPP SP: 1,544 detections in the bbox and window. Also stored, not used for features: MODIS SP 423 |
| **AirNow sites in box** | Atascadero `06-079-8002` — tier site (peak 24.7 µg/m³, 2016-08-16), nearest site (32.9 km from the fire detections) and best site (97.3% of hours). The only in-box AirNow site; the bbox was widened to reach it (#3) |
| **PurpleAir density** | Not checked (PurpleAir deferred to v1.1) |
| **NWS grid** | LOX (Los Angeles — San Luis Obispo County) |
| **Why chosen** | Mid-sized Santa Lucia Range fire whose smoke stayed in the Low band at the only in-box monitor: Atascadero peaked at 24.7 µg/m³ on 2016-08-16. With PE-018 Lake, it teaches the model that a fire of this size need not mean high downwind impact. No other fire contributed in-box FRP. *(Replaces PE-016 Rim Fire 2013 on 2026-10-10, #10. See the replacement log below.)* |

---

### PE-017 · Mosquito Fire (first three days)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-017` |
| **Region** | Sierra Nevada Foothills (Placer, El Dorado counties) |
| **Start date** | 2022-09-06 |
| **End date** | 2022-09-08 (first three days; the fire was contained 2022-10-22) |
| **Acres burned** | ~76,788 final; acreage during the window to be confirmed from CAL FIRE incident reports |
| **FIRMS archive** | VIIRS-SNPP SP: 470 detections in the bbox and window. Also stored, not used for features: MODIS SP 148, VIIRS-NOAA20 SP 663 |
| **AirNow sites in box** | Colfax `06-061-0004` — tier site (peak 20.6 µg/m³, 2022-09-07), nearest site (15.9 km from the fire detections) and best site (100.0% of hours). The only in-box AirNow site |
| **PurpleAir density** | Not checked (PurpleAir deferred to v1.1) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | The first three days of the Mosquito Fire, California's largest of 2022, before it grew into a major event. Captures a fire's pre-escalation signature: detections present, and PM2.5 at Colfax rising from a baseline of 4.2 to 20.6 µg/m³ but staying in the Low band. Teaches the model what "fire detected but smoke not yet impacting monitors" looks like — important for the 12h and 24h horizons. *(Replaces PE-017 Caldor Fire early phase on 2026-10-10, #10, and takes over its role. See the replacement log below.)* |

---

### PE-018 · Lake Fire (2024, first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-018` |
| **Region** | Central Coast (Santa Barbara County — Los Padres NF, north of Los Olivos) |
| **Start date** | 2024-07-05 |
| **End date** | 2024-07-18 (training window; contained 2024-08-04) |
| **Acres burned** | ~38,610 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP SP: 1,356 detections in the bbox and window. Also stored, not used for features: MODIS SP 486, VIIRS-NOAA20 SP 1,466 |
| **AirNow sites in box** | Santa Ynez `06-083-3001` — tier site (peak 9.7 µg/m³, 2024-07-11), nearest site (9.9 km from the fire detections) and best site (99.7% of hours). The only in-box AirNow site |
| **PurpleAir density** | Not yet checked (2024) |
| **NWS grid** | LOX (Los Angeles — verified via `api.weather.gov/points`: fire centroid → LOX zone CAZ353, Los Olivos) |
| **Why chosen** | Mid-sized fire with a monitor 10 km away, yet Santa Ynez's daily mean never passed 9.7 µg/m³. The clearest near-zero case in the set. Whether wind direction explains it (`wind_alignment`) is to be confirmed from NWS data in the DATA-03 run. *(Replaces the original PE-018, Monument Fire 2021, whose measured impact was High, not Low. See the replacement log below.)* |

---

### PE-020 · Crews Fire

| Field | Value |
|---|---|
| **pilot_event_id** | `PE-020` |
| **Region** | Bay Area / Central Coast (Santa Clara County — southeast of Gilroy) |
| **Start date** | 2020-07-05 |
| **End date** | 2020-07-13 |
| **Acres burned** | ~5,513 |
| **FIRMS archive** | VIIRS-SNPP SP: 141 detections in the bbox and window. Also stored, not used for features: MODIS SP 14, VIIRS-NOAA20 SP 117 |
| **AirNow sites in box** | Hollister AMS `06-069-0002` — tier site (peak 13.3 µg/m³, 2020-07-05) and best site (99.1% of hours). Gilroy - 9th Street `06-085-0002` — nearest site (6.7 km from the fire detections) |
| **PurpleAir density** | Not yet checked (South Bay, 2020) |
| **NWS grid** | MTR (Bay Area — Santa Clara) |
| **Why chosen** | Small, short-duration grass-and-oak fire expected to have limited smoke impact. It burned before the August 2020 lightning siege (SCU, LNU, August Complex), so background PM2.5 was clean: the in-box peak was 13.3 µg/m³ at Hollister. Other fires account for 19.2% of in-box FRP, near the 20% limit; accepted because FIRMS `_SP` is final reprocessed data (#7). *(Replaces the original PE-020, a 2017 "Shasta Fire" that does not exist and was never checked against FIRMS or AQS data.)* |

---

## Summary table

| ID | Fire name | Year | Region | Acres | Tier | Key characteristic |
|---|---|---|---|---|---|---|
| PE-001 | August Complex | 2020 | NorCal | 1,032,648 | High | California's first gigafire |
| PE-002 | Dixie | 2021 | NorCal | 963,309 | High-Medium | Largest single-ignition fire |
| PE-003 | Mendocino Complex | 2018 | NorCal | 459,123 | High-Medium | Pre-PurpleAir era |
| PE-004 | Park | 2024 | NorCal | 429,603 | High | Most recent major fire, monitor 4 km away |
| PE-005 | SCU Lightning Complex (to 08-31) | 2020 | Bay Area | 396,624 | High-Medium | Most in-box monitors (6) |
| PE-006 | Soberanes (first 2 weeks) | 2016 | Central Coast | 132,104 | High-Medium | Downwind valley monitor, pre-PurpleAir |
| PE-007 | Glass | 2020 | NorCal | 67,484 | High-Medium | Autumn wine country winds |
| PE-008 | Carr (from 07-31) | 2018 | NorCal | 229,651 | High | Pyrotornado, outlier FRP |
| PE-009 | Rabbit | 2023 | SoCal | 8,355 | High-Medium | One-day spike, sharp falloff between monitors |
| PE-010 | Woolsey | 2018 | SoCal | 96,949 | Medium-Low | LA metro Santa Ana winds |
| PE-011 | Klamathon | 2018 | NorCal | 38,009 | Medium-Low | Single California monitor |
| PE-012 | Creek | 2020 | Sierra | 379,895 | High | Valley-trapped smoke |
| PE-013 | Zogg | 2020 | NorCal | 56,338 | High | Three concurrent fires |
| PE-014 | River (2 days) | 2021 | Sierra Foothills | 2,600 | Low | Near-zero right next to a monitor |
| PE-015 | Sheep | 2022 | SoCal | ~990 | Low | Small fire, near-zero daily means |
| PE-016 | Chimney (first 2 weeks) | 2016 | Central Coast | 46,344 (final) | Low | Mid-sized fire, low measured impact |
| PE-017 | Mosquito (first 3 days) | 2022 | Sierra Foothills | to confirm (76,788 final) | Low | Pre-escalation signature |
| PE-018 | Lake (2024, first 2 weeks) | 2024 | Central Coast | 38,610 | Low | Near-zero 10 km from a mid-sized fire |
| PE-019 | LNU Complex (48h) | 2020 | Bay Area | 8,200 | Medium-Low | Marine layer, diurnal pattern |
| PE-020 | Crews | 2020 | Bay Area | 5,513 | Low | Cleanest near-zero baseline |

**Tier counts:** High 5, High-Medium 6, Medium-Low 3, Low 6.

**Geographic coverage:** Northern California (8), Sierra Nevada / Foothills (3), Southern California (3), Bay Area / Central Coast (6) — satisfies the ≥3 region requirement. Project scope is **California only**; regions are California sub-regions.

**Date range:** 2016–2024 — 9 years of FIRMS and AirNow archival data.

**FIRMS sensors:** fire features use VIIRS-SNPP SP only (#13). MODIS Terra/Aqua and VIIRS-NOAA20 SP detections are stored, tagged by satellite, but not used; VIIRS-NOAA21 is excluded (#11).

---

## Data-availability verification

PM-01 requires each event to have a recorded check confirming nearby monitor coverage. This table is the evidence. It is taken from `backend/scripts/pilot_verification/reports/final_check.md`, run on 2026-10-10 with `PILOT_EVENTS=final` on live FIRMS `_SP` and AirNow `/aq/data/` data, under the rules in [`docs/data-decisions.md`](data-decisions.md). All 20 events pass every rule.

- **Tier site: peak (day)**: the in-box AirNow site with the highest peak daily mean (local-standard-time days with ≥ 18 valid hours) and that peak in µg/m³. It sets the tier (#4). **AirNow preliminary data, not AQS.**
- **Nearest in-box site**: distance from the site to the nearest FIRMS detection of the event's own cluster; must be ≤ 40 km (#2).
- **Best site, % hours**: the in-box site with the most valid hours in the window; must be ≥ 75% (#6).
- **Other-fire FRP**: share of in-box FRP from other fires; must be < 20% (#7).
- **VIIRS-SNPP SP**: detection count in the bbox and window for the sensor fire features use (#13).
- **AQS peak ≤ 50 km (reference)**: PR #21's AQS site check (2026-10-09): the highest daily mean at any hourly AQS site with ≥ 75% coverage within 50 km of the fire. **Reference only (#1)**: it does not set the tier, because a site 50 km away does not describe the box. Not run for PE-016 and PE-017, which were replaced afterwards.

| ID | Window | Tier | Tier site: peak (day) | Nearest in-box site | Best site, % hours | Other-fire FRP | VIIRS-SNPP SP | AQS peak ≤ 50 km (reference) |
|---|---|---|---|---|---|---|---|---|
| PE-001 | 2020-08-16 → 11-12 | High | Willows-Colusa: 145.2 (2020-09-11) | Willows-Colusa, 18.9 km | Willows-Colusa, 99.4% | 2.3% | 66,359 | 433.9 |
| PE-002 | 2021-07-13 → 10-25 | High-Medium | Chico - East: 102.8 (2021-08-07) | Chico - East, 34.6 km | Chico - East, 95.6% | 0.0% | 62,382 | 568.1 |
| PE-003 | 2018-07-27 → 09-18 | High-Medium | Ukiah Library: 59.5 (2018-08-08) | Ukiah Library, 9.4 km | Ukiah Library, 96.5% | 0.0% | 16,272 | 118.2 |
| PE-004 | 2024-07-24 → 10-24 | High | Paradise - Clark Road: 138.1 (2024-07-31) | Chico - East, 4.1 km | Chico - East, 99.1% | 0.0% | 3,685 | 85.2 |
| PE-005 | 2020-08-16 → 08-31 | High-Medium | TracyAP: 117.5 (2020-08-24) | San Jose - Knox Ave, 5.8 km | Modesto - 14th Street, 99.7% | 0.1% | 9,601 | 117.5 |
| PE-006 | 2016-07-22 → 08-04 | High-Medium | Carmel Valley AMS: 63.8 (2016-07-26) | Carmel Valley AMS, 5.9 km | Carmel Valley AMS, 98.8% | 0.0% | 3,005 | 63.8 |
| PE-007 | 2020-09-27 → 10-20 | High-Medium | Sebastopol: 58.9 (2020-10-01) | Sebastopol, 15.5 km | Sebastopol, 99.1% | 0.0% | 2,431 | 148.6 |
| PE-008 | 2018-07-31 → 08-30 | High | Weaverville: 134.0 (2018-08-08) | Weaverville, 11.9 km | Weaverville, 93.1% | 0.0% | 9,758 | 134.0 |
| PE-009 | 2023-07-14 → 07-23 | High-Medium | Banning - South Hathaway Street: 68.2 (2023-07-15) | Banning - South Hathaway Street, 11.7 km | Banning - South Hathaway Street, 100.0% | 18.3% | 87 | 68.2 |
| PE-010 | 2018-11-08 → 11-21 | Medium-Low | Reseda: 42.1 (2018-11-10) | Thousand Oaks - Moorpark Road, 2.2 km | El Rio - Rio Mesa School #2, 99.7% | 0.0% | 1,824 | 44.2 |
| PE-011 | 2018-07-05 → 07-18 | Medium-Low | Yreka: 47.5 (2018-07-07) | Yreka, 17.4 km | Yreka, 99.7% | 3.1% | 954 | 47.5 |
| PE-012 | 2020-09-04 → 12-24 | High | Yosemite Village - Visitor Center: 613.2 (2020-09-17) | Yosemite Village - Visitor Center, 28.1 km | Clovis - N. Villa Ave, 99.6% | 1.5% | 40,517 | 824.1 |
| PE-013 | 2020-09-27 → 10-15 | High | Weaverville: 125.8 (2020-10-02) | Weaverville, 31.7 km | Weaverville, 87.5% | 0.6% | 1,681 | 125.8 |
| PE-014 | 2021-08-04 → 08-05 | Low | Auburn: 6.9 (2021-08-05) | Colfax, 1.5 km | Auburn, 100.0% | 0.0% | 47 | 10.9 |
| PE-015 | 2022-06-12 → 06-14 | Low | Victorville - Park Avenue: 12.4 (2022-06-14) | Victorville - Park Avenue, 29.1 km | Victorville - Park Avenue, 100.0% | 0.0% | 42 | 19.7 |
| PE-016 | 2016-08-13 → 08-26 | Low | Atascadero: 24.7 (2016-08-16) | Atascadero, 32.9 km | Atascadero, 97.3% | 0.0% | 1,544 | — |
| PE-017 | 2022-09-06 → 09-08 | Low | Colfax: 20.6 (2022-09-07) | Colfax, 15.9 km | Colfax, 100.0% | 0.0% | 470 | — |
| PE-018 | 2024-07-05 → 07-18 | Low | Santa Ynez: 9.7 (2024-07-11) | Santa Ynez, 9.9 km | Santa Ynez, 99.7% | 0.0% | 1,356 | 10.3 |
| PE-019 | 2020-08-17 → 08-18 | Medium-Low | Vacaville: 52.9 (2020-08-18) | Vacaville, 28.6 km | Vacaville, 100.0% | 0.1% | 385 | 35.3 |
| PE-020 | 2020-07-05 → 07-13 | Low | Hollister AMS: 13.3 (2020-07-05) | Gilroy - 9th Street, 6.7 km | Hollister AMS, 99.1% | 19.2% | 141 | 23.7 |

Every non-Low event also passes the elevation rule (#5); `final_check.md` gives each tier site's baseline and elevation, and the bbox for each event.

**Tier changes:**

- **2026-10-10 (computed tier, #9):** PE-002 Dixie High → High-Medium; PE-004 Park High-Medium → High; PE-007 Glass High → High-Medium; PE-013 Zogg Medium-Low → High; PE-019 LNU Low → Medium-Low.
- **2026-10-09 (PR #21, from AQS peaks within 50 km):** PE-007 Glass, PE-008 Carr and PE-012 Creek High-Medium → High; PE-003 Mendocino Complex, PE-004 Park and PE-005 SCU High → High-Medium; PE-010 Woolsey High-Medium → Medium-Low; PE-015 Sheep Medium-Low → Low. PE-013 Zogg was kept at Medium-Low despite a High reading; reversed on 2026-10-10.

**Windows changed:**

- **2026-10-10:** PE-008 Carr starts 2018-07-31 instead of 2018-07-23, because Weaverville was dark on the top-quartile days 07-26 and 07-28 to 07-30 (#8).
- **2026-10-09:** PE-014 River shortened to 2021-08-04–08-05 because Dixie Fire smoke reached its monitors from 08-06; PE-005 SCU set to 2020-08-16–08-31, its active period, because later High readings came from other fires. Start dates moved to CAL FIRE alarm dates: PE-001 2020-08-17 → 08-16, PE-005 2020-08-18 → 08-16, PE-015 2022-06-11 → 06-12.

**Monitors and FIRMS lines (2026-10-10):** every card's monitor line now lists the in-box AirNow sites from the config, naming the tier, nearest and best sites with their AQS IDs. The AQS site lists from 2026-10-09 survive only as the reference column above. Every card's FIRMS line gives the `_SP` detection counts in the event's bbox and window, with VIIRS-SNPP first because it is the only sensor used for fire features.

### Replacements

| ID | Original event | Replacement | Date | Reason |
|---|---|---|---|---|
| PE-006 | Valley Fire (2015) | **Soberanes Fire (2016)** | 2026-10-09 | Tier mismatch: listed High-Medium, measured Low. Peak daily PM2.5 was 22.3 µg/m³ at most (AQS, Ukiah `06-045-0006`); Sebastopol, Napa and Cortina stayed under 10. |
| PE-009 | Witch Fire (2007) | **Rabbit Fire (2023)** | 2026-10-09 | Failed the check: no hourly PM2.5 in San Diego County for the window, only 24-hour filter samples (AQS), and the AirNow-Tech archive starts in 2012. |
| PE-011 | Kincade Fire (2019) | **Klamathon Fire (2018)** | 2026-10-09 | Tier mismatch: listed Medium-Low, measured Low. Peak daily PM2.5 was 28.0 µg/m³ at most (AQS, Sebastopol `06-097-0004`, which also reported only 72% of hours); Napa Valley College, Cortina and Ukiah stayed under 19. |
| PE-016 | Antelope Fire (2021) | Rim Fire (2013) | 2026-10-09 | Tier mismatch that defeats its role: listed Low as the "large fire, little impact" case, measured High. Yreka `06-093-2001` peaked at 134.3 µg/m³ (AQS) and exceeded 35.4 on 20 of 31 days. |
| PE-016 | Rim Fire (2013) | **Chimney Fire (2016, first two weeks)** | 2026-10-10 | No AirNow site inside Rim's bbox; the nearest, San Andreas, is 49.7 km from the fire, outside the 40 km rule (#2, #10). Chimney was the pick of `screen_candidates.py`: it passes every rule with tier Low and clashes with no other event's window within 200 km. |
| PE-017 | Caldor Fire, early phase (2021) | **Mosquito Fire, first three days (2022)** | 2026-10-10 | No AirNow site inside Caldor's bbox; the nearest, San Andreas, is 40.8 km from the fire (#2, #10). Mosquito was the pick of `screen_candidates.py`: it passes every rule with tier Low and clashes with no other event's window within 200 km. |
| PE-018 | Monument Fire (2021) | **Lake Fire (2024)** | 2026-10-09 | Tier mismatch that defeats its role: listed Low as the "smoke dispersed away" case, measured High. Weaverville `06-105-0002` peaked at 685.5 µg/m³ (AQS) and exceeded 125.4 on 23 days. |
| PE-020 | "Shasta Fire (2017)" | **Crews Fire (2020)** | 2026-10-03 | The original event does not exist and was never checked against FIRMS or AQS data. The Crews monitors were confirmed on 2026-10-09 (AQS) and 2026-10-10 (AirNow). |

Notes on the replacements:

- **PE-006 and PE-011** both had usable hourly label monitors, so neither failed the coverage check. Their tiers had been assigned from each fire's reputation, not from monitor data. Re-tiering both to Low would have left Medium-Low with 2 events, so they were replaced with events whose measured peaks match the intended tier. Lost by the swap: Valley's rapid-ignition case and Kincade's marine-layer case; either could come back as an extra Low-tier event.
- **PE-009**: dropping Witch also drops the dataset's only MODIS-only (pre-VIIRS) event.
- **PE-016 (Antelope) and PE-018 (Monument)** could have been re-tiered to High, but they were chosen specifically as low-impact cases, so a High tier would have defeated their purpose.
- **PE-016 (Rim) and PE-017 (Caldor)** passed PR #21's AQS check but have no AirNow site in their bbox, so they could produce no in-box labels. Lost by the swap: Rim's "very large fire, low impact" case (256,176 acres); Chimney, at 46,344 acres, is a mid-sized case.

---

## Earlier check: FIRMS + AirNow (2026-10-06)

Kept for the record: `backend/docs/pilot_events.json` history and the scripts in `backend/scripts/pilot_verification/` (see its README) refer to this section. It checked the **event set as it stood on dev on 2026-10-06**, so several event IDs here name fires that have since been replaced (PE-006 Valley, PE-009 Witch, PE-011 Kincade, PE-016 Antelope, PE-017 Caldor, PE-018 Monument, PE-020 "Shasta"), and its tiers, bboxes and verdicts are superseded by the 2026-10-10 check above.

| ID | AQS site IDs (≤ 25 km) | % hours | Peak daily PM2.5 | Tier confirmed? | FIRMS SP detections | Checked by / date |
|---|---|---|---|---|---|---|
| PE-001 | 06-021-0003 Willows-Colusa (18.9 km)<br>06-103-0007 Red Bluff - Walnut office (29.2 km, >25) | 99.4% (Willows-Colusa) | 145.2 µg/m³ (Willows-Colusa, 2020-09-11) — AirNow prelim. | Yes — High | 148,092 (MODIS 14,137 / SNPP 66,362 / NOAA-20 67,593) | Pending |
| PE-002 | 06-007-0008 Chico - East (34.6 km, >25) | 95.6% (Chico - East) | 102.8 µg/m³ (Chico - East, 2021-08-07) — AirNow prelim. | No — measured High-Medium (doc: High) | 142,306 (MODIS 13,870 / SNPP 62,382 / NOAA-20 66,054) | Pending |
| PE-003 | 06-045-0006 Ukiah Library (9.4 km) | 96.5% (Ukiah Library) | 59.5 µg/m³ (Ukiah Library, 2018-08-08) — AirNow prelim. | No — measured High-Medium (doc: High) | 37,179 (MODIS 4,597 / SNPP 16,272 / NOAA-20 16,310) | Pending |
| PE-004 | 06-007-0008 Chico - East (4.1 km)<br>06-007-2003 Paradise - Clark Road (9.2 km)<br>06-103-0007 Red Bluff - Walnut office (17.6 km) | 99.1% (Chico - East) | 85.2 µg/m³ (Chico - East, 2024-08-02) — AirNow prelim. Max in bbox: 138.1 (Paradise - Clark Road, 2024-07-31) | No — measured High-Medium (doc: High); High at Paradise - Clark Road | 16,154 (MODIS 2,839 / SNPP 3,685 / NOAA-20 9,630) | Pending |
| PE-005 | 06-085-0006 San Jose - Knox Ave (5.8 km)<br>06-077-3005 TracyAP (9.2 km)<br>06-085-0005 San Jose - Jackson St. (9.3 km)<br>06-099-0005 Modesto - 14th Street (12.0 km)<br>06-085-0002 Gilroy - 9th Street (17.1 km)<br>06-087-0007 Santa Cruz AMS (45.4 km, >25) | 99.5% (TracyAP) | 117.5 µg/m³ (TracyAP, 2020-08-24) — AirNow prelim. Max in bbox: 123.1 (San Jose - Knox Ave, 2020-09-11) | No — measured High-Medium (doc: High) | 20,590 (MODIS 2,206 / SNPP 9,294 / NOAA-20 9,090) | Pending |
| PE-006 | 06-097-0004 Sebastopol (38.5 km, >25) | 97.7% (Sebastopol) | 7.3 µg/m³ (Sebastopol, 2015-09-21) — AirNow prelim. | No — measured Low (doc: High-Medium) | 224 (MODIS 63 / SNPP 161) | Pending |
| PE-007 | 06-097-0004 Sebastopol (15.5 km) | 99.1% (Sebastopol) | 58.9 µg/m³ (Sebastopol, 2020-10-01) — AirNow prelim. | Yes — High-Medium | 5,189 (MODIS 659 / SNPP 2,431 / NOAA-20 2,099) | Pending |
| PE-008 | 06-105-0002 Weaverville (11.9 km) | 74.0% (Weaverville) | 134.0 µg/m³ (Weaverville, 2018-08-08) — AirNow prelim. | No — measured High (doc: High-Medium) | 31,129 (MODIS 3,747 / SNPP 14,154 / NOAA-20 13,228) | Pending |
| PE-009 | None in bbox (no AirNow data) | 0% | No AirNow data | Pending (no AirNow data) | 1,198 (MODIS 1,198) | Pending |
| PE-010 | 06-111-0007 Thousand Oaks - Moorpark Road (2.2 km)<br>06-111-2002 Simi Valley - Cochran Street (2.2 km)<br>06-111-3001 El Rio - Rio Mesa School #2 (7.2 km)<br>06-037-1201 Reseda (10.1 km)<br>06-111-0009 Piru - Pacific (12.7 km)<br>06-037-6012 Santa Clarita (15.2 km) | 99.7% (El Rio - Rio Mesa School #2) | 41.2 µg/m³ (El Rio - Rio Mesa School #2, 2018-11-11) — AirNow prelim. Max in bbox: 42.1 (Reseda, 2018-11-10) | No — measured Medium-Low (doc: High-Medium) | 4,630 (MODIS 515 / SNPP 1,824 / NOAA-20 2,291) | Pending |
| PE-011 | 06-097-0004 Sebastopol (14.1 km) | 72.8% (Sebastopol) | 28.0 µg/m³ (Sebastopol, 2019-10-25) — AirNow prelim. | No — measured Low (doc: Medium-Low) | 4,227 (MODIS 404 / SNPP 1,803 / NOAA-20 2,020) | Pending |
| PE-012 | 06-043-1001 Yosemite Village - Visitor Center (28.1 km, >25)<br>06-019-5001 Clovis - N. Villa Ave (32.5 km, >25) | 99.6% (Clovis - N. Villa Ave) | 193.8 µg/m³ (Clovis - N. Villa Ave, 2020-09-14) — AirNow prelim. Max in bbox: 613.2 (Yosemite Village - Visitor Center, 2020-09-17) | No — measured High (doc: High-Medium) | 89,129 (MODIS 7,518 / SNPP 40,517 / NOAA-20 41,094) | Pending |
| PE-013 | 06-105-0002 Weaverville (31.7 km, >25)<br>06-103-0007 Red Bluff - Walnut office (33.3 km, >25) | 87.5% (Weaverville) | 125.8 µg/m³ (Weaverville, 2020-10-02) — AirNow prelim. | No — measured High (doc: Medium-Low) | 3,451 (MODIS 374 / SNPP 1,681 / NOAA-20 1,396) | Pending |
| PE-014 | 06-061-0004 Colfax (1.5 km)<br>06-061-0003 Auburn (18.6 km) | 100.0% (Auburn) | 127.3 µg/m³ (Auburn, 2021-08-07) — AirNow prelim. Max in bbox: 165.3 (Colfax, 2021-08-06) | No — measured High (doc: Low) | 134 (MODIS 14 / SNPP 47 / NOAA-20 73) | Pending |
| PE-015 | 06-071-0306 Victorville - Park Avenue (29.1 km, >25)<br>06-037-0016 Glendora - Laurel (31.2 km, >25) | 100.0% (Victorville - Park Avenue) | 12.4 µg/m³ (Victorville - Park Avenue, 2022-06-14) — AirNow prelim. | No — measured Low (doc: Medium-Low) | 118 (MODIS 17 / SNPP 42 / NOAA-20 59) | Pending |
| PE-016 | 06-093-2002 Mt Shasta (25.2 km, >25) | 94.6% (Mt Shasta) | 107.9 µg/m³ (Mt Shasta, 2021-08-15) — AirNow prelim. | No — measured High-Medium (doc: Low) | 11,515 (MODIS 1,126 / SNPP 5,193 / NOAA-20 5,196) | Pending |
| PE-017 | None in bbox (nearest: 06-009-0001 San Andreas, 40.8 km) | 0% | No AirNow data | Pending (no AirNow data) | 261 (MODIS 43 / SNPP 132 / NOAA-20 86) | Pending |
| PE-018 | 06-105-0002 Weaverville (8.4 km) | 97.0% (Weaverville) | 685.5 µg/m³ (Weaverville, 2021-08-07) — AirNow prelim. | No — measured High (doc: Low) | 93,254 (MODIS 9,847 / SNPP 41,648 / NOAA-20 41,759) | Pending |
| PE-019 | 06-095-3003 Vacaville (28.6 km, >25) | 100.0% (Vacaville) | 52.9 µg/m³ (Vacaville, 2020-08-18) — AirNow prelim. | No — measured Medium-Low (doc: Low) | 678 (MODIS 33 / SNPP 385 / NOAA-20 260) | Pending |
| PE-020 | None in bbox (nearest: 06-007-0008 Chico -  East, 102.8 km) | 0% | No AirNow data | Pending (no AirNow data) | 0 (MODIS 0 / SNPP 0) | Pending |

An event that fails the check (no site ≤ 25 km, or < 75% hours) is replaced, and the replacement is noted here.

**Measured 2026-10-06 (FIRMS + AirNow only).** Filled from live API calls, not yet from AQS:

- **Bbox** — each event's bbox is centred on the FRP-weighted centroid of its FIRMS `_SP` cluster, with the cluster's FRP-weighted 98th-percentile extent plus a 25 km buffer, symmetric about the centroid. The config (`backend/docs/pilot_events.json`) holds it. PE-020 has no cluster, so its row uses the bbox already in the config.
- **FIRMS SP detections** — every `_SP` archive product with coverage for the window (MODIS, VIIRS-SNPP from 2012-01-20, VIIRS-NOAA20 from 2018-04-01; NOAA-21 has no `_SP` product), counted inside the bbox.
- **AQS site IDs** — AirNow `/aq/data/` sites that reported PM2.5 inside the bbox during the window, with the AQS ID AirNow sends. The distance is to the nearest FIRMS detection of the event's cluster. Sites over 25 km away are marked `>25`: they can still carry labels at forecast points placed next to them, but there is no monitor near the fire. Where none reports in the bbox, the nearest site comes from a one-day AirNow probe of a 300 km box.
- **% hours** — share of the window's UTC hours (start date 00:00 to end date 23:00, as `batch_ingest` requests them) with a valid `RawConcentration` at the best site.
- **Peak daily PM2.5** — the highest daily mean of hourly AirNow `RawConcentration` at the best site (the one in the % hours column), over local-standard-time days (UTC−8, as AQS daily means use) with ≥ 18 valid hours. Red Bluff's labels are shifted to the true hour with PR #24's offset table. **Source: AirNow preliminary data, not AQS.** Where another site in the bbox peaked higher, that value is shown too. Some peaks are smoke from other fires: for PE-014, Auburn's 2021-08-07 peak is from the Dixie Fire.
- **Tier confirmed?** — the best site's peak against the tier table above. The cards and `pilot_events.json` still carry the doc's original tiers; re-tiering is a separate decision. Checked-by stays Pending until the AQS check.

**Verdicts**

| ID | Verdict | Bbox (km, W × H) | Reason |
|---|---|---|---|
| PE-001 | Pass | 148 × 148 | 148,092 FIRMS _SP detections in the bbox; nearest AirNow site Willows-Colusa (06-021-0003) is 18.9 km from the fire with 99.4% of hours; 2 reporting site(s) in the bbox. |
| PE-002 | Borderline | 173 × 136 | Nearest reporting AirNow site Chico - East (06-007-0008) is 34.6 km from the fire (95.6% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-003 | Pass | 100 × 107 | 37,179 FIRMS _SP detections in the bbox; nearest AirNow site Ukiah Library (06-045-0006) is 9.4 km from the fire with 96.5% of hours; 1 reporting site(s) in the bbox. |
| PE-004 | Pass | 94 × 111 | 16,154 FIRMS _SP detections in the bbox; nearest AirNow site Chico - East (06-007-0008) is 4.1 km from the fire with 99.1% of hours; 3 reporting site(s) in the bbox. |
| PE-005 | Pass | 96 × 98 | 20,590 FIRMS _SP detections in the bbox; nearest AirNow site San Jose - Knox Ave (06-085-0006) is 5.8 km from the fire with 99.1% of hours; 6 reporting site(s) in the bbox. |
| PE-006 | Borderline | 82 × 78 | Nearest reporting AirNow site Sebastopol (06-097-0004) is 38.5 km from the fire (97.7% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-007 | Pass | 69 × 75 | 5,189 FIRMS _SP detections in the bbox; nearest AirNow site Sebastopol (06-097-0004) is 15.5 km from the fire with 99.1% of hours; 1 reporting site(s) in the bbox. |
| PE-008 | Borderline | 104 × 114 | Only AirNow site Weaverville (06-105-0002, 11.9 km) has 74.0% of hours, under the doc's 75% rule. |
| PE-009 | Fail | 95 × 98 | AirNow /aq/data/ has no rows in the bbox for the window and none in a 300 km box around the fire (statewide California returns 0 rows for 2007 and 2008; AirNow coverage starts later). Labels would need AQS/AirData instead. |
| PE-010 | Pass | 79 × 75 | 4,630 FIRMS _SP detections in the bbox; nearest AirNow site Thousand Oaks - Moorpark Road (06-111-0007) is 2.2 km from the fire with 99.4% of hours; 6 reporting site(s) in the bbox. |
| PE-011 | Borderline | 66 × 77 | Only AirNow site Sebastopol (06-097-0004, 14.1 km) has 72.8% of hours, under the doc's 75% rule. |
| PE-012 | Borderline | 94 × 117 | Nearest reporting AirNow site Yosemite Village - Visitor Center (06-043-1001) is 28.1 km from the fire (98.8% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-013 | Borderline | 64 × 90 | Nearest reporting AirNow site Weaverville (06-105-0002) is 31.7 km from the fire (87.5% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-014 | Pass | 53 × 58 | 134 FIRMS _SP detections in the bbox; nearest AirNow site Colfax (06-061-0004) is 1.5 km from the fire with 94.2% of hours; 2 reporting site(s) in the bbox. |
| PE-015 | Borderline | 53 × 52 | Nearest reporting AirNow site Victorville - Park Avenue (06-071-0306) is 29.1 km from the fire (100.0% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-016 | Borderline | 74 × 70 | Nearest reporting AirNow site Mt Shasta (06-093-2002) is 25.2 km from the fire (94.6% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-017 | Fail | 57 × 53 | No AirNow site reports in the bbox. Nearest site in a 1-day probe: San Andreas (06-009-0001), 40.8 km from the fire: inside the 150 km event rule, outside the 25 km rule. A probe of all of August 2021 over a box covering Grizzly Flats, Placerville and South Lake Tahoe (−121.00,38.50,−119.85,39.05) returned no PM2.5 rows from any site, whether permanent, mobile or both (`monitorType` 0/1/2). Placerville (≈ 25.9 km from the fire) is inside the 57 × 53 km bbox; South Lake Tahoe – Sandy Way (06-017-0011, ≈ 58.3 km) is outside it. Neither appears in AirNow, so a bigger bbox would not help. |
| PE-018 | Borderline | 86 × 105 | 55% of in-box FRP is from other fires (41.115,-122.977, 41,111 detections); (40.332,-123.014, 6,818 detections): the River Complex to the north and McFarland Fire to the south. Monitor is fine (Weaverville 06-105-0002, 8.4 km, 97.0%). |
| PE-019 | Borderline | 64 × 88 | Nearest reporting AirNow site Vacaville (06-095-3003) is 28.6 km from the fire (100.0% of hours): passes the 150 km event rule but no monitor within 25 km, so no training rows near the fire. |
| PE-020 | Fail | 42 × 45 (dev config) | 0 FIRMS _SP detections in the bbox (MODIS_SP and VIIRS_SNPP_SP, 2017-07-06..2017-07-12); no AirNow site reports in the bbox, so no monitor within 25 km; nearest AirNow site Chico - East (06-007-0008) is 102.8 km from the box centre. All of Shasta County had 3 detections in the window, none inside the box: the fire named on dev could not be found (open PR #21 says it does not exist). |

Only **Pass** events are in `backend/docs/pilot_events.json`. Borderline events need a decision (accept, re-window or replace). Failed events need a replacement: for PE-020, open PR #21's Crews Fire (2020-07-05 → 07-13) passes the same check — 272 detections in a 60 × 55 km bbox, Gilroy - 9th Street (06-085-0002) 6.7 km from the fire at 98.6% of hours and Hollister (06-069-0002) at 18.2 km.

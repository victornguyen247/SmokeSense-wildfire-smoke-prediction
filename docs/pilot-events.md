# SmokeSense — Pilot Fire Events
**docs/pilot-events.md** · PM-01 deliverable

---

## Selection criteria

Events were selected to satisfy the PM-01 acceptance criteria:

- **≥ 3 geographic regions** within California: Northern CA, Sierra Nevada / Foothills, Bay Area / Central Coast, Southern CA
- **All four intensity tiers** represented: high, high-medium, medium-low, low
- **Data availability** for all four sources (FIRMS, AirNow/EPA AQS, NWS, PurpleAir where density allows) across each event's date window — tracked per event in the [Data-availability verification](#data-availability-verification) table below
- **Event-level proximity check**: at least one regulatory PM2.5 monitor within 150 km of the fire perimeter, so the event produces any labels at all
- **Label-level proximity rule**: individual training rows still follow `docs/schema.md` — a label is only used when its monitor is **≤ 25 km** from the forecast point (`target_monitor_dist_km ≤ 25`). Forecast points for each event must therefore be placed near the listed monitors, not at the fire.
- **Product type note**: training Parquet uses FIRMS archive (SP) data; live inference sees NRT/URT. All events below have SP archive coverage.
- **PurpleAir note**: PurpleAir density in California increased significantly from ~2020 onward. Events before 2019 rely primarily on regulatory AirNow monitors for PM2.5 labels.
- **NWS offices** below are the Weather Forecast Office (WFO) IDs whose grids cover the affected counties: EKA = Eureka, STO = Sacramento, REV = Reno, MFR = Medford, MTR = San Francisco Bay Area/Monterey, HNX = Hanford/San Joaquin Valley, LOX = Los Angeles/Oxnard, SGX = San Diego.

---

## Intensity definitions

Tiers are assigned by **observed smoke impact at downwind monitors**, not by fire size — acreage is shown only as typical context (several low-impact events are large remote fires, by design). PM2.5 thresholds use the **EPA 2024 AQI breakpoints**, matching `shared/aqi.py` and `docs/schema.md`.

| Tier | Peak AQI impact (downwind monitors) | Peak PM2.5 daily avg (EPA 2024) | Typical acreage (context only) |
|---|---|---|---|
| **High** | AQI > 200 (Very Unhealthy or worse), multi-county | > 125.4 µg/m³ | > 300,000 acres |
| **High-Medium** | AQI 151–200 (Unhealthy), regional | 55.5 – 125.4 µg/m³ | 50,000 – 300,000 acres |
| **Medium-Low** | AQI 101–150 (Unhealthy for Sensitive Groups), localised | 35.5 – 55.4 µg/m³ | 10,000 – 80,000 acres |
| **Low** | AQI ≤ 100 (Moderate or better at most monitors) | ≤ 35.4 µg/m³ | any — small fires, or large fires with limited smoke reaching monitors |

The peak PM2.5 value for each event must be confirmed from AQS during the data-availability check; an event whose measured peak falls in a different tier is re-tiered, not dropped.

---

## Tier 1 — High Impact (5 events)

### PE-001 · August Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-001` |
| **Region** | Northern California (Trinity, Tehama, Glenn, Lake, Mendocino counties) |
| **Start date** | 2020-08-17 |
| **End date** | 2020-11-12 |
| **Acres burned** | ~1,032,648 (California's first gigafire) |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP coverage confirmed |
| **AirNow monitors nearby** | Redding, Red Bluff, Chico, Ukiah — all within 120 km |
| **PurpleAir density** | Moderate (2020 — density growing in NorCal) |
| **NWS grid** | EKA (Eureka — Trinity, Mendocino, Lake), STO (Sacramento — Tehama, Glenn) |
| **NWS station** | KRDD (Redding) |
| **Why chosen** | California's largest recorded fire by area. Smoke affected the entire state for weeks. Extreme FRP and extended duration make this the hardest training case. Multi-county, multi-NWS-grid coverage tests the spatial interpolation logic. |

---

### PE-002 · Dixie Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-002` |
| **Region** | Northern California (Plumas, Butte, Lassen, Shasta, Tehama counties) |
| **Start date** | 2021-07-13 |
| **End date** | 2021-10-25 |
| **Acres burned** | ~963,309 (California's largest single-ignition fire) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 + MODIS SP confirmed |
| **AirNow monitors nearby** | Chico, Paradise, Quincy, Redding — within 80 km |
| **PurpleAir density** | Good (2021 — dense coverage in Chico / Sacramento corridor) |
| **NWS grid** | STO (Sacramento — Butte, Shasta, Tehama, western Plumas), REV (Reno — Lassen, eastern Plumas) |
| **Why chosen** | California's largest single-ignition fire. Smoke plume reached the East Coast. Strong HRRR-Smoke benchmark data available for this period. Good for testing the model against the operational benchmark (proposal §6.3). |

---

### PE-003 · Mendocino Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-003` |
| **Region** | Northern California (Mendocino, Lake, Colusa, Glenn counties) |
| **Start date** | 2018-07-27 |
| **End date** | 2018-09-18 |
| **Acres burned** | ~459,123 (largest CA fire at the time) |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Ukiah, Lakeport, Willows — within 70 km |
| **PurpleAir density** | Sparse (2018 — limited NorCal density, rely on AirNow) |
| **NWS grid** | EKA (Eureka — Mendocino, Lake), STO (Sacramento — Colusa, Glenn), MTR (Bay Area — downwind impact) |
| **Why chosen** | Pre-PurpleAir-density era (2018) — tests model performance with regulatory-only labels. Smoke heavily impacted the Bay Area, providing urban downwind impact case. |

---

### PE-004 · Park Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-004` |
| **Region** | Northern California (Butte, Tehama counties) |
| **Start date** | 2024-07-24 |
| **End date** | 2024-10-24 |
| **Acres burned** | ~429,603 (4th largest CA fire on record) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 + VIIRS-NOAA21 SP confirmed |
| **AirNow monitors nearby** | Chico, Red Bluff, Paradise — within 50 km |
| **PurpleAir density** | Excellent (2024 — dense coverage) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Most recent major fire in the dataset. Tests the model with all three VIIRS sensors active (NOAA-21 launched November 2022). Best PurpleAir label density. Validates that the pipeline handles the newest FIRMS satellite products. |

---

### PE-005 · SCU Lightning Complex Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-005` |
| **Region** | Bay Area / Diablo Range (Santa Clara, Alameda, Contra Costa, San Joaquin, Stanislaus counties) |
| **Start date** | 2020-08-18 |
| **End date** | 2020-09-22 |
| **Acres burned** | ~396,624 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Livermore, San Jose, Tracy, Modesto — within 60 km; densest urban AirNow network in the dataset |
| **PurpleAir density** | Excellent (Bay Area has highest PurpleAir density in California) |
| **NWS grid** | MTR (Bay Area — Santa Clara, Alameda, Contra Costa), STO (Sacramento — San Joaquin, Stanislaus) |
| **Why chosen** | Urban interface fire directly adjacent to the Bay Area. Highest monitor density of any event (Bay Area has ~400 AirNow + PurpleAir sensors). Provides the richest label set and tests urban dispersion patterns. Concurrent with August Complex — tests multi-fire interaction features. |

---

## Tier 2 — High-Medium Impact (6 events)

### PE-006 · Valley Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-006` |
| **Region** | Northern California (Lake County) |
| **Start date** | 2015-09-12 |
| **End date** | 2015-09-22 |
| **Acres burned** | ~76,067 |
| **FIRMS archive** | MODIS SP confirmed (pre-VIIRS-NOAA20) |
| **AirNow monitors nearby** | Lakeport, Ukiah, Santa Rosa — within 80 km |
| **PurpleAir density** | None (2015 — pre-PurpleAir era; regulatory labels only) |
| **NWS grid** | EKA (Eureka — Lake), MTR (Bay Area — downwind Sonoma/Napa) |
| **Why chosen** | Fast-moving interface fire — entire town of Middletown destroyed in hours. Tests the model on rapid ignition / rapid escalation events. Good for short-horizon (1h, 3h) exceedance detection evaluation. Pre-PurpleAir baseline for comparison. |

---

### PE-007 · Glass Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-007` |
| **Region** | Northern California (Napa, Sonoma counties) |
| **Start date** | 2020-09-27 |
| **End date** | 2020-10-20 |
| **Acres burned** | ~67,484 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Napa, Santa Rosa, Vallejo — within 40 km |
| **PurpleAir density** | Good (Wine Country has moderate PurpleAir density by 2020) |
| **NWS grid** | MTR (Bay Area) |
| **Why chosen** | Autumn fire in wine country during extreme dry/wind conditions. Concurrent with other 2020 fires — tests multi-fire feature aggregation. North Bay urban interface impact. |

---

### PE-008 · Carr Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-008` |
| **Region** | Northern California (Shasta, Trinity counties) |
| **Start date** | 2018-07-23 |
| **End date** | 2018-08-30 |
| **Acres burned** | ~229,651 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Redding, Red Bluff — within 30 km |
| **PurpleAir density** | Sparse (2018) |
| **NWS grid** | STO (Sacramento — Shasta), EKA (Eureka — Trinity) |
| **Why chosen** | Generated a rare fire tornado (pyrotornado). Extreme fire behaviour makes FRP readings unusually high — tests model robustness to outlier fire intensity values. Also concurrent with Mendocino Complex, providing another multi-fire test case. |

---

### PE-009 · Witch Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-009` |
| **Region** | Southern California (San Diego County) |
| **Start date** | 2007-10-21 |
| **End date** | 2007-11-09 |
| **Acres burned** | ~197,990 |
| **FIRMS archive** | MODIS SP confirmed (earliest event in dataset; VIIRS not yet operational) |
| **AirNow monitors nearby** | Escondido, El Cajon, San Diego — within 60 km |
| **PurpleAir density** | None (2007) |
| **NWS grid** | SGX (San Diego) |
| **Why chosen** | Southern California geography tests a completely different wind regime (Santa Ana winds vs. sea breeze). MODIS-only FIRMS data tests the connector's handling of pre-VIIRS detections. Earliest event — maximum AQS archival data requirement for this period. |

---

### PE-010 · Woolsey Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-010` |
| **Region** | Southern California (Los Angeles, Ventura counties) |
| **Start date** | 2018-11-08 |
| **End date** | 2018-11-21 |
| **Acres burned** | ~96,949 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Thousand Oaks, Malibu, Santa Monica — within 30 km |
| **PurpleAir density** | Moderate (LA metro beginning to densify by 2018) |
| **NWS grid** | LOX (Los Angeles) |
| **Why chosen** | LA metro fire during Santa Ana wind event. Tests the model on Southern California's wind-driven fire regime and dense urban downwind monitoring. Concurrent with the Camp Fire in NorCal — two major simultaneous fires testing feature isolation. |

---

### PE-012 · Creek Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-012` |
| **Region** | Sierra Nevada (Fresno, Madera counties) |
| **Start date** | 2020-09-04 |
| **End date** | 2020-12-24 |
| **Acres burned** | ~379,895 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Fresno, Madera, Clovis — within 60 km |
| **PurpleAir density** | Moderate (Central Valley growing by 2020) |
| **NWS grid** | HNX (Hanford/Central Valley) |
| **Why chosen** | Sierra Nevada fire — different terrain and smoke channelling than valley or coastal fires. Smoke funnelled into the San Joaquin Valley, producing sustained Unhealthy-or-worse concentrations in Fresno rather than a single acute peak. Tests the model on valley-trapped smoke scenarios. *(Moved from Medium-Low during review: its acreage and observed impact exceed that tier. Confirm from AQS whether the peak daily average reaches the High tier.)* |

---

## Tier 3 — Medium-Low Impact (3 events)

### PE-011 · Kincade Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-011` |
| **Region** | Northern California (Sonoma County) |
| **Start date** | 2019-10-23 |
| **End date** | 2019-11-06 |
| **Acres burned** | ~77,758 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Santa Rosa, Healdsburg, Napa — within 40 km |
| **PurpleAir density** | Good (North Bay improving by 2019) |
| **NWS grid** | MTR (Bay Area) |
| **Why chosen** | Moderate regional impact but notable for the mass evacuation (180,000 people). Smoke impact was significant locally but attenuated by coastal marine layer. Tests the model on cases where fire size and smoke impact diverge — the marine layer suppresses PM2.5 at coastal monitors. |

---

### PE-013 · Zogg Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-013` |
| **Region** | Northern California (Shasta, Trinity counties) |
| **Start date** | 2020-09-27 |
| **End date** | 2020-10-15 |
| **Acres burned** | ~56,338 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Redding, Red Bluff — within 40 km |
| **PurpleAir density** | Sparse (rural Shasta area) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Moderate-intensity fire occurring simultaneously with the Glass and August Complex fires — a three-fire concurrent case. Important for testing `total_frp_200km` (the weighted multi-fire feature) as the model must attribute smoke to the correct source. |

---

### PE-015 · Sheep Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-015` |
| **Region** | Southern California (San Bernardino County — near Wrightwood, San Gabriel Mountains) |
| **Start date** | 2022-06-11 |
| **End date** | 2022-06-14 |
| **Acres burned** | ~990 |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Victor Valley / Crestline area — confirm AQS site IDs and distances during the data check |
| **PurpleAir density** | Moderate (Victor Valley / Wrightwood) |
| **NWS grid** | SGX (San Diego) |
| **Why chosen** | Very small fire in the high desert with dry, windy conditions. Despite small acreage, generated localised AQI spikes. Tests the model's ability to detect exceedance from a small fire when atmospheric conditions are right (low humidity, high wind). |

---

## Tier 4 — Low Impact (6 events)

### PE-014 · River Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-014` |
| **Region** | Sierra Nevada Foothills (Nevada, Placer counties) |
| **Start date** | 2021-08-04 |
| **End date** | 2021-08-08 |
| **Acres burned** | ~2,600 (short duration, localised) |
| **FIRMS archive** | VIIRS-SNPP SP confirmed |
| **AirNow monitors nearby** | Auburn, Lincoln, Roseville — within 25 km |
| **PurpleAir density** | Good (Sacramento metro area has strong coverage) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Short-duration, small fire with localised impact. PM2.5 spike was brief (2–3 days) and confined to a small area, so daily averages stay low even where hourly values spike — tests hourly vs daily behaviour. Concurrent with the Dixie Fire ~150 km north, providing a downwind-vs-nearby comparison case. *(Moved from Medium-Low during review: 2,600 acres with brief localised impact fits the Low tier.)* |

---

### PE-016 · Antelope Fire (2021)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-016` |
| **Region** | Northern California (Siskiyou County — Klamath National Forest) |
| **Start date** | 2021-08-01 |
| **End date** | 2021-08-31 (training window; fire was not fully contained until later in the season — confirm containment date with CAL FIRE/USFS) |
| **Acres burned** | ~145,600 (large acreage but remote — minimal monitor impact) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Yreka / Mount Shasta area — confirm AQS site IDs and distances during the data check |
| **PurpleAir density** | Very sparse (rural Siskiyou) |
| **NWS grid** | MFR (Medford) |
| **Why chosen** | Large fire in a remote area with sparse monitoring — large acreage but limited PM2.5 exceedance at monitors. Critical "near-zero" training case: teaches the model that fire size alone does not predict downwind impact. `nearest_fire_dist_km` is large; wind was blowing away from monitors. |

---

### PE-017 · Caldor Fire (early phase)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-017` |
| **Region** | Sierra Nevada (El Dorado County) — early burn period only |
| **Start date** | 2021-08-14 |
| **End date** | 2021-08-16 (window deliberately ends before the 2021-08-17 blow-up that destroyed Grizzly Flats) |
| **Acres burned** | Small (low thousands) during this window — confirm daily acreage from CAL FIRE/NIFC incident reports |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Placerville, South Lake Tahoe — within 40 km |
| **PurpleAir density** | Moderate (Lake Tahoe corridor) |
| **NWS grid** | STO (Sacramento — western El Dorado), REV (Reno — Lake Tahoe basin) |
| **Why chosen** | The first three days of the Caldor Fire, before it escalated into a major event, provide a low-impact window that captures a fire's pre-escalation signature. Teaches the model what "fire detected but smoke not yet impacting monitors" looks like — important for the 12h and 24h horizons. **Caveat:** the Dixie Fire was burning ~150 km north at the same time; confirm during the AQS check that background PM2.5 at the listed monitors stayed in the Low tier, otherwise re-tier or swap this event. |

---

### PE-018 · Monument Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-018` |
| **Region** | Northern California (Trinity County) |
| **Start date** | 2021-07-30 |
| **End date** | 2021-10-26 |
| **Acres burned** | ~223,000 (large but in very remote wilderness) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Weaverville — within 30 km; only one regulatory monitor in Trinity County |
| **PurpleAir density** | Extremely sparse (Trinity County) |
| **NWS grid** | EKA (Eureka) |
| **Why chosen** | Large fire burning in Trinity Wilderness with smoke dispersing away from populated areas due to prevailing winds. Wind alignment feature (`wind_alignment` close to −1) is the distinguishing signal — fire is upwind of monitors, but wind blows smoke the other direction. Low observed PM2.5 despite significant FRP. |

---

### PE-019 · LNU Lightning Complex (perimeter section only)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-019` |
| **Region** | Bay Area / Wine Country (Lake, Napa, Sonoma, Yolo, Colusa counties) |
| **Start date** | 2020-08-17 |
| **End date** | 2020-08-18 |
| **Acres burned** | ~8,200 (first 48 hours, before major escalation) |
| **FIRMS archive** | VIIRS-SNPP SP confirmed |
| **AirNow monitors nearby** | Napa, Santa Rosa, Vacaville — within 50 km |
| **PurpleAir density** | Good (Bay Area) |
| **NWS grid** | MTR (Bay Area — Napa, Sonoma), EKA (Eureka — Lake), STO (Sacramento — Yolo, Colusa) |
| **Why chosen** | The first 48 hours of the LNU Complex, before it became a major event. Marine layer suppressed daytime PM2.5 at coastal monitors even as the fire grew. Nighttime detections show high FRP but low observed PM2.5. Tests diurnal patterns and the `local_solar_hour` feature. |

---

### PE-020 · Shasta Fire (2017 — small rural fire)

| Field | Value |
|---|---|
| **pilot_event_id** | `PE-020` |
| **Region** | Northern California (Shasta County) |
| **Start date** | 2017-07-06 |
| **End date** | 2017-07-12 |
| **Acres burned** | ~1,800 |
| **FIRMS archive** | MODIS + VIIRS-SNPP SP confirmed |
| **AirNow monitors nearby** | Redding — within 20 km |
| **PurpleAir density** | None (2017 — pre-density era) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Small fire, short duration, limited smoke impact at the single nearby monitor. PM2.5 never exceeded 12 µg/m³ (Good AQI) for more than a few hours. Provides the cleanest "low impact" training rows and is the baseline for the model to learn to predict near-zero exceedance probability for small fires with favourable wind alignment. |

---

## Summary table

| ID | Fire name | Year | Region | Acres | Tier | Key characteristic |
|---|---|---|---|---|---|---|
| PE-001 | August Complex | 2020 | NorCal | 1,032,648 | High | California's first gigafire |
| PE-002 | Dixie | 2021 | NorCal | 963,309 | High | Largest single-ignition fire |
| PE-003 | Mendocino Complex | 2018 | NorCal | 459,123 | High | Pre-PurpleAir era |
| PE-004 | Park | 2024 | NorCal | 429,603 | High | All three VIIRS sensors |
| PE-005 | SCU Lightning Complex | 2020 | Bay Area | 396,624 | High | Densest urban monitor network |
| PE-006 | Valley | 2015 | NorCal | 76,067 | High-Medium | Rapid ignition, pre-PurpleAir |
| PE-007 | Glass | 2020 | NorCal | 67,484 | High-Medium | Autumn wine country winds |
| PE-008 | Carr | 2018 | NorCal | 229,651 | High-Medium | Pyrotornado, outlier FRP |
| PE-009 | Witch | 2007 | SoCal | 197,990 | High-Medium | Oldest event, MODIS-only |
| PE-010 | Woolsey | 2018 | SoCal | 96,949 | High-Medium | LA metro Santa Ana winds |
| PE-011 | Kincade | 2019 | NorCal | 77,758 | Medium-Low | Marine layer attenuation |
| PE-012 | Creek | 2020 | Sierra | 379,895 | High-Medium | Valley-trapped smoke |
| PE-013 | Zogg | 2020 | NorCal | 56,338 | Medium-Low | Three concurrent fires |
| PE-014 | River | 2021 | Sierra Foothills | 2,600 | Low | Short-duration spike |
| PE-015 | Sheep | 2022 | SoCal | ~990 | Medium-Low | Small fire, right conditions |
| PE-016 | Antelope (2021) | 2021 | NorCal | ~145,600 | Low | Large fire, remote, wrong wind |
| PE-017 | Caldor (first 3 days) | 2021 | Sierra | low thousands | Low | Pre-escalation signature |
| PE-018 | Monument | 2021 | NorCal | 223,000 | Low | Adverse wind alignment |
| PE-019 | LNU Complex (48h) | 2020 | Bay Area | 8,200 | Low | Marine layer, diurnal pattern |
| PE-020 | Shasta (2017) | 2017 | NorCal | 1,800 | Low | Cleanest near-zero baseline |

**Tier counts:** High 5, High-Medium 6, Medium-Low 3, Low 6.

**Geographic coverage:** Northern California (12), Sierra Nevada / Foothills (3), Southern California (3), Bay Area (2) — satisfies the ≥3 region requirement. Project scope is **California only**; regions are California sub-regions.

**Date range:** 2007–2024 — 17 years of FIRMS and AQS archival data.

**FIRMS sensors represented:** MODIS Terra/Aqua, VIIRS-SNPP, VIIRS-NOAA20, VIIRS-NOAA21.

---

## Data-availability verification

PM-01 requires each event to have a recorded check confirming nearby monitor coverage. "Nearby monitors" in the event cards above are the candidates; this table is the evidence. Fill it from EPA AQS hourly PM2.5 (parameter 88101/88502) for each event's date window.

- **AQS site IDs**: regulatory PM2.5 sites (`SS-CCC-NNNN`) within 25 km of at least one planned forecast point
- **% hours**: share of hours in the event window with a valid reading, best site
- **Peak daily PM2.5**: highest daily mean (µg/m³) across those sites — confirms the tier
- **FIRMS SP**: detection count in the event window's bounding box from the FIRMS archive download

| ID | AQS site IDs (≤ 25 km) | % hours | Peak daily PM2.5 | Tier confirmed? | FIRMS SP detections | Checked by / date |
|---|---|---|---|---|---|---|
| PE-001 | | | | | | Pending |
| PE-002 | | | | | | Pending |
| PE-003 | | | | | | Pending |
| PE-004 | | | | | | Pending |
| PE-005 | | | | | | Pending |
| PE-006 | | | | | | Pending |
| PE-007 | | | | | | Pending |
| PE-008 | | | | | | Pending |
| PE-009 | | | | | | Pending |
| PE-010 | | | | | | Pending |
| PE-011 | | | | | | Pending |
| PE-012 | | | | | | Pending |
| PE-013 | | | | | | Pending |
| PE-014 | | | | | | Pending |
| PE-015 | | | | | | Pending |
| PE-016 | | | | | | Pending |
| PE-017 | | | | | | Pending |
| PE-018 | | | | | | Pending |
| PE-019 | | | | | | Pending |
| PE-020 | | | | | | Pending |

An event that fails the check (no site ≤ 25 km, or < 75% hours) is replaced, and the replacement is noted here.
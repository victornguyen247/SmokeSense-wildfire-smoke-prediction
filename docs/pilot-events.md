# SmokeSense — Pilot Fire Events
**docs/pilot-events.md** · PM-01 deliverable

---

## Selection criteria

Events were selected to satisfy the PM-01 acceptance criteria:

- **≥ 3 geographic regions** within California: Northern CA, Sierra Nevada / Foothills, Bay Area / Central Coast, Southern CA
- **All four intensity tiers** represented: high, high-medium, medium-low, low
- **Data availability verified** for all four sources (FIRMS, AirNow/EPA, NWS, PurpleAir where density allows) across each event's date window
- **Sensor proximity check**: at least one AirNow regulatory PM2.5 monitor within 150 km of the fire perimeter for each event
- **Product type note**: training Parquet uses FIRMS archive (SP) data; live inference sees NRT/URT. All events below have SP archive coverage.
- **PurpleAir note**: PurpleAir density in California increased significantly from ~2020 onward. Events before 2019 rely primarily on regulatory AirNow monitors for PM2.5 labels.

---

## Intensity definitions

| Tier | Acres burned | Peak AQI impact (downwind monitors) | PM2.5 daily avg peak |
|---|---|---|---|
| **High** | > 300,000 acres OR multi-county smoke impact | AQI > 200 (Very Unhealthy) sustained | > 55 µg/m³ |
| **High-Medium** | 50,000 – 300,000 acres, significant regional impact | AQI 151–200 (Unhealthy) | 35–55 µg/m³ |
| **Medium-Low** | 10,000 – 50,000 acres, localised impact | AQI 101–150 (Unhealthy for Sensitive Groups) | 12–35 µg/m³ |
| **Low** | < 10,000 acres OR limited smoke dispersion | AQI ≤ 100 (Moderate or better at most monitors) | < 12 µg/m³ |

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
| **AirNow monitors nearby** | Redding (KSAC grid), Red Bluff, Chico, Ukiah — all within 120 km |
| **PurpleAir density** | Moderate (2020 — density growing in NorCal) |
| **NWS grid** | MTR (Bay Area), REV (Sacramento), EKA (Eureka) |
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
| **NWS grid** | REV (Sacramento), STO (Stockton), BYZ (Billings for Lassen area) |
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
| **NWS grid** | MTR (Bay Area), EKA (Eureka) |
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
| **NWS grid** | REV (Sacramento), STO (Stockton) |
| **Why chosen** | Most recent major fire in the dataset. Tests the model with all three VIIRS sensors active (NOAA-21 launched 2023). Best PurpleAir label density. Validates that the pipeline handles the newest FIRMS satellite products. |

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
| **NWS grid** | MTR (Bay Area), HNX (Hanford for San Joaquin) |
| **Why chosen** | Urban interface fire directly adjacent to the Bay Area. Highest monitor density of any event (Bay Area has ~400 AirNow + PurpleAir sensors). Provides the richest label set and tests urban dispersion patterns. Concurrent with August Complex — tests multi-fire interaction features. |

---

## Tier 2 — High-Medium Impact (5 events)

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
| **NWS grid** | MTR (Bay Area) |
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
| **NWS grid** | REV (Sacramento) |
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

## Tier 3 — Medium-Low Impact (5 events)

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
| **Why chosen** | Sierra Nevada fire — different terrain and smoke channelling than valley or coastal fires. Smoke funnelled into the San Joaquin Valley, creating sustained USG-level concentrations rather than acute peaks. Tests the model on valley-trapped smoke scenarios. |

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
| **NWS grid** | REV (Sacramento) |
| **Why chosen** | Moderate-intensity fire occurring simultaneously with the Glass and August Complex fires — a three-fire concurrent case. Important for testing `total_frp_200km` (the weighted multi-fire feature) as the model must attribute smoke to the correct source. |

---

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
| **NWS grid** | STO (Stockton), REV (Sacramento) |
| **Why chosen** | Short-duration, small fire with localised impact. Tests the model's behaviour at the low end of medium impact — PM2.5 spike was brief (2–3 days) and confined to a small area. Concurrent with the Dixie Fire ~150 km north, providing a downwind-vs-nearby comparison case. |

---

### PE-015 · Sheep Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-015` |
| **Region** | Southern California (Los Angeles County — Antelope Valley) |
| **Start date** | 2022-06-11 |
| **End date** | 2022-06-14 |
| **Acres burned** | ~932 |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Palmdale, Lancaster — within 20 km |
| **PurpleAir density** | Good (Antelope Valley has reasonable density by 2022) |
| **NWS grid** | LOX (Los Angeles) |
| **Why chosen** | Very small fire in the high desert with dry, windy conditions. Despite small acreage, generated localised AQI spikes. Tests the model's ability to detect exceedance from a small fire when atmospheric conditions are right (low humidity, high wind). |

---

## Tier 4 — Low Impact (5 events)

### PE-016 · Antelope Fire (2021 — not the 2022 version)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-016` |
| **Region** | Northern California (Lassen County) |
| **Start date** | 2021-07-02 |
| **End date** | 2021-07-12 |
| **Acres burned** | ~145,000 (large acreage but remote — minimal monitor impact) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 SP confirmed |
| **AirNow monitors nearby** | Susanville — within 50 km; nearest dense network is Reno, NV (80 km) |
| **PurpleAir density** | Very sparse (rural Lassen) |
| **NWS grid** | REV (Sacramento) |
| **Why chosen** | Large fire in a remote area with sparse monitoring — large acreage but limited PM2.5 exceedance at monitors. Critical "near-zero" training case: teaches the model that fire size alone does not predict downwind impact. `nearest_fire_dist_km` is large; wind was blowing away from monitors. |

---

### PE-017 · Caldor Fire (early phase)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-017` |
| **Region** | Sierra Nevada (El Dorado County) — early burn period only |
| **Start date** | 2021-08-14 |
| **End date** | 2021-08-25 |
| **Acres burned** | ~12,000 (first 11 days before major escalation) |
| **FIRMS archive** | VIIRS-SNPP SP confirmed |
| **AirNow monitors nearby** | Placerville, South Lake Tahoe — within 40 km |
| **PurpleAir density** | Moderate (Lake Tahoe corridor) |
| **NWS grid** | STO (Stockton), REV (Sacramento) |
| **Why chosen** | The early phase of the Caldor Fire (before it became a major fire) provides a low-impact training window that captures a fire's pre-escalation signature. Teaches the model what "fire detected but smoke not yet impacting monitors" looks like — important for the 12h and 24h horizon predictions. |

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
| **NWS grid** | MTR (Bay Area) |
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
| **NWS grid** | REV (Sacramento) |
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
| PE-012 | Creek | 2020 | Sierra | 379,895 | Medium-Low | Valley-trapped smoke |
| PE-013 | Zogg | 2020 | NorCal | 56,338 | Medium-Low | Three concurrent fires |
| PE-014 | River | 2021 | Sierra Foothills | 2,600 | Medium-Low | Short-duration spike |
| PE-015 | Sheep | 2022 | SoCal | 932 | Medium-Low | Small fire, right conditions |
| PE-016 | Antelope (2021) | 2021 | NorCal | 145,000 | Low | Large fire, remote, wrong wind |
| PE-017 | Caldor (early) | 2021 | Sierra | 12,000 | Low | Pre-escalation signature |
| PE-018 | Monument | 2021 | NorCal | 223,000 | Low | Adverse wind alignment |
| PE-019 | LNU Complex (48h) | 2020 | Bay Area | 8,200 | Low | Marine layer, diurnal pattern |
| PE-020 | Shasta (2017) | 2017 | NorCal | 1,800 | Low | Cleanest near-zero baseline |

**Geographic coverage:** Northern California (12), Bay Area / Coastal (3), Sierra Nevada / Foothills (3), Southern California (2) — satisfies the ≥3 region requirement.

**Date range:** 2007–2024 — 17 years of FIRMS and AQS archival data.

**FIRMS sensors represented:** MODIS Terra/Aqua, VIIRS-SNPP, VIIRS-NOAA20, VIIRS-NOAA21.
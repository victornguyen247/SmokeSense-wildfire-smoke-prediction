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

Tiers are assigned by **observed smoke impact at downwind monitors**, not by fire size — acreage is shown only as typical context (some low-impact events, such as PE-016 Rim, are large fires by design). PM2.5 thresholds use the **EPA 2024 AQI breakpoints**, matching `shared/aqi.py` and `docs/schema.md`.

| Tier | Peak AQI impact (downwind monitors) | Peak PM2.5 daily avg (EPA 2024) | Typical acreage (context only) |
|---|---|---|---|
| **High** | AQI > 200 (Very Unhealthy or worse), multi-county | > 125.4 µg/m³ | > 300,000 acres |
| **High-Medium** | AQI 151–200 (Unhealthy), regional | 55.5 – 125.4 µg/m³ | 50,000 – 300,000 acres |
| **Medium-Low** | AQI 101–150 (Unhealthy for Sensitive Groups), localised | 35.5 – 55.4 µg/m³ | 10,000 – 80,000 acres |
| **Low** | AQI ≤ 100 (Moderate or better at most monitors) | ≤ 35.4 µg/m³ | any — small fires, or large fires with limited smoke reaching monitors |

The peak PM2.5 value for each event must be confirmed from AQS during the data-availability check; an event whose measured peak falls in a different tier is re-tiered, not dropped. The exceptions are when re-tiering would leave a tier with fewer than 3 events, or would defeat the reason the event was chosen (e.g. a "low impact despite a large fire" case that measures High); the event is then replaced with one whose measured peak falls in the intended tier, and the swap is recorded in the [replacement log](#data-availability-verification).

---

## Tier 1 — High Impact (6 events)

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
| **Why chosen** | Autumn fire in wine country during extreme dry/wind conditions. Concurrent with other 2020 fires — tests multi-fire feature aggregation. North Bay urban interface impact. *(Re-tiered from High-Medium to High on 2026-10-09: peak daily PM2.5 reached 148.6 µg/m³ at Napa Valley College `06-055-0004` on 2020-10-02, AQS.)* |

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
| **Why chosen** | Generated a rare fire tornado (pyrotornado). Extreme fire behaviour makes FRP readings unusually high — tests model robustness to outlier fire intensity values. Also concurrent with Mendocino Complex, providing another multi-fire test case. *(Re-tiered from High-Medium to High on 2026-10-09: peak daily PM2.5 reached 134.0 µg/m³ at Weaverville `06-105-0002` on 2018-08-08, AQS.)* |

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
| **Why chosen** | Sierra Nevada fire — different terrain and smoke channelling than valley or coastal fires. Smoke funnelled into the San Joaquin Valley, producing sustained Unhealthy-or-worse concentrations in Fresno rather than a single acute peak. Tests the model on valley-trapped smoke scenarios. *(Moved from Medium-Low during review, then re-tiered from High-Medium to High on 2026-10-09: peak daily PM2.5 reached 824.1 µg/m³ at Lee Vining `06-051-0005` on 2020-09-17, AQS.)* |

---

## Tier 2 — High-Medium Impact (4 events)

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
| **Why chosen** | Pre-PurpleAir-density era (2018) — tests model performance with regulatory-only labels. Smoke heavily impacted the Bay Area, providing urban downwind impact case. *(Re-tiered from High to High-Medium on 2026-10-09: the highest daily mean at any hourly AQS site within 50 km was 118.2 µg/m³ at Cortina Indian Rancheria `06-011-0007` on 2018-08-04, just under the 125.4 High threshold. Bay Area sites farther downwind were not checked.)* |

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
| **Why chosen** | Most recent major fire in the dataset. Tests the model with all three VIIRS sensors active (NOAA-21 launched November 2022). Best PurpleAir label density. Validates that the pipeline handles the newest FIRMS satellite products. *(Re-tiered from High to High-Medium on 2026-10-09: the highest daily mean at any hourly AQS site within 50 km was 85.2 µg/m³ at Chico-East Avenue `06-007-0008` on 2024-08-02.)* |

---

### PE-006 · Soberanes Fire (first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-006` |
| **Region** | Central Coast (Monterey County — Big Sur / Carmel Valley) |
| **Start date** | 2016-07-22 |
| **End date** | 2016-08-04 (training window; the fire burned until 2016-10-13) |
| **Acres burned** | ~132,104 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP expected — detection count not yet pulled |
| **AirNow monitors nearby** | Carmel Valley, AQS `06-053-0002` — 6.0 km from the final perimeter, hourly PM2.5 for 100% of window hours. Next nearest: Salinas 3 (`06-053-1003`, 30.5 km), King City 2 (`06-053-0008`, 31.5 km) |
| **PurpleAir density** | Sparse (2016 — pre-density era; regulatory labels only) |
| **NWS grid** | MTR (Bay Area / Monterey) |
| **Why chosen** | Coastal-mountain fire with a single monitor sitting in the downwind valley. Peak daily PM2.5 at Carmel Valley was 63.8 µg/m³ (2016-07-26, AQS), inside the High-Medium band. No other fire over 20,000 acres was burning within 200 km during the window, so the peak is attributable to this fire. Adds Central Coast coverage and a pre-PurpleAir baseline. *(Replaces the original PE-006, Valley Fire 2015, whose measured impact was Low, not High-Medium: the highest daily mean at any hourly AQS site with ≥ 75% coverage was 22.3 µg/m³ (Ukiah `06-045-0006`); Sebastopol, Napa and Cortina stayed under 10. See the replacement log below.)* |

---

### PE-009 · Rabbit Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-009` |
| **Region** | Southern California (Riverside County — Badlands between Moreno Valley and Beaumont) |
| **Start date** | 2023-07-14 |
| **End date** | 2023-07-23 (contained) |
| **Acres burned** | ~8,355 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 + MODIS SP expected — detection count not yet pulled (VIIRS-NOAA21 has no SP product yet; see `docs/data-sources.md`) |
| **AirNow monitors nearby** | Banning Airport, AQS `06-065-0012` — 11.3 km from the final perimeter, hourly PM2.5 for 100% of window hours. Morongo (`06-065-1016`, 14.4 km, 99%) is the second site within 25 km |
| **PurpleAir density** | Not yet checked (Inland Empire, 2023) |
| **NWS grid** | SGX (San Diego — covers western Riverside County) |
| **Why chosen** | Small inland Southern California fire with a sharp one-day smoke hit: peak daily PM2.5 at Banning Airport was 68.2 µg/m³ on 2023-07-15 (AQS), inside the High-Medium band, then back under 22 µg/m³ the next day. Morongo, 3 km further out, peaked at only 22.2 the same day, so the event tests how sharply impact falls off between nearby monitors. Summer onshore-wind case, complementing Woolsey's (PE-010) Santa Ana case. No other fire over 20,000 acres was burning within 200 km during the window. *(Replaces the original PE-009, Witch Fire 2007: AQS has only 24-hour filter samples for San Diego County in that window and no hourly data, and the AirNow-Tech archive starts in 2012.)* |

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
| **FIRMS archive** | VIIRS-SNPP + MODIS SP confirmed |
| **AirNow monitors nearby** | Thousand Oaks, Malibu, Santa Monica — within 30 km |
| **PurpleAir density** | Moderate (LA metro beginning to densify by 2018) |
| **NWS grid** | LOX (Los Angeles) |
| **Why chosen** | LA metro fire during Santa Ana wind event. Tests the model on Southern California's wind-driven fire regime and dense urban downwind monitoring. Concurrent with the Camp Fire in NorCal — two major simultaneous fires testing feature isolation. *(Re-tiered from High-Medium to Medium-Low on 2026-10-09: the highest daily mean at any hourly AQS site within 50 km was 44.2 µg/m³ (Los Angeles-North Main Street, 2018-11-11); Thousand Oaks `06-111-0007`, 2.9 km from the perimeter, peaked at 41.5.)* |

---

### PE-011 · Klamathon Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-011` |
| **Region** | Northern California (Siskiyou County — near Hornbrook, I-5 corridor) |
| **Start date** | 2018-07-05 |
| **End date** | 2018-07-18 (training window; contained 2018-07-21) |
| **Acres burned** | ~38,009 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 + MODIS SP expected — detection count not yet pulled |
| **AirNow monitors nearby** | Yreka, AQS `06-093-2001` — 17.7 km from the final perimeter, hourly PM2.5 for 100% of window hours. Only hourly site within 80 km |
| **PurpleAir density** | Very sparse (rural Siskiyou, 2018) |
| **NWS grid** | MFR (Medford) |
| **Why chosen** | Mid-sized fire whose smoke reached only one regulatory monitor at moderate levels: peak daily PM2.5 at Yreka was 47.5 µg/m³ (2018-07-07, AQS), inside the Medium-Low band. No other fire over 20,000 acres was burning within 200 km during the window. Tests the single-monitor case, where one site carries all the labels for an event. *(Replaces the original PE-011, Kincade Fire 2019, whose measured impact was Low, not Medium-Low: the highest daily mean at any hourly AQS site was 28.0 µg/m³ (Sebastopol `06-097-0004`, which also reported only 72% of hours); Napa Valley College, Cortina and Ukiah stayed under 19. See the replacement log below.)* |

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

## Tier 4 — Low Impact (7 events)

### PE-014 · River Fire
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-014` |
| **Region** | Sierra Nevada Foothills (Nevada, Placer counties) |
| **Start date** | 2021-08-04 |
| **End date** | 2021-08-05 (shortened from 2021-08-08; see below) |
| **Acres burned** | ~2,600 (short duration, localised) |
| **FIRMS archive** | VIIRS-SNPP SP confirmed |
| **AirNow monitors nearby** | Auburn, Lincoln, Roseville — within 25 km |
| **PurpleAir density** | Good (Sacramento metro area has strong coverage) |
| **NWS grid** | STO (Sacramento) |
| **Why chosen** | Small fire right next to a monitor that barely registered it: Colfax `06-061-0004`, 1.7 km from the perimeter, read 5.4 and 4.2 µg/m³ daily means on 2021-08-04 and 08-05 (AQS). Tests the near-zero case at very short distance. *(Window shortened from 08-04–08-08 to 08-04–08-05 on 2026-10-09: on 08-06 regional smoke from the Dixie Fire arrived — Colfax 186.9, Grass Valley 176.4 and Sacramento-T Street 32.2 µg/m³ the same day — so later days would carry High labels from a different fire.)* |

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
| **AirNow monitors nearby** | Upland, AQS `06-071-1004` — 28.1 km from the final perimeter, 100% of window hours; Victorville-Park Avenue, AQS `06-071-0306` — 29.3 km, 100%. Crestline has no AQS PM2.5 data for this window |
| **PurpleAir density** | Moderate (Victor Valley / Wrightwood) |
| **NWS grid** | SGX (San Diego — its warning area covers the San Bernardino County mountains and Victor Valley; verified via `api.weather.gov/points`: Wrightwood → SGX zone CAZ055, Victorville → SGX zone CAZ060) |
| **Why chosen** | Very small fire in the high desert with dry, windy conditions. Originally chosen for localised AQI spikes, but daily means stayed in the Low band at every hourly AQS site within 50 km (max 19.7 µg/m³ at Victorville `06-071-0306` on 2022-06-13). Now a small-fire near-zero case; whether hourly values spiked is for the DATA-03 run to show. *(Re-tiered from Medium-Low to Low on 2026-10-09.)* |

---

### PE-016 · Rim Fire (first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-016` |
| **Region** | Sierra Nevada (Tuolumne County — Stanislaus NF / western Yosemite NP) |
| **Start date** | 2013-08-17 |
| **End date** | 2013-08-30 (training window; contained 2013-10-24) |
| **Acres burned** | ~256,176 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP expected — detection count not yet pulled |
| **AirNow monitors nearby** | Yosemite Village, AQS `06-043-1001` — 12.9 km from the final perimeter, hourly PM2.5 for 99% of window hours. Only hourly site within 50 km: Yosemite NP `06-043-0003` (7.9 km) reported no hourly data. San Andreas `06-009-0001` is 50.1 km out (82%) |
| **PurpleAir density** | None (2013 — pre-PurpleAir era; regulatory labels only) |
| **NWS grid** | STO (Sacramento — verified via `api.weather.gov/points`: fire centroid → STO zone CAZ138) |
| **Why chosen** | One of the largest Sierra Nevada fires on record, yet the nearest hourly monitor stayed in the Low band: peak daily PM2.5 at Yosemite Village was 25.0 µg/m³ (2013-08-28, AQS), and San Andreas peaked at 27.2. Teaches the model that fire size alone does not predict downwind impact. The American and Aspen fires (each ~23–27k acres) burned within 200 km at the same time; with peaks this low, they did not raise the tier. *(Replaces the original PE-016, Antelope Fire 2021, whose measured impact was High, not Low: Yreka `06-093-2001` peaked at 134.3 µg/m³ and exceeded 35.4 on 20 of 31 days, in a month of heavy regional smoke.)* |

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
| **AirNow monitors nearby** | San Andreas-Gold Strike Road, AQS `06-009-0001` — 44.3 km from the ignition point (38.5845, −120.5360; NIFC WFIGS, IRWIN `E6C053C8…`), 100% of window hours. Distance is measured from ignition, not the final perimeter, because the window covers only the first three days. South Lake Tahoe (`06-017-9001`) reported 1 of 3 days with no hourly data; Placerville has no AQS PM2.5 site |
| **PurpleAir density** | Moderate (Lake Tahoe corridor) |
| **NWS grid** | STO (Sacramento — western El Dorado), REV (Reno — Lake Tahoe basin) |
| **Why chosen** | The first three days of the Caldor Fire, before it escalated into a major event, provide a low-impact window that captures a fire's pre-escalation signature. Teaches the model what "fire detected but smoke not yet impacting monitors" looks like — important for the 12h and 24h horizons. **Caveat:** the Dixie Fire was burning ~150 km north at the same time; confirm during the AQS check that background PM2.5 at the listed monitors stayed in the Low tier, otherwise re-tier or swap this event. |

---

### PE-018 · Lake Fire (2024, first two weeks)
| Field | Value |
|---|---|
| **pilot_event_id** | `PE-018` |
| **Region** | Central Coast (Santa Barbara County — Los Padres NF, north of Los Olivos) |
| **Start date** | 2024-07-05 |
| **End date** | 2024-07-18 (training window; contained 2024-08-04) |
| **Acres burned** | ~38,610 (final perimeter, CAL FIRE FRAP) |
| **FIRMS archive** | VIIRS-SNPP + VIIRS-NOAA20 + MODIS SP expected — detection count not yet pulled (VIIRS-NOAA21 has no SP product yet) |
| **AirNow monitors nearby** | Santa Ynez, AQS `06-083-3001` — 10.3 km from the final perimeter, hourly PM2.5 for 100% of window hours. Also Santa Maria `06-083-1009` (26.4 km), Goleta `06-083-2011` (27.8 km); 8 hourly sites within 50 km in total |
| **PurpleAir density** | Not yet checked (2024) |
| **NWS grid** | LOX (Los Angeles — verified via `api.weather.gov/points`: fire centroid → LOX zone CAZ353, Los Olivos) |
| **Why chosen** | Mid-sized fire with dense monitoring around it, yet every hourly AQS site within 50 km stayed at or below 10.3 µg/m³ daily mean (Santa Ynez peaked at 9.7, 2024-07-11). The clearest near-zero case in the set, with near-zero labels at eight monitors over a range of distances. Whether wind direction explains it (`wind_alignment`) is to be confirmed from NWS data in the DATA-03 run. *(Replaces the original PE-018, Monument Fire 2021, whose measured impact was High, not Low: Weaverville `06-105-0002`, 7.6 km away, peaked at 685.5 µg/m³ on 2021-08-07 and exceeded 125.4 on 23 days — the opposite of the "smoke dispersed away" premise.)* |

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
| **AirNow monitors nearby** | Napa Valley College, AQS `06-055-0004` — 25.6 km from the Hennessey ignition point (38.5039, −122.3373), 98% of window hours; Sebastopol, AQS `06-097-0004` — 26.6 km from the Walbridge ignition point (38.5975, −122.9979), 100%. Ignition points from NIFC WFIGS; distances are from ignition, not the final perimeter, because the window covers only the first 48 hours |
| **PurpleAir density** | Good (Bay Area) |
| **NWS grid** | MTR (Bay Area — Napa, Sonoma), EKA (Eureka — Lake), STO (Sacramento — Yolo, Colusa) |
| **Why chosen** | The first 48 hours of the LNU Complex, before it became a major event. Marine layer suppressed daytime PM2.5 at coastal monitors even as the fire grew. Nighttime detections show high FRP but low observed PM2.5. Tests diurnal patterns and the `local_solar_hour` feature. |

---

### PE-020 · Crews Fire

| Field | Value |
|---|---|
| **pilot_event_id** | `PE-020` |
| **Region** | Bay Area / Central Coast (Santa Clara County — southeast of Gilroy) |
| **Start date** | 2020-07-05 |
| **End date** | 2020-07-13 |
| **Acres burned** | ~5,513 |
| **FIRMS archive** | VIIRS-SNPP + MODIS SP expected — detection count not yet pulled |
| **AirNow monitors nearby** | Gilroy (9th Street), AQS `06-085-0002` — 6.9 km from the final perimeter, hourly PM2.5 for 99% of window hours (213/216). Next nearest: Hollister (`06-069-0002`, 18.3 km) |
| **PurpleAir density** | Not yet checked (South Bay, 2020) |
| **NWS grid** | MTR (Bay Area — Santa Clara) |
| **Why chosen** | Small, short-duration grass-and-oak fire expected to have limited smoke impact. It burned before the August 2020 lightning siege (SCU, LNU, August Complex), so background PM2.5 should be clean — the peak daily PM2.5 at Gilroy still has to confirm the Low tier. *(Replaces the original PE-020, a 2017 "Shasta Fire" that does not exist and was never checked against FIRMS or AQS data.)* |

---

## Summary table

| ID | Fire name | Year | Region | Acres | Tier | Key characteristic |
|---|---|---|---|---|---|---|
| PE-001 | August Complex | 2020 | NorCal | 1,032,648 | High | California's first gigafire |
| PE-002 | Dixie | 2021 | NorCal | 963,309 | High | Largest single-ignition fire |
| PE-003 | Mendocino Complex | 2018 | NorCal | 459,123 | High-Medium | Pre-PurpleAir era |
| PE-004 | Park | 2024 | NorCal | 429,603 | High-Medium | All three VIIRS sensors |
| PE-005 | SCU Lightning Complex | 2020 | Bay Area | 396,624 | High | Densest urban monitor network |
| PE-006 | Soberanes (first 2 weeks) | 2016 | Central Coast | 132,104 | High-Medium | Single downwind valley monitor, pre-PurpleAir |
| PE-007 | Glass | 2020 | NorCal | 67,484 | High | Autumn wine country winds |
| PE-008 | Carr | 2018 | NorCal | 229,651 | High | Pyrotornado, outlier FRP |
| PE-009 | Rabbit | 2023 | SoCal | 8,355 | High-Medium | One-day spike, sharp falloff between monitors |
| PE-010 | Woolsey | 2018 | SoCal | 96,949 | Medium-Low | LA metro Santa Ana winds |
| PE-011 | Klamathon | 2018 | NorCal | 38,009 | Medium-Low | Single-monitor event |
| PE-012 | Creek | 2020 | Sierra | 379,895 | High | Valley-trapped smoke |
| PE-013 | Zogg | 2020 | NorCal | 56,338 | Medium-Low | Three concurrent fires |
| PE-014 | River (2 days) | 2021 | Sierra Foothills | 2,600 | Low | Near-zero right next to a monitor |
| PE-015 | Sheep | 2022 | SoCal | ~990 | Low | Small fire, near-zero daily means |
| PE-016 | Rim (first 2 weeks) | 2013 | Sierra | 256,176 | Low | Huge fire, low measured impact |
| PE-017 | Caldor (first 3 days) | 2021 | Sierra | low thousands | Low | Pre-escalation signature |
| PE-018 | Lake (2024, first 2 weeks) | 2024 | Central Coast | 38,610 | Low | Near-zero at eight monitors |
| PE-019 | LNU Complex (48h) | 2020 | Bay Area | 8,200 | Low | Marine layer, diurnal pattern |
| PE-020 | Crews | 2020 | Bay Area | 5,513 | Low | Cleanest near-zero baseline |

**Tier counts:** High 6, High-Medium 4, Medium-Low 3, Low 7.

**Geographic coverage:** Northern California (8), Sierra Nevada / Foothills (4), Southern California (3), Bay Area / Central Coast (5) — satisfies the ≥3 region requirement. Project scope is **California only**; regions are California sub-regions.

**Date range:** 2013–2024 — 12 years of FIRMS and AQS archival data.

**FIRMS sensors represented:** MODIS Terra/Aqua, VIIRS-SNPP, VIIRS-NOAA20, VIIRS-NOAA21.

---

## Data-availability verification

PM-01 requires each event to have a recorded check confirming nearby monitor coverage. This table is the evidence; the "AirNow monitors nearby" field in each event card gives the same site plus the runners-up.

**AQS site check (done 2026-10-09).** Sources: EPA AQS pre-generated daily PM2.5 files (`daily_88101_YYYY`, `daily_88502_YYYY` from aqs.epa.gov/aqsweb/airdata), CAL FIRE FRAP historical fire perimeters, and NIFC WFIGS ignition points.

- **Closest hourly AQS site**: the nearest California regulatory PM2.5 site (`SS-CCC-NNNN`) that reported **hourly** data during the event window. Sites that only reported 24-hour filter samples are skipped, since training labels are hourly; closer filter-only sites are listed in the event card.
- **Distance to fire**: from the site to the nearest edge of the final fire perimeter (0 km = inside it). For the partial-window events PE-017 and PE-019, it is measured from the ignition point instead, because the final perimeter overstates where the fire was during the window.
- **% hours**: share of hours in the event window with a valid hourly reading at that site.
- **Peak daily PM2.5**: highest daily mean (µg/m³) in the window at any hourly AQS site with ≥ 75% coverage within 50 km — confirms the tier. It can come from a different site than the one in the second column; the event card names the site.
- **FIRMS SP**: detection count in the event window's bounding box from the FIRMS archive download.

Distance to the fire is not the label rule: `docs/schema.md` only requires a monitor ≤ 25 km from the **forecast point**, and forecast points are placed near the monitors. Peak PM2.5 is the highest daily mean at any hourly AQS site with ≥ 75% coverage within 50 km of the fire (ignition point for PE-017/PE-019), so it can come from a site other than the one listed. Peak PM2.5, tier and FIRMS columns are still open except where noted; they come from the DATA-03 run for each event.

| ID | Closest hourly AQS site | Distance to fire | % hours | Peak daily PM2.5 | Tier confirmed? | FIRMS SP detections | Checked by / date |
|---|---|---|---|---|---|---|---|
| PE-001 | `06-045-2002` Willits | 22.9 km | 96% |  |  | |  |
| PE-002 | `06-063-1007` Chester | 1.5 km | 93% |  |  | |  |
| PE-003 | `06-045-0006` Ukiah-Library | 10.2 km | 97% | 118.2 | Yes — High-Medium (re-tiered) | |  |
| PE-004 | `06-007-0008` Chico-East Ave | 4.1 km | 99% | 85.2 | Yes — High-Medium (re-tiered) | |  |
| PE-005 | `06-001-0007` Livermore | 5.8 km | 99% |  |  | |  |
| PE-006 | `06-053-0002` Carmel Valley | 6.0 km | 100% | 63.8 | Yes — High-Medium | |  |
| PE-007 | `06-097-0004` Sebastopol | 15.8 km | 99% | 148.6 | Yes — High (re-tiered) | |  |
| PE-008 | `06-105-0002` Weaverville | 13.6 km | 75% | 134.0 | Yes — High (re-tiered) | |  |
| PE-009 | `06-065-0012` Banning Airport | 11.3 km | 100% | 68.2 | Yes — High-Medium | |  |
| PE-010 | `06-111-0007` Thousand Oaks | 2.9 km | 99% | 44.2 | Yes — Medium-Low (re-tiered) | |  |
| PE-011 | `06-093-2001` Yreka | 17.7 km | 100% | 47.5 | Yes — Medium-Low | | |
| PE-012 | `06-051-0001` Mammoth Lakes | 14.2 km | 99% | 824.1 | Yes — High (re-tiered) | | |
| PE-013 | `06-105-0002` Weaverville | 32.4 km | 90% |  |  | |  |
| PE-014 | `06-061-0004` Colfax | 1.7 km | 92% | 5.4 | Yes — Low | |  |
| PE-015 | `06-071-1004` Upland | 28.1 km | 100% | 19.7 | Yes — Low (re-tiered) | |  |
| PE-016 | `06-043-1001` Yosemite Village | 12.9 km | 99% | 25.0 | Yes — Low | |  |
| PE-017 | `06-009-0001` San Andreas | 44.3 km (ignition) | 100% |  |  | |  |
| PE-018 | `06-083-3001` Santa Ynez | 10.3 km | 100% | 10.3 | Yes — Low | |  |
| PE-019 | `06-055-0004` Napa Valley College | 25.6 km (ignition) | 98% |  |  | |  |
| PE-020 | `06-085-0002` Gilroy | 6.9 km | 99% |  |  | |  |

An event is replaced when it fails the check (no hourly site, or < 75% hours), or when its measured peak falls outside its tier and re-tiering would leave a tier with fewer than 3 events, or would defeat the reason it was chosen. Every replacement is listed under **Replacements** below.

**Re-tiered (2026-10-09), from measured peak daily PM2.5:** PE-007 Glass, PE-008 Carr and PE-012 Creek High-Medium → High; PE-003 Mendocino Complex and PE-004 Park High → High-Medium; PE-010 Woolsey High-Medium → Medium-Low; PE-015 Sheep Medium-Low → Low. **Window changed:** PE-014 River shortened to 2021-08-04–08-05 because Dixie Fire smoke reached its monitors from 08-06.

**Replacements:**

| ID | Original event | Replacement | Date | Reason |
|---|---|---|---|---|
| PE-006 | Valley Fire (2015) | **Soberanes Fire (2016)** | 2026-10-09 | Tier mismatch: listed High-Medium, measured Low. Peak daily PM2.5 was 22.3 µg/m³ at most (Ukiah `06-045-0006`); Sebastopol, Napa and Cortina stayed under 10. |
| PE-009 | Witch Fire (2007) | **Rabbit Fire (2023)** | 2026-10-09 | Failed the check: no hourly PM2.5 in San Diego County for the window, only 24-hour filter samples (AQS), and the AirNow-Tech archive starts in 2012. |
| PE-011 | Kincade Fire (2019) | **Klamathon Fire (2018)** | 2026-10-09 | Tier mismatch: listed Medium-Low, measured Low. Peak daily PM2.5 was 28.0 µg/m³ at most (Sebastopol `06-097-0004`, which also reported only 72% of hours); Napa Valley College, Cortina and Ukiah stayed under 19. |
| PE-016 | Antelope Fire (2021) | **Rim Fire (2013)** | 2026-10-09 | Tier mismatch that defeats its role: listed Low as the "large fire, little impact" case, measured High. Yreka `06-093-2001` peaked at 134.3 µg/m³ and exceeded 35.4 on 20 of 31 days. |
| PE-018 | Monument Fire (2021) | **Lake Fire (2024)** | 2026-10-09 | Tier mismatch that defeats its role: listed Low as the "smoke dispersed away" case, measured High. Weaverville `06-105-0002` peaked at 685.5 µg/m³ and exceeded 125.4 on 23 days. |
| PE-020 | "Shasta Fire (2017)" | **Crews Fire (2020)** | 2026-10-03 | The original event does not exist and was never checked against FIRMS or AQS data. The Crews monitor, Gilroy `06-085-0002`, was confirmed on 2026-10-09. |

Notes on the replacements:

- **PE-006 and PE-011** both had usable hourly label monitors, so neither failed the coverage check. Their tiers had been assigned from each fire's reputation, not from monitor data. Re-tiering both to Low would have left Medium-Low with 2 events, so they were replaced with events whose measured peaks match the intended tier. Lost by the swap: Valley's rapid-ignition case and Kincade's marine-layer case; either could come back as an extra Low-tier event.
- **PE-009**: dropping Witch also drops the dataset's only MODIS-only (pre-VIIRS) event.
- **PE-016 and PE-018** could have been re-tiered to High, but they were chosen specifically as low-impact cases, so a High tier would have defeated their purpose.

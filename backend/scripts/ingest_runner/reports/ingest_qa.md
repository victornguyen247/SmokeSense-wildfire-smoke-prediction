# Ingest QA

20 events from `backend/docs/pilot_events.json`, checked by `backend/scripts/ingest_runner/ingest_qa.py`. Rows are selected by space and time (no table carries an event id).

## Ingest

| Event | FIRMS rows by satellite (SNPP / NOAA-20 / MODIS T+A) | FIRMS requests (retries) | AirNow rows, sites | NCEI rows, stations | null_counts | gaps | seconds |
|---|---|---|---|---|---|---|---|
| PE-001 | 280,568 (126,452 / 127,568 / 26,548) | 0 (0) | 3,935, 2 | 26,134, 10 | airnow: pm25_missing_station_hours 339; ncei: wind_speed_ms 144, wind_dir_deg 9230, temp_c 168, rh_pct 211, pressure_hpa 12156, precip_1h_mm 13183 | ncei: 93 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 249 |
| PE-002 | 370,238 (165,136 / 167,288 / 37,814) | 66 (0) | 2,409, 1 | 53,203, 11 | airnow: pm25_missing_station_hours 111; ncei: wind_speed_ms 271, wind_dir_deg 21790, temp_c 1833, rh_pct 1897, pressure_hpa 39266, precip_1h_mm 40380 | ncei: 167 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 757 |
| PE-003 | 92,141 (41,301 / 39,999 / 10,841) | 36 (0) | 1,250, 1 | 11,726, 6 | airnow: pm25_missing_station_hours 47; ncei: wind_speed_ms 109, wind_dir_deg 4431, temp_c 63, rh_pct 86, pressure_hpa 6311, precip_1h_mm 6557 | ncei: 47 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 312 |
| PE-004 | 26,950 (8,178 / 14,711 / 4,061) | 60 (0) | 5,974, 3 | 25,849, 7 | airnow: pm25_missing_station_hours 726; ncei: wind_speed_ms 133, wind_dir_deg 10283, temp_c 194, rh_pct 214, pressure_hpa 15580, precip_1h_mm 16864 | ncei: 35 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 278 |
| PE-005 | 66,469 (29,616 / 31,067 / 5,786) | 12 (0) | 2,288, 6 | 14,583, 25 | airnow: pm25_missing_station_hours 21; ncei: wind_speed_ms 112, wind_dir_deg 4843, temp_c 312, rh_pct 322, pressure_hpa 9330, precip_1h_mm 9280 | ncei: 133 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 163 |
| PE-006 | 4,130 (3,291 / 0 / 839) | 8 (0) | 663, 2 | 3,204, 5 | airnow: pm25_missing_station_hours 12; ncei: wind_speed_ms 19, wind_dir_deg 882, temp_c 37, rh_pct 37, pressure_hpa 2163, precip_1h_mm 2147 | ncei: 20 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 57 |
| PE-007 | 40,712 (18,975 / 17,577 / 4,160) | 18 (0) | 571, 1 | 10,067, 12 | airnow: pm25_missing_station_hours 5; ncei: wind_speed_ms 29, wind_dir_deg 4424, temp_c 99, rh_pct 106, pressure_hpa 5270, precip_1h_mm 5890 | ncei: 43 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 131 |
| PE-008 | 119,428 (53,972 / 52,016 / 13,440) | 21 (0) | 693, 1 | 4,626, 4 | airnow: pm25_missing_station_hours 75; ncei: wind_speed_ms 87, wind_dir_deg 2484, temp_c 69, rh_pct 78, pressure_hpa 2078, precip_1h_mm 2333 | ncei: 20 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 220 |
| PE-009 | 1,301 (695 / 498 / 108) | 9 (0) | 478, 2 | 6,247, 17 | airnow: pm25_missing_station_hours 8; ncei: wind_speed_ms 41, wind_dir_deg 2157, temp_c 790, rh_pct 1132, pressure_hpa 3455, precip_1h_mm 4664 | ncei: 13 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 49 |
| PE-010 | 6,759 (2,828 / 3,273 / 658) | 12 (0) | 1,990, 6 | 7,299, 21 | airnow: pm25_missing_station_hours 26; ncei: wind_speed_ms 17, wind_dir_deg 2703, temp_c 41, rh_pct 158, pressure_hpa 597, precip_1h_mm 1546 | ncei: 79 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 104 |
| PE-011 | 2,993 (1,428 / 1,222 / 343) | 12 (0) | 650, 2 | 1,920, 5 | airnow: pm25_missing_station_hours 23; ncei: wind_speed_ms 25, wind_dir_deg 870, temp_c 1, rh_pct 2, pressure_hpa 2, precip_1h_mm 120 | purpleair: skipped by --skip-source | 66 |
| PE-012 | 150,485 (68,769 / 68,237 / 13,479) | 69 (0) | 5,331, 2 | 16,554, 4 | airnow: pm25_missing_station_hours 45; ncei: wind_speed_ms 25, wind_dir_deg 4469, temp_c 162, rh_pct 207, pressure_hpa 7552, precip_1h_mm 8435 | ncei: 164 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 396 |
| PE-013 | 48,222 (22,322 / 20,945 / 4,955) | 15 (0) | 775, 2 | 2,464, 4 | airnow: pm25_missing_station_hours 145; ncei: wind_speed_ms 19, wind_dir_deg 1120, temp_c 11, rh_pct 12, pressure_hpa 864, precip_1h_mm 1024 | ncei: 9 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 108 |
| PE-014 | 24,409 (9,716 / 11,497 / 3,196) | 3 (0) | 93, 2 | 2,017, 14 | airnow: pm25_missing_station_hours 6; ncei: wind_speed_ms 4, wind_dir_deg 562, temp_c 2, rh_pct 5, pressure_hpa 1583, precip_1h_mm 1657 | ncei: 4 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 36 |
| PE-015 | 414 (171 / 211 / 32) | 6 (0) | 144, 2 | 3,120, 27 | ncei: wind_speed_ms 17, wind_dir_deg 654, temp_c 5, rh_pct 31, pressure_hpa 1334, precip_1h_mm 1868 | ncei: 10 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 58 |
| PE-016 | 8,345 (6,620 / 0 / 1,725) | 8 (0) | 327, 1 | 720, 2 | airnow: pm25_missing_station_hours 11; ncei: wind_speed_ms 13, wind_dir_deg 224, temp_c 14, rh_pct 16, pressure_hpa 2 | ncei: 14 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 68 |
| PE-017 | 3,075 (1,281 / 1,484 / 310) | 6 (0) | 72, 1 | 2,774, 15 | ncei: wind_speed_ms 15, wind_dir_deg 784, temp_c 3, rh_pct 4, pressure_hpa 2102, precip_1h_mm 2197 | ncei: 7 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 49 |
| PE-018 | 6,452 (2,369 / 3,169 / 914) | 12 (0) | 335, 1 | 4,574, 9 | airnow: pm25_missing_station_hours 1; ncei: wind_speed_ms 56, wind_dir_deg 1347, temp_c 24, rh_pct 26, pressure_hpa 1282, precip_1h_mm 1916 | ncei: 20 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 69 |
| PE-019 | 6,570 (3,314 / 2,632 / 624) | 3 (0) | 48, 1 | 1,910, 18 | ncei: wind_speed_ms 14, wind_dir_deg 492, temp_c 18, rh_pct 22, pressure_hpa 1090, precip_1h_mm 1255 | ncei: 13 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 24 |
| PE-020 | 1,744 (922 / 668 / 154) | 9 (0) | 427, 2 | 4,404, 14 | airnow: pm25_missing_station_hours 7; ncei: wind_speed_ms 10, wind_dir_deg 1511, temp_c 96, rh_pct 98, pressure_hpa 2724, precip_1h_mm 2724 | ncei: 95 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 45 |

## Checks

| Event | (a) AirNow sites missing / extra | (b) tier site % h DB / verif. | (b) best site % h DB / verif. | (c) Red Bluff offset | (d) pm25 -999 / <0 / <-5 | (e) FIRMS dates, lead rows, margin rows | (f) NCEI stations (bbox + 50 km), best % valid | (i) tier site lead / tail % | Flags |
|---|---|---|---|---|---|---|---|---|---|
| PE-001 | 0 / 0 | 99.4 / 99.4 (06-021-0003) | 99.4 / 99.4 (06-021-0003) | 1811/1811 at corrected hour | 0 / 0 / 0 | 2020-08-13 → 2020-11-12, 1,178, 132,472 | 10, 99.6% (KOVE) | 100.0 / 100.0 | — |
| PE-002 | 0 / 0 | 95.6 / 95.6 (06-007-0008) | 95.6 / 95.6 (06-007-0008) | n/a | 0 / 0 / 0 | 2021-07-10 → 2021-10-25, 9,455, 223,276 | 11, 100.0% (KRTS) | 100.0 / 100.0 | — |
| PE-003 | 0 / 0 | 96.5 / 96.5 (06-045-0006) | 96.5 / 96.5 (06-045-0006) | n/a | 0 / 0 / 0 | 2018-07-24 → 2018-09-18, 2,515, 54,962 | 6, 98.8% (KEDU) | 95.8 / 100.0 | — |
| PE-004 | 0 / 0 | 74.6 / 74.6 (06-007-2003) | 99.1 / 99.1 (06-007-0008) | 2099/2099 at corrected hour | 0 / 0 / 0 | 2024-07-21 → 2024-10-24, 799, 10,795 | 7, 99.3% (KRDD) | 95.8 / 95.8 | — |
| PE-005 | 0 / 0 | 99.2 / 99.2 (06-077-3005) | 99.7 / 99.7 (06-099-0005) | n/a | 0 / 0 / 0 | 2020-08-13 → 2020-08-31, 67, 45,182 | 25, 100.0% (KO22) | 100.0 / 95.8 | — |
| PE-006 | 0 / 0 | 98.8 / 98.8 (06-053-0002) | 98.8 / 98.8 (06-053-0002) | n/a | 0 / 0 / 0 | 2016-07-19 → 2016-08-04, 53, 333 | 5, 100.0% (KCVH) | 95.8 / 100.0 | — |
| PE-007 | 0 / 0 | 99.1 / 99.1 (06-097-0004) | 99.1 / 99.1 (06-097-0004) | n/a | 0 / 0 / 0 | 2020-09-24 → 2020-10-20, 2,569, 35,522 | 12, 100.0% (KSMF) | 100.0 / 100.0 | — |
| PE-008 | 0 / 0 | 93.1 / 93.1 (06-105-0002) | 93.1 / 93.1 (06-105-0002) | n/a | 0 / 0 / 0 | 2018-07-28 → 2018-08-30, 15,074, 92,244 | 4, 99.3% (KRBL) | 0.0 / 100.0 | 1 |
| PE-009 | 0 / 0 | 100.0 / 100.0 (06-065-0012) | 100.0 / 100.0 (06-065-0012) | n/a | 0 / 0 / 0 | 2023-07-11 → 2023-07-23, 555, 1,102 | 17, 100.0% (KONT) | 100.0 / 100.0 | — |
| PE-010 | 0 / 0 | 98.5 / 98.5 (06-037-1201) | 99.7 / 99.7 (06-111-3001) | n/a | 0 / 0 / 0 | 2018-11-05 → 2018-11-21, 219, 2,112 | 21, 99.4% (KEDW) | 100.0 / 100.0 | — |
| PE-011 | 0 / 0 | 99.7 / 99.7 (06-093-2001) | 99.7 / 99.7 (06-093-2001) | n/a | 0 / 0 / 0 | 2018-07-02 → 2018-07-18, 85, 1,071 | 5, 99.7% (KMFR) | 100.0 / 100.0 | — |
| PE-012 | 0 / 0 | 98.8 / 98.8 (06-043-1001) | 99.6 / 99.6 (06-019-5001) | n/a | 0 / 0 / 0 | 2020-09-01 → 2020-12-24, 4,731, 61,270 | 4, 100.0% (KFAT) | 100.0 / 100.0 | — |
| PE-013 | 0 / 0 | 87.5 / 87.5 (06-105-0002) | 87.5 / 87.5 (06-105-0002) | 375/375 at corrected hour | 0 / 0 / 0 | 2020-09-24 → 2020-10-15, 2,635, 44,754 | 4, 99.3% (KRDD) | 100.0 / 79.2 | — |
| PE-014 | 0 / 0 | 100.0 / 100.0 (06-061-0003) | 100.0 / 100.0 (06-061-0003) | n/a | 0 / 0 / 0 | 2021-08-01 → 2021-08-05, 8,413, 24,275 | 14, 100.0% (KAUN) | 95.8 / 100.0 | — |
| PE-015 | 0 / 0 | 100.0 / 100.0 (06-071-0306) | 100.0 / 100.0 (06-071-0306) | n/a | 0 / 0 / 0 | 2022-06-09 → 2022-06-14, 137, 294 | 27, 100.0% (KWJF) | 100.0 / 100.0 | — |
| PE-016 | 0 / 0 | 97.3 / 97.3 (06-079-8002) | 97.3 / 97.3 (06-079-8002) | n/a | 0 / 0 / 0 | 2016-08-10 → 2016-08-26, 416, 6,378 | 2, 97.9% (KSBP) | 100.0 / 91.7 | — |
| PE-017 | 0 / 0 | 100.0 / 100.0 (06-061-0004) | 100.0 / 100.0 (06-061-0004) | n/a | 0 / 0 / 0 | 2022-09-03 → 2022-09-08, 715, 1,794 | 15, 100.0% (KAUN) | 100.0 / 100.0 | — |
| PE-018 | 0 / 0 | 99.7 / 99.7 (06-083-3001) | 99.7 / 99.7 (06-083-3001) | n/a | 0 / 0 / 0 | 2024-07-02 → 2024-07-18, 154, 3,144 | 9, 100.0% (KSBA) | 100.0 / 100.0 | — |
| PE-019 | 0 / 0 | 100.0 / 100.0 (06-095-3003) | 100.0 / 100.0 (06-095-3003) | n/a | 0 / 0 / 0 | 2020-08-14 → 2020-08-18, 1,263, 5,892 | 18, 100.0% (KAPC) | 100.0 / 100.0 | — |
| PE-020 | 0 / 0 | 99.1 / 99.1 (06-069-0002) | 99.1 / 99.1 (06-069-0002) | n/a | 0 / 0 / 0 | 2020-07-02 → 2020-07-13, 102, 1,470 | 14, 100.0% (KMRY) | 100.0 / 95.8 | — |

**(g) PurpleAir:** 0 observation rows, 0 monitors (expected 0).
**(e) FIRMS rows outside every event's firms_bbox × window:** 0 (expected 0).

## Flags

- **PE-008** i: tier site 06-105-0002 has no AirNow values in the lead window

## (h) AirNow rows shared by events with overlapping windows

(monitor, hour) rows inside both events' tight bboxes and both windows. DATA-04 dedupes these and keeps each pair in the same fold.

| Pair | Window overlap | Shared rows | Shared sites |
|---|---|---|---|
| PE-001 × PE-005 | 2020-08-16 → 2020-08-31 | 0 | 0 |
| PE-001 × PE-007 | 2020-09-27 → 2020-10-20 | 0 | 0 |
| PE-001 × PE-012 | 2020-09-04 → 2020-11-12 | 0 | 0 |
| PE-001 × PE-013 | 2020-09-27 → 2020-10-15 | 376 | 1 |
| PE-001 × PE-019 | 2020-08-17 → 2020-08-18 | 0 | 0 |
| PE-002 × PE-014 | 2021-08-04 → 2021-08-05 | 0 | 0 |
| PE-003 × PE-008 | 2018-07-31 → 2018-08-30 | 0 | 0 |
| PE-005 × PE-019 | 2020-08-17 → 2020-08-18 | 0 | 0 |
| PE-007 × PE-012 | 2020-09-27 → 2020-10-20 | 0 | 0 |
| PE-007 × PE-013 | 2020-09-27 → 2020-10-15 | 0 | 0 |
| PE-012 × PE-013 | 2020-09-27 → 2020-10-15 | 0 | 0 |

## (j) Monitor identity

35 AirNow monitors: 35 built from a 9-digit code, 0 from a prefixed code, 0 not found in the raw AirNow cache; 0 AQS code(s) on more than one monitor.

## In-box AirNow sites outside California (AQS state code not 06)

| Event | Site | AQS id | State code |
|---|---|---|---|
| PE-009 | Morongo School | TT-582-1016 | TT |
| PE-011 | Ashland Fire Dept | 41-029-0203 | 41 |

## (c) Red Bluff (061030007) samples

- **PE-001**: 1811 of 1811 raw rows stored at label + offset, 0 only at the raw label.
  - raw label 2020-08-16T01:00:00+00:00 → stored 2020-08-16T00:00:00+00:00 (shift -1 h), pm25 4.0
  - raw label 2020-08-16T02:00:00+00:00 → stored 2020-08-16T01:00:00+00:00 (shift -1 h), pm25 3.0
- **PE-004**: 2099 of 2099 raw rows stored at label + offset, 0 only at the raw label.
  - raw label 2024-07-24T00:00:00+00:00 → stored 2024-07-24T00:00:00+00:00 (shift +0 h), pm25 13.7
  - raw label 2024-07-24T01:00:00+00:00 → stored 2024-07-24T01:00:00+00:00 (shift +0 h), pm25 11.6
- **PE-013**: 375 of 375 raw rows stored at label + offset, 0 only at the raw label.
  - raw label 2020-09-27T01:00:00+00:00 → stored 2020-09-27T00:00:00+00:00 (shift -1 h), pm25 5.0
  - raw label 2020-09-27T02:00:00+00:00 → stored 2020-09-27T01:00:00+00:00 (shift -1 h), pm25 6.0

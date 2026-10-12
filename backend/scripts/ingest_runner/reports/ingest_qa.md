# Ingest QA

20 events from `backend/docs/pilot_events.json`, checked by `backend/scripts/ingest_runner/ingest_qa.py`. Rows are selected by space and time (no table carries an event id).

## Ingest

| Event | FIRMS rows by satellite (SNPP / NOAA-20 / MODIS T+A) | FIRMS requests (retries) | AirNow rows, sites | NCEI rows, stations | null_counts | gaps | seconds |
|---|---|---|---|---|---|---|---|
| PE-001 | 280,568 (126,452 / 127,568 / 26,548) | 0 (0) | 3,935, 2 | 4,960, 2 | airnow: pm25_missing_station_hours 337; ncei: wind_speed_ms 31, wind_dir_deg 1488, temp_c 10, rh_pct 19, pressure_hpa 11, precip_1h_mm 804 | ncei: 16 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 154 |
| PE-002 | 370,238 (165,136 / 167,288 / 37,814) | 66 (0) | 2,409, 1 | 11,556, 2 | airnow: pm25_missing_station_hours 111; ncei: wind_speed_ms 44, wind_dir_deg 2894, temp_c 1751, rh_pct 1765, pressure_hpa 11556, precip_1h_mm 11502 | ncei: 54 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 631 |
| PE-003 | 92,141 (41,301 / 39,999 / 10,841) | 36 (0) | 1,250, 1 | 1,288, 1 | airnow: pm25_missing_station_hours 46; ncei: wind_speed_ms 2, wind_dir_deg 692, temp_c 21, rh_pct 23, pressure_hpa 1, precip_1h_mm 36 | ncei: 23 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 255 |
| PE-004 | 26,950 (8,178 / 14,711 / 4,061) | 60 (0) | 5,974, 3 | 6,668, 2 | airnow: pm25_missing_station_hours 722; ncei: wind_speed_ms 24, wind_dir_deg 1967, temp_c 146, rh_pct 153, pressure_hpa 3859, precip_1h_mm 4466 | ncei: 8 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 228 |
| PE-005 | 66,469 (29,616 / 31,067 / 5,786) | 12 (0) | 2,288, 6 | 4,072, 7 | airnow: pm25_missing_station_hours 16; ncei: wind_speed_ms 4, wind_dir_deg 1427, temp_c 147, rh_pct 152, pressure_hpa 2691, precip_1h_mm 2536 | ncei: 8 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 131 |
| PE-006 | 4,130 (3,291 / 0 / 839) | 8 (0) | 663, 2 | 669, 2 | airnow: pm25_missing_station_hours 9; ncei: wind_speed_ms 14, wind_dir_deg 169, temp_c 14, rh_pct 14, pressure_hpa 28, precip_1h_mm 20 | ncei: 2 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 35 |
| PE-007 | 40,712 (18,975 / 17,577 / 4,160) | 18 (0) | 571, 1 | 2,176, 2 | airnow: pm25_missing_station_hours 5; ncei: wind_speed_ms 4, wind_dir_deg 1231, temp_c 34, rh_pct 34, pressure_hpa 1600, precip_1h_mm 1600 | ncei: 12 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 83 |
| PE-008 | 119,428 (53,972 / 52,016 / 13,440) | 21 (0) | 693, 1 | 2,899, 2 | airnow: pm25_missing_station_hours 51; ncei: wind_speed_ms 27, wind_dir_deg 1529, temp_c 30, rh_pct 38, pressure_hpa 2034, precip_1h_mm 2155 | ncei: 14 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 209 |
| PE-009 | 1,301 (695 / 498 / 108) | 9 (0) | 478, 2 | 1,338, 3 | airnow: pm25_missing_station_hours 2; ncei: wind_speed_ms 5, wind_dir_deg 552, temp_c 713, rh_pct 713, pressure_hpa 1100, precip_1h_mm 1338 | purpleair: skipped by --skip-source | 28 |
| PE-010 | 6,759 (2,828 / 3,273 / 658) | 12 (0) | 1,990, 6 | 2,245, 7 | airnow: pm25_missing_station_hours 26; ncei: wind_speed_ms 4, wind_dir_deg 624, temp_c 10, rh_pct 47, pressure_hpa 173, precip_1h_mm 229 | ncei: 25 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 55 |
| PE-011 | 2,993 (1,428 / 1,222 / 343) | 12 (0) | 650, 2 | 336, 1 | airnow: pm25_missing_station_hours 22; ncei: wind_speed_ms 5, wind_dir_deg 109 | purpleair: skipped by --skip-source | 41 |
| PE-012 | 150,485 (68,769 / 68,237 / 13,479) | 69 (0) | 5,331, 2 | 7,460, 1 | airnow: pm25_missing_station_hours 45; ncei: wind_speed_ms 12, wind_dir_deg 2064, temp_c 129, rh_pct 171, pressure_hpa 7460, precip_1h_mm 7437 | ncei: 135 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 340 |
| PE-013 | 48,222 (22,322 / 20,945 / 4,955) | 15 (0) | 775, 2 | 1,064, 2 | airnow: pm25_missing_station_hours 137; ncei: wind_speed_ms 5, wind_dir_deg 321, temp_c 2, rh_pct 3, precip_1h_mm 152 | ncei: 3 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 79 |
| PE-014 | 24,409 (9,716 / 11,497 / 3,196) | 3 (0) | 93, 2 | 333, 3 | airnow: pm25_missing_station_hours 3; ncei: wind_dir_deg 137, temp_c 2, rh_pct 3, pressure_hpa 285, precip_1h_mm 285 | ncei: 3 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 25 |
| PE-015 | 414 (171 / 211 / 32) | 6 (0) | 144, 2 | 89, 1 | ncei: wind_dir_deg 18, pressure_hpa 89, precip_1h_mm 89 | purpleair: skipped by --skip-source | 12 |
| PE-016 | 8,345 (6,620 / 0 / 1,725) | 8 (0) | 327, 1 | 336, 1 | airnow: pm25_missing_station_hours 9; ncei: wind_speed_ms 7, wind_dir_deg 138, temp_c 12, rh_pct 14 | ncei: 13 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 47 |
| PE-017 | 3,075 (1,281 / 1,484 / 310) | 6 (0) | 72, 1 | 288, 2 | ncei: wind_speed_ms 1, wind_dir_deg 155, pressure_hpa 216, precip_1h_mm 216 | purpleair: skipped by --skip-source | 16 |
| PE-018 | 6,452 (2,369 / 3,169 / 914) | 12 (0) | 335, 1 | 1,004, 1 | airnow: pm25_missing_station_hours 1; ncei: wind_speed_ms 2, wind_dir_deg 418, temp_c 21, rh_pct 23, pressure_hpa 1004, precip_1h_mm 1004 | ncei: 17 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 36 |
| PE-019 | 6,570 (3,314 / 2,632 / 624) | 3 (0) | 48, 1 | 433, 5 | ncei: wind_speed_ms 4, wind_dir_deg 137, temp_c 9, rh_pct 9, pressure_hpa 290, precip_1h_mm 335 | ncei: 4 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 12 |
| PE-020 | 1,744 (922 / 668 / 154) | 9 (0) | 427, 2 | 1,350, 3 | airnow: pm25_missing_station_hours 5; ncei: wind_dir_deg 672, temp_c 10, rh_pct 12, pressure_hpa 1134, precip_1h_mm 1134 | ncei: 12 rows had a value dropped by NCEI quality control; purpleair: skipped by --skip-source | 28 |

## Checks

| Event | (a) AirNow sites missing / extra | (b) tier site % h DB / verif. | (b) best site % h DB / verif. | (c) Red Bluff offset | (d) pm25 -999 / <0 / <-5 | (e) FIRMS dates, lead rows, margin rows | (f) NCEI stations, best % valid | Flags |
|---|---|---|---|---|---|---|---|---|
| PE-001 | 0 / 0 | 99.4 / 99.4 (06-021-0003) | 99.4 / 99.4 (06-021-0003) | 1811/1811 at corrected hour | 0 / 0 / 0 | 2020-08-13 → 2020-11-12, 1,178, 132,472 | 2, 99.1% (KRBL) | — |
| PE-002 | 0 / 0 | 95.6 / 95.6 (06-007-0008) | 95.6 / 95.6 (06-007-0008) | n/a | 0 / 0 / 0 | 2021-07-10 → 2021-10-25, 9,455, 223,276 | 2, 91.0% (KCIC) | — |
| PE-003 | 0 / 0 | 96.5 / 96.5 (06-045-0006) | 96.5 / 96.5 (06-045-0006) | n/a | 0 / 0 / 0 | 2018-07-24 → 2018-09-18, 2,515, 54,962 | 1, 97.5% (KUKI) | — |
| PE-004 | 0 / 0 | 74.6 / 74.6 (06-007-2003) | 99.1 / 99.1 (06-007-0008) | 2099/2099 at corrected hour | 0 / 0 / 0 | 2024-07-21 → 2024-10-24, 799, 10,795 | 2, 94.6% (KRBL) | — |
| PE-005 | 0 / 0 | 99.2 / 99.2 (06-077-3005) | 99.7 / 99.7 (06-099-0005) | n/a | 0 / 0 / 0 | 2020-08-13 → 2020-08-31, 67, 45,182 | 7, 100.0% (KMOD) | — |
| PE-006 | 0 / 0 | 98.8 / 98.8 (06-053-0002) | 98.8 / 98.8 (06-053-0002) | n/a | 0 / 0 / 0 | 2016-07-19 → 2016-08-04, 53, 333 | 2, 99.4% (KSNS) | — |
| PE-007 | 0 / 0 | 99.1 / 99.1 (06-097-0004) | 99.1 / 99.1 (06-097-0004) | n/a | 0 / 0 / 0 | 2020-09-24 → 2020-10-20, 2,569, 35,522 | 2, 97.2% (KSTS) | — |
| PE-008 | 0 / 0 | 93.1 / 93.1 (06-105-0002) | 93.1 / 93.1 (06-105-0002) | n/a | 0 / 0 / 0 | 2018-07-28 → 2018-08-30, 15,074, 92,244 | 2, 99.2% (KRDD) | — |
| PE-009 | 0 / 0 | 100.0 / 100.0 (06-065-0012) | 100.0 / 100.0 (06-065-0012) | n/a | 0 / 0 / 0 | 2023-07-11 → 2023-07-23, 555, 1,102 | 3, 99.6% (KRIV) | — |
| PE-010 | 0 / 0 | 98.5 / 98.5 (06-037-1201) | 99.7 / 99.7 (06-111-3001) | n/a | 0 / 0 / 0 | 2018-11-05 → 2018-11-21, 219, 2,112 | 7, 98.8% (KVNY) | — |
| PE-011 | 0 / 0 | 99.7 / 99.7 (06-093-2001) | 99.7 / 99.7 (06-093-2001) | n/a | 0 / 0 / 0 | 2018-07-02 → 2018-07-18, 85, 1,071 | 1, 98.5% (KSIY) | — |
| PE-012 | 0 / 0 | 98.8 / 98.8 (06-043-1001) | 99.6 / 99.6 (06-019-5001) | n/a | 0 / 0 / 0 | 2020-09-01 → 2020-12-24, 4,731, 61,270 | 1, 92.8% (KMMH) | — |
| PE-013 | 0 / 0 | 87.5 / 87.5 (06-105-0002) | 87.5 / 87.5 (06-105-0002) | 375/375 at corrected hour | 0 / 0 / 0 | 2020-09-24 → 2020-10-15, 2,635, 44,754 | 2, 99.3% (KRDD) | — |
| PE-014 | 0 / 0 | 100.0 / 100.0 (06-061-0003) | 100.0 / 100.0 (06-061-0003) | n/a | 0 / 0 / 0 | 2021-08-01 → 2021-08-05, 8,413, 24,275 | 3, 100.0% (KAUN) | — |
| PE-015 | 0 / 0 | 100.0 / 100.0 (06-071-0306) | 100.0 / 100.0 (06-071-0306) | n/a | 0 / 0 / 0 | 2022-06-09 → 2022-06-14, 137, 294 | 1, 41.7% (KVCV) | 1 |
| PE-016 | 0 / 0 | 97.3 / 97.3 (06-079-8002) | 97.3 / 97.3 (06-079-8002) | n/a | 0 / 0 / 0 | 2016-08-10 → 2016-08-26, 416, 6,378 | 1, 94.0% (KPRB) | — |
| PE-017 | 0 / 0 | 100.0 / 100.0 (06-061-0004) | 100.0 / 100.0 (06-061-0004) | n/a | 0 / 0 / 0 | 2022-09-03 → 2022-09-08, 715, 1,794 | 2, 100.0% (KGOO) | — |
| PE-018 | 0 / 0 | 99.7 / 99.7 (06-083-3001) | 99.7 / 99.7 (06-083-3001) | n/a | 0 / 0 / 0 | 2024-07-02 → 2024-07-18, 154, 3,144 | 1, 99.4% (KIZA) | — |
| PE-019 | 0 / 0 | 100.0 / 100.0 (06-095-3003) | 100.0 / 100.0 (06-095-3003) | n/a | 0 / 0 / 0 | 2020-08-14 → 2020-08-18, 1,263, 5,892 | 5, 100.0% (KAPC) | — |
| PE-020 | 0 / 0 | 99.1 / 99.1 (06-069-0002) | 99.1 / 99.1 (06-069-0002) | n/a | 0 / 0 / 0 | 2020-07-02 → 2020-07-13, 102, 1,470 | 3, 100.0% (KWVI) | — |

**(g) PurpleAir:** 0 observation rows, 0 monitors (expected 0).
**(e) FIRMS rows outside every event's firms_bbox × window:** 0 (expected 0).

## Flags

- **PE-015** f: best NCEI station KVCV has 41.7% valid hours (< 50%)

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

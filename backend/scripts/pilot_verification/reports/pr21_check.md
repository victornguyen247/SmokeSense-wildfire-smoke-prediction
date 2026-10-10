# PR #21 event set vs AirNow tight-box rules

Generated 2026-10-10 by `report_pr21.py` from a `PILOT_EVENTS=pr21` run of `run_all.py` (live FIRMS `_SP` and AirNow `/aq/data/`). AirNow values are preliminary, not AQS.

| Event | PR #21 tier; peak (closest AQS site) | Nearest in-box AirNow site, distance to fire detections, % hours | ≤ 40 km? | AirNow peak daily PM2.5 (tier, item3 TIER_RANGES) | Baseline → elevation (item6) | Other-fire FRP share | PR #21 closest AQS site in AirNow, tight box? | Dark peak day (item2) |
|---|---|---|---|---|---|---|---|---|
| PE-001 August Complex Fire | High; 433.9 (Willits 06-045-2002) | None in box (nearest outside: 06-021-0003 Willows-Colusa, 18.9 km) | No | No AirNow data | — | 2.1% | No | n/a (no site < 90%) |
| PE-002 Dixie Fire | High; 568.1 (Chester 06-063-1007) | 06-007-0008 Chico - East, 34.6 km, 95.6% | Yes | best Chico - East 102.8 (High-Medium) | best 7.8 → +95.0 (×13.18) | 0.0% in box; 41.3% outside box within 200 km (median) | No | n/a (no site < 90%) |
| PE-003 Mendocino Complex Fire | High-Medium; 118.2 (Ukiah-Library 06-045-0006) | 06-045-0006 Ukiah Library, 9.4 km, 96.5% | Yes | best Ukiah Library 59.5 (High-Medium) | best 5.5 → +54.0 (×10.82) | 0.0% in box; 30.0% outside box within 200 km (median) | Yes (96.5%) | n/a (no site < 90%) |
| PE-004 Park Fire | High-Medium; 85.2 (Chico-East Ave 06-007-0008) | 06-007-0008 Chico - East, 4.1 km, 99.1% | Yes | best Chico - East 85.2 (High-Medium); max Paradise - Clark Road 138.1 (High) | best 10.6 → +74.6 (×8.04); max 8.2 → +129.9 (×16.84) | 0.0% in box; 9.6% outside box within 200 km (median) | Yes (99.1%) | Yes — Paradise - Clark Road: 2024-10-15 |
| PE-005 SCU Lightning Complex Fire | High-Medium; 117.5 (Livermore 06-001-0007) | 06-085-0006 San Jose - Knox Ave, 5.8 km, 99.2% | Yes | best Modesto - 14th Street 102.2 (High-Medium); max TracyAP 117.5 (High-Medium) | best 6.4 → +95.8 (×15.97); max 6.6 → +110.9 (×17.80) | 0.1% in box; 60.5% outside box within 200 km (median) | No | n/a (no site < 90%) |
| PE-006 Soberanes Fire (first two weeks) | High-Medium; 63.8 (Carmel Valley 06-053-0002) | 06-053-0002 Carmel Valley AMS, 5.9 km, 98.8% | Yes | best Carmel Valley AMS 63.8 (High-Medium) | best 2.0 → +61.8 (×31.90) | 0.0% in box; 1.3% outside box within 200 km (median) | Yes (98.8%) | n/a (no site < 90%) |
| PE-007 Glass Fire | High; 148.6 (Sebastopol 06-097-0004) | 06-097-0004 Sebastopol, 15.5 km, 99.1% | Yes | best Sebastopol 58.9 (High-Medium) | best 2.9 → +56.0 (×20.31) | 0.0% in box; 62.2% outside box within 200 km (median) | Yes (99.1%) | n/a (no site < 90%) |
| PE-008 Carr Fire | High; 134.0 (Weaverville 06-105-0002) | 06-105-0002 Weaverville, 11.9 km, 74.0% | Yes | best Weaverville 134.0 (High) | best: no baseline (0 of 7 days with ≥ 18 h) | 0.0% in box; 69.4% outside box within 200 km (median) | Yes (74.0%) | Yes — Weaverville: 2018-07-26, 2018-07-28, 2018-07-29, 2018-07-30 |
| PE-009 Rabbit Fire | High-Medium; 68.2 (Banning Airport 06-065-0012) | 06-065-0012 Banning - South Hathaway Street, 11.7 km, 100.0% | Yes | best Banning - South Hathaway Street 68.2 (High-Medium) | best 10.2 → +58.0 (×6.69) | 18.3% in box; 50.5% outside box within 200 km (median) | Yes (100.0%) | n/a (no site < 90%) |
| PE-010 Woolsey Fire | Medium-Low; 44.2 (Thousand Oaks 06-111-0007) | 06-111-0007 Thousand Oaks - Moorpark Road, 2.2 km, 99.4% | Yes | best El Rio - Rio Mesa School #2 41.2 (Medium-Low); max Reseda 42.1 (Medium-Low) | best 9.5 → +31.7 (×4.34); max 14.1 → +28.0 (×2.99) | 0.0% in box; 3.0% outside box within 200 km (median) | Yes (99.4%) | n/a (no site < 90%) |
| PE-011 Klamathon Fire | Medium-Low; 47.5 (Yreka 06-093-2001) | 06-093-2001 Yreka, 17.4 km, 99.7% | Yes | best Yreka 47.5 (Medium-Low) | best 3.5 → +44.0 (×13.57) | 3.1% in box; 14.9% outside box within 200 km (median) | Yes (99.7%) | n/a (no site < 90%) |
| PE-012 Creek Fire | High; 824.1 (Mammoth Lakes 06-051-0001) | 06-043-1001 Yosemite Village - Visitor Center, 28.1 km, 98.8% | Yes | best Clovis - N. Villa Ave 193.8 (High); max Yosemite Village - Visitor Center 613.2 (High) | best 31.9 → +161.9 (×6.08); max 23.7 → +589.5 (×25.87) | 1.5% in box; 30.0% outside box within 200 km (median) | No | n/a (no site < 90%) |
| PE-013 Zogg Fire | Medium-Low; 125.8 (Weaverville 06-105-0002) | 06-105-0002 Weaverville, 31.7 km, 87.5% | Yes | best Weaverville 125.8 (High) | best 18.5 → +107.3 (×6.80) | 0.6% in box; 90.1% outside box within 200 km (median) | Yes (87.5%) | No |
| PE-014 River Fire | Low; 10.9 (Colfax 06-061-0004) | 06-061-0004 Colfax, 1.5 km, 93.8% | Yes | best Auburn 6.9 (Low) | best 7.8 → -0.9 (×0.88) | 0.0% in box; 100.0% outside box within 200 km (median) | Yes (93.8%) | n/a (no site < 90%) |
| PE-015 Sheep Fire | Low; 19.7 (Upland 06-071-1004) | 06-071-0306 Victorville - Park Avenue, 29.1 km, 100.0% | Yes | best Victorville - Park Avenue 12.4 (Low) | best 9.0 → +3.4 (×1.38) | 0.0% in box; 3.4% outside box within 200 km (median) | No | n/a (no site < 90%) |
| PE-016 Rim Fire (first two weeks) | Low; 25.0 (Yosemite Village 06-043-1001) | None in box (nearest outside: 06-009-0001 San Andreas, 49.7 km) | No | No AirNow data | — | 0.0% | No | n/a (no site < 90%) |
| PE-017 Caldor Fire (early phase) | Low; 30.0 (San Andreas 06-009-0001) | None in box (nearest outside: 06-009-0001 San Andreas, 40.8 km) | No | No AirNow data | — | 0.0% | No | n/a (no site < 90%) |
| PE-018 Lake Fire (2024, first two weeks) | Low; 10.3 (Santa Ynez 06-083-3001) | 06-083-3001 Santa Ynez, 9.9 km, 99.7% | Yes | best Santa Ynez 9.7 (Low) | best 5.1 → +4.6 (×1.90) | 0.0% in box; 10.6% outside box within 200 km (median) | Yes (99.7%) | n/a (no site < 90%) |
| PE-019 LNU Lightning Complex (perimeter section only) | Low; 35.3 (Napa Valley College 06-055-0004) | 06-095-3003 Vacaville, 28.6 km, 100.0% | Yes | best Vacaville 52.9 (Medium-Low) | best 4.3 → +48.6 (×12.30) | 0.1% in box; 76.3% outside box within 200 km (median) | No | n/a (no site < 90%) |
| PE-020 Crews Fire | Low; 23.7 (Gilroy 06-085-0002) | 06-085-0002 Gilroy - 9th Street, 6.7 km, 98.6% | Yes | best Hollister AMS 13.3 (Low) | best 9.1 → +4.2 (×1.46) | 19.2% in box; 60.6% outside box within 200 km (median) | Yes (98.6%) | n/a (no site < 90%) |

Column notes:
- **Nearest in-box AirNow site**: AirNow sites reporting PM2.5 inside the tight bbox during the window; distance is to the nearest FIRMS detection of the event's own cluster; % is of the window's UTC hours.
- **≤ 40 km?**: that nearest site is within 40 km of the fire detections.
- **AirNow peak**: highest daily mean over local-standard-time days with ≥ 18 h. *best* is the site with the most hours, *max* the highest peak in the box (shown when different).
- **Baseline → elevation**: baseline is the median daily mean over the 7 LST days before the start (days with ≥ 18 h), from AirNow on the tight box; elevation is peak − baseline (× peak / baseline).
- **Other-fire FRP share**: share of in-box FIRMS FRP from clusters other than the event's (stage2); then item5's median share of FRP within 200 km of the in-box sites that lies outside the box.
- **Dark peak day**: item2, for sites with < 90% hours: top-quartile days of the window with no hours at all.

## Bboxes

| Event | Window | Bbox (W, S, E, N) | Size (km) |
|---|---|---|---|
| PE-001 | 2020-08-16 → 2020-11-12 | -123.71, 39.26, -122.28, 40.59 | 122 × 148 |
| PE-002 | 2021-07-13 → 2021-10-25 | -122.04, 39.59, -120.00, 40.81 | 173 × 136 |
| PE-003 | 2018-07-27 → 2018-09-18 | -123.37, 38.79, -122.21, 39.75 | 100 × 107 |
| PE-004 | 2024-07-24 → 2024-10-24 | -122.29, 39.59, -121.19, 40.59 | 94 × 111 |
| PE-005 | 2020-08-16 → 2020-08-31 | -122.03, 36.90, -120.92, 37.78 | 98 × 98 |
| PE-006 | 2016-07-22 → 2016-08-04 | -122.19, 36.09, -121.42, 36.70 | 69 × 68 |
| PE-007 | 2020-09-27 → 2020-10-20 | -122.93, 38.21, -122.14, 38.88 | 69 × 75 |
| PE-008 | 2018-07-23 → 2018-08-30 | -123.19, 40.21, -121.96, 41.23 | 104 × 114 |
| PE-009 | 2023-07-14 → 2023-07-23 | -117.31, 33.64, -116.70, 34.15 | 56 × 57 |
| PE-010 | 2018-11-08 → 2018-11-21 | -119.23, 33.78, -118.37, 34.45 | 79 × 75 |
| PE-011 | 2018-07-05 → 2018-07-18 | -122.92, 41.66, -122.15, 42.28 | 64 × 69 |
| PE-012 | 2020-09-04 → 2020-12-24 | -119.80, 36.80, -118.74, 37.85 | 94 × 117 |
| PE-013 | 2020-09-27 → 2020-10-15 | -123.00, 40.08, -122.24, 40.89 | 64 × 90 |
| PE-014 | 2021-08-04 → 2021-08-05 | -121.29, 38.85, -120.68, 39.37 | 53 × 58 |
| PE-015 | 2022-06-12 → 2022-06-14 | -117.90, 34.13, -117.32, 34.60 | 53 × 52 |
| PE-016 | 2013-08-17 → 2013-08-30 | -120.43, 37.54, -119.42, 38.25 | 89 × 79 |
| PE-017 | 2021-08-14 → 2021-08-16 | -120.84, 38.34, -120.19, 38.82 | 57 × 53 |
| PE-018 | 2024-07-05 → 2024-07-18 | -120.41, 34.47, -119.63, 35.05 | 71 × 65 |
| PE-019 | 2020-08-17 → 2020-08-18 | -122.66, 38.15, -121.93, 38.94 | 64 × 88 |
| PE-020 | 2020-07-05 → 2020-07-13 | -121.79, 36.77, -121.11, 37.26 | 60 × 55 |

## Anchors

The anchor only picks which FIRMS cluster in the county union is the event; the bbox is then built around that cluster.

| Event | Anchor (lat, lon) | Source |
|---|---|---|
| PE-001 August Complex Fire | 39.85, -122.85 | Same fire as events.py (PR #26); its anchor kept |
| PE-002 Dixie Fire | 40.15, -121.1 | Same fire as events.py (PR #26); its anchor kept |
| PE-003 Mendocino Complex Fire | 39.3, -122.8 | Same fire as events.py (PR #26); its anchor kept |
| PE-004 Park Fire | 40.0, -121.75 | Same fire as events.py (PR #26); its anchor kept |
| PE-005 SCU Lightning Complex Fire | 37.4, -121.45 | Same fire as events.py (PR #26); its anchor kept |
| PE-006 Soberanes Fire (first two weeks) | 36.392, -121.806 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |
| PE-007 Glass Fire | 38.56, -122.5 | Same fire as events.py (PR #26); its anchor kept |
| PE-008 Carr Fire | 40.65, -122.62 | Same fire as events.py (PR #26); its anchor kept |
| PE-009 Rabbit Fire | 33.898, -117.006 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |
| PE-010 Woolsey Fire | 34.1, -118.8 | Same fire as events.py (PR #26); its anchor kept |
| PE-011 Klamathon Fire | 41.968, -122.535 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |
| PE-012 Creek Fire | 37.25, -119.3 | Same fire as events.py (PR #26); its anchor kept |
| PE-013 Zogg Fire | 40.54, -122.56 | Same fire as events.py (PR #26); its anchor kept |
| PE-014 River Fire | 39.05, -120.95 | Same fire as events.py (PR #26); its anchor kept |
| PE-015 Sheep Fire | 34.36, -117.66 | Same fire as events.py (PR #26); its anchor kept |
| PE-016 Rim Fire (first two weeks) | 37.894, -119.922 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |
| PE-017 Caldor Fire (early phase) | 38.5845, -120.536 | Ignition point stated in the PR #21 doc (NIFC WFIGS) |
| PE-018 Lake Fire (2024, first two weeks) | 34.758, -120.019 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |
| PE-019 LNU Lightning Complex (perimeter section only) | 38.5039, -122.3373 | Ignition point stated in the PR #21 doc (NIFC WFIGS); Hennessey. The Walbridge ignition (38.5975, −122.9979) is a separate cluster, not used |
| PE-020 Crews Fire | 37.011, -121.449 | New fire: centroid of the highest-FRP cluster in the county union (top 3 below) |

Top 3 FIRMS clusters (FRP-weighted centroid) for the new fires, county union over the window:

- **PE-006 Soberanes Fire (first two weeks)** (union -122.05, 35.79, -120.21, 36.91; 3,801 detections):
  - 36.392, -121.806: 3,796 detections, FRP 162,080 MW, 2016-07-22 → 2016-08-04
  - 36.811, -120.384: 2 detections, FRP 2 MW, 2016-07-22 → 2016-07-22
  - 36.591, -121.553: 1 detections, FRP 2 MW, 2016-08-04 → 2016-08-04
- **PE-009 Rabbit Fire** (union -117.68, 33.43, -114.44, 34.08; 208 detections):
  - 33.898, -117.006: 161 detections, FRP 5,426 MW, 2023-07-14 → 2023-07-18
  - 33.975, -117.218: 20 detections, FRP 1,122 MW, 2023-07-14 → 2023-07-14
  - 33.459, -117.437: 3 detections, FRP 44 MW, 2023-07-14 → 2023-07-22
- **PE-011 Klamathon Fire** (union -123.72, 40.99, -121.45, 42.01; 1,691 detections):
  - 41.968, -122.535: 1,566 detections, FRP 50,105 MW, 2018-07-05 → 2018-07-10
  - 41.95, -123.548: 122 detections, FRP 1,064 MW, 2018-07-15 → 2018-07-18
  - 41.931, -121.829: 2 detections, FRP 15 MW, 2018-07-16 → 2018-07-16
- **PE-016 Rim Fire (first two weeks)** (union -120.65, 37.63, -119.20, 38.43; 13,781 detections):
  - 37.894, -119.922: 13,774 detections, FRP 871,944 MW, 2013-08-17 → 2013-08-30
  - 38.062, -120.461: 5 detections, FRP 127 MW, 2013-08-17 → 2013-08-17
  - 38.21, -120.534: 1 detections, FRP 1 MW, 2013-08-28 → 2013-08-28
- **PE-018 Lake Fire (2024, first two weeks)** (union -120.73, 33.41, -118.96, 35.12; 3,319 detections):
  - 34.758, -120.019: 3,308 detections, FRP 151,660 MW, 2024-07-06 → 2024-07-13
  - 34.93, -120.476: 6 detections, FRP 61 MW, 2024-07-16 → 2024-07-17
  - 34.401, -118.999: 3 detections, FRP 1 MW, 2024-07-05 → 2024-07-17
- **PE-020 Crews Fire** (union -122.20, 36.89, -121.21, 37.48; 293 detections):
  - 37.011, -121.449: 226 detections, FRP 1,664 MW, 2020-07-05 → 2020-07-06
  - 37.157, -121.577: 32 detections, FRP 312 MW, 2020-07-05 → 2020-07-05
  - 36.928, -121.714: 4 detections, FRP 61 MW, 2020-07-09 → 2020-07-09

## Overrides

PR #26's per-event overrides in `stage1.py` are keyed by event id. For this set: LNU's link rule (PE-019) is kept, since it is the same fire; the River Complex exclusion is dropped, because PE-018 is now the Lake Fire; and PE-001's hand-widened bbox is not applied, so every event is checked on its computed tight box. FIRMS products are the `_SP` archive only: NOAA-21 (NRT) is not counted for PE-004 or PE-018.

"""Final pilot event set (2026-10-10), checked under the final rules.

Starts from events_pr21.py (PR #21's set) with these changes:
  - tier is None for every event: tiers are computed (rules_final.py), not copied;
  - PE-008 Carr starts 2018-07-31 (was 2018-07-23);
  - PE-016 and PE-017 are the replacements picked by screening events_candidates.py.
No bbox is overridden by hand: under the final rules stage2 widens a bbox to its
nearest AirNow site within 40 km of the fire instead (recorded as bbox_adjust).
"""
from events_pr21 import DOC_CHECK, LINK_OVERRIDE, products_for  # noqa: F401

EVENTS = [
    # id, name, tier, start, end, counties, anchor(lat,lon)
    ("PE-001", "August Complex Fire", None, "2020-08-16", "2020-11-12",
     ["Trinity", "Tehama", "Glenn", "Lake", "Mendocino"], (39.85, -122.85)),
    ("PE-002", "Dixie Fire", None, "2021-07-13", "2021-10-25",
     ["Plumas", "Butte", "Lassen", "Shasta", "Tehama"], (40.15, -121.10)),
    ("PE-003", "Mendocino Complex Fire", None, "2018-07-27", "2018-09-18",
     ["Mendocino", "Lake", "Colusa", "Glenn"], (39.30, -122.80)),
    ("PE-004", "Park Fire", None, "2024-07-24", "2024-10-24",
     ["Butte", "Tehama"], (40.00, -121.75)),
    ("PE-005", "SCU Lightning Complex Fire", None, "2020-08-16", "2020-08-31",
     ["Santa Clara", "Alameda", "Contra Costa", "San Joaquin", "Stanislaus"], (37.40, -121.45)),
    ("PE-006", "Soberanes Fire (first two weeks)", None, "2016-07-22", "2016-08-04",
     ["Monterey"], (36.392, -121.806)),
    ("PE-007", "Glass Fire", None, "2020-09-27", "2020-10-20",
     ["Napa", "Sonoma"], (38.56, -122.50)),
    ("PE-008", "Carr Fire", None, "2018-07-31", "2018-08-30",
     ["Shasta", "Trinity"], (40.65, -122.62)),
    ("PE-009", "Rabbit Fire", None, "2023-07-14", "2023-07-23",
     ["Riverside"], (33.898, -117.006)),
    ("PE-010", "Woolsey Fire", None, "2018-11-08", "2018-11-21",
     ["Los Angeles", "Ventura"], (34.10, -118.80)),
    ("PE-011", "Klamathon Fire", None, "2018-07-05", "2018-07-18",
     ["Siskiyou"], (41.968, -122.535)),
    ("PE-012", "Creek Fire", None, "2020-09-04", "2020-12-24",
     ["Fresno", "Madera"], (37.25, -119.30)),
    ("PE-013", "Zogg Fire", None, "2020-09-27", "2020-10-15",
     ["Shasta", "Trinity"], (40.54, -122.56)),
    ("PE-014", "River Fire", None, "2021-08-04", "2021-08-05",
     ["Nevada", "Placer"], (39.05, -120.95)),
    ("PE-015", "Sheep Fire", None, "2022-06-12", "2022-06-14",
     ["San Bernardino"], (34.36, -117.66)),
    # Replacement picked by screen_candidates.py (was Rim Fire 2013):
    # https://www.fire.ca.gov/incidents/2016/8/13/chimney-fire
    ("PE-016", "Chimney Fire (first two weeks)", None, "2016-08-13", "2016-08-26",
     ["San Luis Obispo"], (35.70595, -120.98316)),
    # Replacement picked by screen_candidates.py (was Caldor Fire early phase):
    # https://www.fire.ca.gov/incidents/2022/9/6/mosquito-fire/
    ("PE-017", "Mosquito Fire (first three days)", None, "2022-09-06", "2022-09-08",
     ["Placer", "El Dorado"], (39.00591, -120.7447)),
    ("PE-018", "Lake Fire (2024, first two weeks)", None, "2024-07-05", "2024-07-18",
     ["Santa Barbara"], (34.758, -120.019)),
    ("PE-019", "LNU Lightning Complex (perimeter section only)", None, "2020-08-17", "2020-08-18",
     ["Lake", "Napa", "Sonoma", "Yolo", "Colusa"], (38.5039, -122.3373)),
    ("PE-020", "Crews Fire", None, "2020-07-05", "2020-07-13",
     ["Santa Clara"], (37.011, -121.449)),
]


EXCLUDE = {}
BBOX_OVERRIDE = {}

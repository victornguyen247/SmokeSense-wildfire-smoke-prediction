"""Pilot events as they stand in docs/pilot-events.md on PR #21 (fix/pilot-list, 2026-10-09).

Same format as events.py, which stays as the PR #26 set. Counties come from
each card's Region field; windows are PR #21's (several changed).

anchor = (lat, lon) used ONLY to pick which FIRMS cluster is this event when the
county union holds several fires:
  - fires also in events.py keep its anchor;
  - PE-017 and PE-019 use the ignition points the PR #21 doc states (NIFC WFIGS);
  - new fires use the centroid of the highest-FRP FIRMS cluster in the county
    union during the window (see reports/pr21_check.md for the top 3 clusters).
"""
EVENTS = [
    # id, name, tier, start, end, counties, anchor(lat,lon)
    ("PE-001", "August Complex Fire", "high", "2020-08-16", "2020-11-12",
     ["Trinity", "Tehama", "Glenn", "Lake", "Mendocino"], (39.85, -122.85)),
    ("PE-002", "Dixie Fire", "high", "2021-07-13", "2021-10-25",
     ["Plumas", "Butte", "Lassen", "Shasta", "Tehama"], (40.15, -121.10)),
    ("PE-003", "Mendocino Complex Fire", "high-medium", "2018-07-27", "2018-09-18",
     ["Mendocino", "Lake", "Colusa", "Glenn"], (39.30, -122.80)),
    ("PE-004", "Park Fire", "high-medium", "2024-07-24", "2024-10-24",
     ["Butte", "Tehama"], (40.00, -121.75)),
    ("PE-005", "SCU Lightning Complex Fire", "high-medium", "2020-08-16", "2020-08-31",
     ["Santa Clara", "Alameda", "Contra Costa", "San Joaquin", "Stanislaus"], (37.40, -121.45)),
    ("PE-006", "Soberanes Fire (first two weeks)", "high-medium", "2016-07-22", "2016-08-04",
     ["Monterey"], (36.392, -121.806)),
    ("PE-007", "Glass Fire", "high", "2020-09-27", "2020-10-20",
     ["Napa", "Sonoma"], (38.56, -122.50)),
    ("PE-008", "Carr Fire", "high", "2018-07-23", "2018-08-30",
     ["Shasta", "Trinity"], (40.65, -122.62)),
    ("PE-009", "Rabbit Fire", "high-medium", "2023-07-14", "2023-07-23",
     ["Riverside"], (33.898, -117.006)),
    ("PE-010", "Woolsey Fire", "medium-low", "2018-11-08", "2018-11-21",
     ["Los Angeles", "Ventura"], (34.10, -118.80)),
    ("PE-011", "Klamathon Fire", "medium-low", "2018-07-05", "2018-07-18",
     ["Siskiyou"], (41.968, -122.535)),
    ("PE-012", "Creek Fire", "high", "2020-09-04", "2020-12-24",
     ["Fresno", "Madera"], (37.25, -119.30)),
    ("PE-013", "Zogg Fire", "medium-low", "2020-09-27", "2020-10-15",
     ["Shasta", "Trinity"], (40.54, -122.56)),
    ("PE-014", "River Fire", "low", "2021-08-04", "2021-08-05",
     ["Nevada", "Placer"], (39.05, -120.95)),
    ("PE-015", "Sheep Fire", "low", "2022-06-12", "2022-06-14",
     ["San Bernardino"], (34.36, -117.66)),
    ("PE-016", "Rim Fire (first two weeks)", "low", "2013-08-17", "2013-08-30",
     ["Tuolumne"], (37.894, -119.922)),
    ("PE-017", "Caldor Fire (early phase)", "low", "2021-08-14", "2021-08-16",
     ["El Dorado"], (38.5845, -120.5360)),
    ("PE-018", "Lake Fire (2024, first two weeks)", "low", "2024-07-05", "2024-07-18",
     ["Santa Barbara"], (34.758, -120.019)),
    ("PE-019", "LNU Lightning Complex (perimeter section only)", "low", "2020-08-17", "2020-08-18",
     ["Lake", "Napa", "Sonoma", "Yolo", "Colusa"], (38.5039, -122.3373)),
    ("PE-020", "Crews Fire", "low", "2020-07-05", "2020-07-13",
     ["Santa Clara"], (37.011, -121.449)),
]

PRODUCT_START = {"MODIS_SP": "2000-11-01", "VIIRS_SNPP_SP": "2012-01-20", "VIIRS_NOAA20_SP": "2018-04-01"}
SP_END = "2026-06-30"


def products_for(start, end):
    return [p for p, s in PRODUCT_START.items() if end >= s and start <= SP_END]


# stage1 overrides for this set. The PR #26 ones in stage1.py are keyed by event
# id and describe PR #26's fires, so only those that still describe the same fire
# carry over: LNU's Aug-18 run (PE-019) is the same fire. PE-018 is now the Lake
# Fire, so the River Complex exclusion is dropped, and PE-001's hand-widened bbox
# is not applied: this set is checked on the computed tight box alone.
EXCLUDE = {}
LINK_OVERRIDE = {"PE-019": 2}
BBOX_OVERRIDE = {}

# PR #21's data-availability table: closest hourly AQS site, its distance to the
# fire (final perimeter; ignition point for PE-017/PE-019), % hours, peak daily PM2.5.
DOC_CHECK = {
    "PE-001": ("06-045-2002", "Willits", "22.9 km", "97%", 433.9),
    "PE-002": ("06-063-1007", "Chester", "1.5 km", "93%", 568.1),
    "PE-003": ("06-045-0006", "Ukiah-Library", "10.2 km", "97%", 118.2),
    "PE-004": ("06-007-0008", "Chico-East Ave", "4.1 km", "99%", 85.2),
    "PE-005": ("06-001-0007", "Livermore", "5.8 km", "99%", 117.5),
    "PE-006": ("06-053-0002", "Carmel Valley", "6.0 km", "100%", 63.8),
    "PE-007": ("06-097-0004", "Sebastopol", "15.8 km", "99%", 148.6),
    "PE-008": ("06-105-0002", "Weaverville", "13.6 km", "75%", 134.0),
    "PE-009": ("06-065-0012", "Banning Airport", "11.3 km", "100%", 68.2),
    "PE-010": ("06-111-0007", "Thousand Oaks", "2.9 km", "99%", 44.2),
    "PE-011": ("06-093-2001", "Yreka", "17.7 km", "100%", 47.5),
    "PE-012": ("06-051-0001", "Mammoth Lakes", "14.2 km", "99%", 824.1),
    "PE-013": ("06-105-0002", "Weaverville", "32.4 km", "90%", 125.8),
    "PE-014": ("06-061-0004", "Colfax", "1.7 km", "92%", 10.9),
    "PE-015": ("06-071-1004", "Upland", "28.1 km", "100%", 19.7),
    "PE-016": ("06-043-1001", "Yosemite Village", "12.9 km", "99%", 25.0),
    "PE-017": ("06-009-0001", "San Andreas", "44.3 km (ignition)", "100%", 30.0),
    "PE-018": ("06-083-3001", "Santa Ynez", "10.3 km", "100%", 10.3),
    "PE-019": ("06-055-0004", "Napa Valley College", "25.6 km (ignition)", "98%", 35.3),
    "PE-020": ("06-085-0002", "Gilroy", "6.9 km", "99%", 23.7),
}

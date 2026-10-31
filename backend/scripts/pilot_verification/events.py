"""Pilot events as they stand in docs/pilot-events.md on origin/dev (2026-10-06).

anchor = approximate known ignition/main-burn location (lat, lon), used ONLY to
pick which FIRMS cluster is this event when the county union holds several fires.
"""
EVENTS = [
    # id, name, tier, start, end, counties, anchor(lat,lon), nws, monitors listed, purpleair
    ("PE-001", "August Complex Fire", "high", "2020-08-17", "2020-11-12",
     ["Trinity", "Tehama", "Glenn", "Lake", "Mendocino"], (39.85, -122.85)),
    ("PE-002", "Dixie Fire", "high", "2021-07-13", "2021-10-25",
     ["Plumas", "Butte", "Lassen", "Shasta", "Tehama"], (40.15, -121.10)),
    ("PE-003", "Mendocino Complex Fire", "high", "2018-07-27", "2018-09-18",
     ["Mendocino", "Lake", "Colusa", "Glenn"], (39.30, -122.80)),
    ("PE-004", "Park Fire", "high", "2024-07-24", "2024-10-24",
     ["Butte", "Tehama"], (40.00, -121.75)),
    ("PE-005", "SCU Lightning Complex Fire", "high", "2020-08-18", "2020-09-22",
     ["Santa Clara", "Alameda", "Contra Costa", "San Joaquin", "Stanislaus"], (37.40, -121.45)),
    ("PE-006", "Valley Fire", "high-medium", "2015-09-12", "2015-09-22",
     ["Lake"], (38.80, -122.65)),
    ("PE-007", "Glass Fire", "high-medium", "2020-09-27", "2020-10-20",
     ["Napa", "Sonoma"], (38.56, -122.50)),
    ("PE-008", "Carr Fire", "high-medium", "2018-07-23", "2018-08-30",
     ["Shasta", "Trinity"], (40.65, -122.62)),
    ("PE-009", "Witch Fire", "high-medium", "2007-10-21", "2007-11-09",
     ["San Diego"], (33.05, -116.85)),
    ("PE-010", "Woolsey Fire", "high-medium", "2018-11-08", "2018-11-21",
     ["Los Angeles", "Ventura"], (34.10, -118.80)),
    ("PE-011", "Kincade Fire", "medium-low", "2019-10-23", "2019-11-06",
     ["Sonoma"], (38.75, -122.75)),
    ("PE-012", "Creek Fire", "high-medium", "2020-09-04", "2020-12-24",
     ["Fresno", "Madera"], (37.25, -119.30)),
    ("PE-013", "Zogg Fire", "medium-low", "2020-09-27", "2020-10-15",
     ["Shasta", "Trinity"], (40.54, -122.56)),
    ("PE-014", "River Fire", "low", "2021-08-04", "2021-08-08",
     ["Nevada", "Placer"], (39.05, -120.95)),
    ("PE-015", "Sheep Fire", "medium-low", "2022-06-11", "2022-06-14",
     ["San Bernardino"], (34.36, -117.66)),
    ("PE-016", "Antelope Fire (2021)", "low", "2021-08-01", "2021-08-31",
     ["Siskiyou"], (41.55, -121.90)),
    ("PE-017", "Caldor Fire (early phase)", "low", "2021-08-14", "2021-08-16",
     ["El Dorado"], (38.62, -120.50)),
    ("PE-018", "Monument Fire", "low", "2021-07-30", "2021-10-26",
     ["Trinity"], (40.75, -123.30)),
    ("PE-019", "LNU Lightning Complex (perimeter section only)", "low", "2020-08-17", "2020-08-18",
     ["Lake", "Napa", "Sonoma", "Yolo", "Colusa"], (38.60, -122.30)),
    ("PE-020", "Shasta Fire (2017)", "low", "2017-07-06", "2017-07-12",
     ["Shasta"], None),  # the fire named on dev; no known location
]

PRODUCT_START = {"MODIS_SP": "2000-11-01", "VIIRS_SNPP_SP": "2012-01-20", "VIIRS_NOAA20_SP": "2018-04-01"}
SP_END = "2026-06-30"


def products_for(start, end):
    return [p for p, s in PRODUCT_START.items() if end >= s and start <= SP_END]

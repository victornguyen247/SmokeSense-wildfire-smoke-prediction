"""Replacement candidates for PE-016 and PE-017 (screened 2026-10-10 under the final rules).

PE-016 role (large fire, little impact at monitors): the first <= 14 days of a
fire with final size >= 20,000 acres, 2013 or later. PE-017 role (pre-escalation):
the first 3 days of a fire that later grew past 20,000 acres.

Start date, county and anchor (the incident location) come from each fire's
CAL FIRE incident page; the URL is on each row. Skipped as unconfirmed: York
Fire 2023 (CAL FIRE lists the start as 2023-08-01, InciWeb says it began on
July 28).
"""
from events_pr21 import products_for  # noqa: F401

EVENTS = [
    # id, name, tier, start, end, counties, anchor(lat,lon)
    # --- PE-016 role: first 14 days
    # https://www.fire.ca.gov/incidents/2019/9/4/walker-fire (2019-09-04, Plumas, 54,612 ac)
    ("C16-WALKER", "Walker Fire (first two weeks)", None, "2019-09-04", "2019-09-17",
     ["Plumas"], (40.061389, -120.680556)),
    # https://www.fire.ca.gov/incidents/2016/8/13/chimney-fire (2016-08-13, San Luis Obispo, 46,235 ac)
    ("C16-CHIMNEY", "Chimney Fire (first two weeks)", None, "2016-08-13", "2016-08-26",
     ["San Luis Obispo"], (35.70595, -120.98316)),
    # https://www.fire.ca.gov/incidents/2016/8/16/cedar-fire (2016-08-16, Kern, 29,322 ac)
    ("C16-CEDAR", "Cedar Fire (first two weeks)", None, "2016-08-16", "2016-08-29",
     ["Kern"], (35.7506, -118.5678)),
    # https://www.fire.ca.gov/incidents/2017/8/29/pier-fire (2017-08-29, Tulare, 36,556 ac)
    ("C16-PIER", "Pier Fire (first two weeks)", None, "2017-08-29", "2017-09-11",
     ["Tulare"], (36.15356, -118.74103)),
    # https://www.fire.ca.gov/incidents/2023/8/15/smith-river-complex (2023-08-15, Del Norte, 95,107 ac)
    ("C16-SMITH", "Smith River Complex (first two weeks)", None, "2023-08-15", "2023-08-28",
     ["Del Norte"], (41.958269, -123.868447)),
    # --- PE-017 role: first 3 days
    # https://www.fire.ca.gov/incidents/2019/10/23/kincade-fire (2019-10-23, Sonoma, 77,758 ac)
    ("C17-KINCADE", "Kincade Fire (first three days)", None, "2019-10-23", "2019-10-25",
     ["Sonoma"], (38.792458, -122.780053)),
    # https://www.fire.ca.gov/incidents/2022/9/6/mosquito-fire/ (2022-09-06, Placer/El Dorado, 76,788 ac)
    ("C17-MOSQUITO", "Mosquito Fire (first three days)", None, "2022-09-06", "2022-09-08",
     ["Placer", "El Dorado"], (39.00591, -120.7447)),
    # https://www.fire.ca.gov/incidents/2019/9/4/walker-fire (first 3 days)
    ("C17-WALKER", "Walker Fire (first three days)", None, "2019-09-04", "2019-09-06",
     ["Plumas"], (40.061389, -120.680556)),
]

ROLE = {e[0]: ("PE-016" if e[0].startswith("C16") else "PE-017") for e in EVENTS}
FIRE = {e[0]: e[0].split("-", 1)[1] for e in EVENTS}  # same fire in both roles shares a key

EXCLUDE = {}
LINK_OVERRIDE = {}
BBOX_OVERRIDE = {}

"""FIRMS reaches FIRMS_MARGIN_KM beyond the event bbox and FIRMS_LEAD_HOURS before
its start; AirNow, NCEI and PurpleAir keep the tight bbox and window.

No network or DB: the connectors, inserts and session are mocked.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

from ingestion.batch.batch_ingest import PilotEvent, load_pilot_events
from ingestion.batch.firms_extent import (
    FIRMS_LEAD_HOURS,
    FIRMS_MARGIN_KM,
    expand_bbox_km,
    lead_start_date,
)
from ingestion.connectors.airnow import padded_airnow_windows
from ingestion.connectors.airnow_time_offsets import max_abs_shift_hours

TIGHT = "-122.00,39.50,-121.00,40.50"

# Worked by hand for TIGHT (about 40 N), 200 km margin:
#   dlat = 200 / 111.32                         = 1.79662 deg
#   south 39.50 - 1.79662 = 37.70338 -> floor   = 37.70
#   north 40.50 + 1.79662 = 42.29662 -> ceil    = 42.30
#   poleward edge 40.50 N: 111.32 * cos(40.5)   = 84.6484 km/deg lon
#   dlon = 200 / 84.6484                        = 2.36272 deg
#   west -122.00 - 2.36272 = -124.36272 -> floor = -124.37
#   east -121.00 + 2.36272 = -118.63728 -> ceil  = -118.63
WIDE = "-124.37,37.70,-118.63,42.30"


def _hav_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# (a) bbox and window math
# ---------------------------------------------------------------------------

def test_constants():
    assert FIRMS_MARGIN_KM == 200.0
    assert FIRMS_LEAD_HOURS == 72


def test_expand_bbox_matches_hand_computed_example_at_40n():
    assert expand_bbox_km(TIGHT) == WIDE


def test_expanded_margin_is_at_least_200_km_on_every_side():
    w, s, e, n = (float(v) for v in TIGHT.split(","))
    W, S, E, N = (float(v) for v in expand_bbox_km(TIGHT).split(","))
    assert _hav_km(s, w, S, w) >= FIRMS_MARGIN_KM
    assert _hav_km(n, w, N, w) >= FIRMS_MARGIN_KM
    # east-west is tightest at the poleward edge
    assert _hav_km(n, w, n, W) >= FIRMS_MARGIN_KM
    assert _hav_km(n, e, n, E) >= FIRMS_MARGIN_KM


def test_expand_rounds_outward_without_float_drift():
    # 39.26 * 100 is 3925.9999... in floating point; must stay 39.26
    assert expand_bbox_km("-123.86,39.26,-122.13,40.59", 0) == "-123.86,39.26,-122.13,40.59"


def test_expand_clamps_latitude():
    _, south, _, north = expand_bbox_km("-1.00,88.00,1.00,89.00").split(",")
    assert north == "90.00"
    _, south, _, _ = expand_bbox_km("-1.00,-89.00,1.00,-88.00").split(",")
    assert south == "-90.00"


def test_lead_start_date_is_three_days_earlier():
    assert lead_start_date("2020-09-01") == "2020-08-29"
    assert lead_start_date("2021-01-02", 36) == "2020-12-31"  # partial days round up


def test_pilot_event_derives_firms_fields():
    ev = PilotEvent(event_id="E", name="n", bbox=TIGHT, start_date="2020-09-01", end_date="2020-09-02")
    assert ev.firms_bbox == WIDE
    assert ev.firms_start_date == "2020-08-29"
    assert ev.bbox == TIGHT and ev.start_date == "2020-09-01"


def test_loader_derives_fields_and_ignores_them_in_config(tmp_path, capsys):
    cfg = tmp_path / "events.json"
    cfg.write_text(json.dumps({"events": [{
        "event_id": "E", "name": "n", "bbox": TIGHT,
        "start_date": "2020-09-01", "end_date": "2020-09-02",
        "firms_bbox": "0,0,1,1",  # not a config field: warned about and dropped
    }]}))
    (ev,) = load_pilot_events(cfg)
    assert ev.firms_bbox == WIDE
    assert ev.firms_start_date == "2020-08-29"
    assert "firms_bbox" in capsys.readouterr().out


def test_real_config_does_not_carry_derived_fields():
    raw = json.loads((Path(__file__).parents[1] / "docs" / "pilot_events.json").read_text())
    for e in raw["events"]:
        assert "firms_bbox" not in e and "firms_start_date" not in e


# ---------------------------------------------------------------------------
# (b) batch_ingest wiring: FIRMS wide + lead, the rest tight
# ---------------------------------------------------------------------------

@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.insert_airnow_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_weather_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_fire_detections", return_value=0)
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_airnow_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_firms_records", return_value=[])
def test_firms_gets_wide_box_and_lead_others_get_tight(
    firms, airnow, ncei, purpleair, *_mocks,
):
    from ingestion.batch.batch_ingest import ingest_event

    event = PilotEvent(
        event_id="PE-T", name="t", bbox=TIGHT,
        start_date="2020-09-01", end_date="2020-09-02",
        firms_products=["VIIRS_SNPP_SP", "MODIS_SP"],
    )
    ingest_event(event)

    # FIRMS: 2020-08-29..2020-09-02 is one 5-day chunk per product, on the wide box
    calls = [c.kwargs for c in firms.call_args_list]
    assert [(c["source"], c["start_date"], c["day_range"]) for c in calls] == [
        ("VIIRS_SNPP_SP", "2020-08-29", 5),
        ("MODIS_SP", "2020-08-29", 5),
    ]
    assert {c["bbox"] for c in calls} == {WIDE}

    # AirNow: tight box, the same padded windows as before this change
    windows = [(c.kwargs["start_date"], c.kwargs["start_hour"], c.kwargs["end_date"], c.kwargs["end_hour"])
               for c in airnow.call_args_list]
    assert windows == padded_airnow_windows("2020-09-01", "2020-09-02", max_abs_shift_hours())
    assert {c.kwargs["bbox"] for c in airnow.call_args_list} == {TIGHT}

    # NCEI and PurpleAir: tight box and window
    for mock in (ncei, purpleair):
        kw = mock.call_args.kwargs
        assert (kw["bbox"], kw["start_date"], kw["end_date"]) == (TIGHT, "2020-09-01", "2020-09-02")

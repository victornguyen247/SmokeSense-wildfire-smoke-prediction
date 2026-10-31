"""--skip-source: a skipped source is never called, writes no progress row,
and shows up in the coverage report; the other sources run as before.

No network or DB: connectors, inserts, the session and mark_progress are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ingestion.batch import batch_ingest
from ingestion.batch.batch_ingest import (
    SKIPPED_GAP,
    PilotEvent,
    ingest_event,
    ingest_event_with_retries,
    load_event_report,
)


def _event():
    return PilotEvent(
        event_id="PE-T", name="t", bbox="-122.00,39.50,-121.00,40.50",
        start_date="2020-09-01", end_date="2020-09-02",
        firms_products=["VIIRS_SNPP_SP"],
    )


@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.insert_airnow_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_weather_observations", return_value=0)
@patch("ingestion.batch.batch_ingest.insert_fire_detections", return_value=0)
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_airnow_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_firms_records", return_value=[])
def test_skipped_source_is_not_called_and_has_no_progress_row(
    firms, airnow, ncei, purpleair, _fire, _weather, _pm25, _session, mark,
):
    report = ingest_event(_event(), skip=frozenset({"purpleair"})).to_dict()["sources"]

    purpleair.assert_not_called()
    assert {c.args[2] for c in mark.call_args_list} == {"firms", "airnow", "ncei"}
    assert report["purpleair"]["gaps"] == [SKIPPED_GAP]
    assert report["purpleair"]["rows_fetched"] == 0

    # the other sources run unchanged
    assert firms.called and airnow.called and ncei.called
    statuses = {(c.args[2], c.kwargs["status"]) for c in mark.call_args_list}
    assert {("firms", "success"), ("airnow", "success"), ("ncei", "success")} <= statuses
    for source in ("firms", "airnow", "ncei"):
        assert SKIPPED_GAP not in report[source]["gaps"]


@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records")
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records")
@patch("ingestion.batch.batch_ingest.get_airnow_pm25_records")
@patch("ingestion.batch.batch_ingest.get_firms_records")
def test_skipping_every_source_calls_nothing(firms, airnow, ncei, purpleair, _session, mark):
    report = ingest_event(_event(), skip=frozenset(batch_ingest.SOURCES)).to_dict()["sources"]

    for mock in (firms, airnow, ncei, purpleair):
        mock.assert_not_called()
    mark.assert_not_called()
    assert all(report[s]["gaps"] == [SKIPPED_GAP] for s in batch_ingest.SOURCES)


def test_skip_is_passed_through_retries():
    skip = frozenset({"purpleair"})
    with patch("ingestion.batch.batch_ingest.ingest_event") as mock_ingest, \
         patch("ingestion.batch.batch_ingest.time.sleep"):
        mock_ingest.side_effect = [RuntimeError("boom"), MagicMock()]
        ingest_event_with_retries(_event(), resume=False, max_attempts=2, skip=skip)
    assert [c.kwargs["skip"] for c in mock_ingest.call_args_list] == [skip, skip]


def test_failed_event_report_lists_skipped_source():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.all.return_value = []  # no progress rows
    with patch("ingestion.batch.batch_ingest.SessionLocal", return_value=session):
        report = load_event_report("PE-T", "RuntimeError('x')", skip=frozenset({"purpleair"})).to_dict()
    assert report["sources"]["purpleair"]["gaps"] == [SKIPPED_GAP]
    assert "not attempted" in report["sources"]["firms"]["gaps"][0]


def test_cli_skip_source_flag(tmp_path):
    cfg = tmp_path / "events.json"
    cfg.write_text(json.dumps({"events": [{
        "event_id": "PE-T", "name": "t", "bbox": "-122.00,39.50,-121.00,40.50",
        "start_date": "2020-09-01", "end_date": "2020-09-02",
    }]}))
    argv = ["batch_ingest", "--event", "PE-T", "--events-config", str(cfg),
            "--report-out", str(tmp_path / "r.json"),
            "--skip-source", "purpleair", "--skip-source", "ncei"]
    with patch("sys.argv", argv), \
         patch.object(batch_ingest, "ingest_event_with_retries") as run:
        run.return_value = batch_ingest.CoverageReport(event_id="PE-T")
        batch_ingest.main()
    assert run.call_args.kwargs["skip"] == frozenset({"purpleair", "ncei"})


def test_cli_rejects_unknown_source(tmp_path):
    with patch("sys.argv", ["batch_ingest", "--all", "--skip-source", "nws"]), \
         pytest.raises(SystemExit):
        batch_ingest.main()

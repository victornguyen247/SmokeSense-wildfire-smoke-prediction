"""Unit tests for ingestion/batch/batch_ingest.py's pure logic.

Scoped to exactly what the PR #14 review called out as untested:
split_date_range's chunk boundary math, mark_progress's upsert/reset
semantics, and ingest_event_with_retries's force-resume-after-first-
attempt behavior. These don't need a live DB or API -- that's the
reviewer's own point -- so they're mocked rather than hitting real
infrastructure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ingestion.batch.batch_ingest import (
    PilotEvent,
    ingest_event_with_retries,
    mark_progress,
    split_date_range,
)


# ---------------------------------------------------------------------------
# split_date_range
# ---------------------------------------------------------------------------

def test_split_date_range_exact_docstring_example():
    """7-day range (Jul 6-12 inclusive) splits into a 5-day chunk + a 2-day
    chunk, matching the function's own docstring example."""
    assert split_date_range("2017-07-06", "2017-07-12") == [
        ("2017-07-06", 5),
        ("2017-07-11", 2),
    ]


def test_split_date_range_single_day():
    assert split_date_range("2017-07-06", "2017-07-06") == [("2017-07-06", 1)]


def test_split_date_range_exactly_at_cap():
    """A range exactly 5 days long should be one chunk, not split further."""
    assert split_date_range("2017-07-06", "2017-07-10") == [("2017-07-06", 5)]


def test_split_date_range_multiple_full_chunks():
    """11 days should split into two 5-day chunks and a 1-day remainder."""
    assert split_date_range("2017-07-01", "2017-07-11") == [
        ("2017-07-01", 5),
        ("2017-07-06", 5),
        ("2017-07-11", 1),
    ]


def test_split_date_range_rejects_end_before_start():
    with pytest.raises(ValueError):
        split_date_range("2017-07-12", "2017-07-06")


def test_split_date_range_respects_custom_max_days():
    assert split_date_range("2017-07-01", "2017-07-03", max_days=1) == [
        ("2017-07-01", 1),
        ("2017-07-02", 1),
        ("2017-07-03", 1),
    ]


# ---------------------------------------------------------------------------
# mark_progress
# ---------------------------------------------------------------------------
# Mocks the SQLAlchemy query chain so these run without a live DB -- only
# the UPDATE branch (existing row found) is exercised here, since that's
# where the reset-on-running and clear-error-on-success logic lives.

def _mock_session_with_existing_row(existing_row):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.one_or_none.return_value = (
        existing_row
    )
    return session


def test_mark_progress_running_clears_stale_fields_from_prior_attempt():
    """A fresh 'running' attempt must wipe whatever the previous attempt
    left behind -- otherwise a row read mid-run shows stale numbers or an
    old error message from a prior failed try (this was PR #14's finding
    about stale state on rerun)."""
    existing = MagicMock()
    existing.rows_fetched = 999
    existing.rows_written = 999
    existing.error = "some old error from a previous failed attempt"
    existing.finished_at = "some old timestamp"

    session = _mock_session_with_existing_row(existing)

    mark_progress(session, "EVT-1", "firms", status="running")

    assert existing.status == "running"
    assert existing.rows_fetched is None
    assert existing.rows_written is None
    assert existing.error is None
    assert existing.finished_at is None


def test_mark_progress_success_clears_error_from_prior_failure():
    """A success after a prior failure must clear the old error message,
    not leave it sitting on a now-successful row."""
    existing = MagicMock()
    existing.error = "stale error from a previous failed attempt"

    session = _mock_session_with_existing_row(existing)

    mark_progress(
        session, "EVT-1", "firms", status="success",
        rows_fetched=80, rows_written=80,
    )

    assert existing.status == "success"
    assert existing.rows_fetched == 80
    assert existing.rows_written == 80
    assert existing.error is None


def test_mark_progress_failed_records_the_error():
    existing = MagicMock()
    # MagicMock attributes are non-None by default, so start from None or
    # the finished_at assertion below would pass without mark_progress
    # ever setting it.
    existing.finished_at = None
    session = _mock_session_with_existing_row(existing)

    mark_progress(session, "EVT-1", "firms", status="failed", error="boom")

    assert existing.status == "failed"
    assert existing.error == "boom"
    assert existing.finished_at is not None


# ---------------------------------------------------------------------------
# ingest_event_with_retries
# ---------------------------------------------------------------------------

def _dummy_event() -> PilotEvent:
    return PilotEvent(
        event_id="EVT-1",
        name="Test event",
        bbox="-122.5,38.0,-120.5,39.5",
        start_date="2017-07-06",
        end_date="2017-07-06",
    )


def test_first_attempt_honors_the_caller_s_resume_choice():
    """The first attempt must use whatever resume value the caller/CLI
    actually asked for, not force it."""
    with patch("ingestion.batch.batch_ingest.ingest_event") as mock_ingest:
        mock_ingest.return_value = "ok"

        ingest_event_with_retries(_dummy_event(), resume=False)

        mock_ingest.assert_called_once()
        _, kwargs = mock_ingest.call_args
        assert kwargs["resume"] is False


def test_retry_after_failure_forces_resume_true():
    """A retry after a failed attempt must force resume=True regardless
    of what the caller originally asked for -- otherwise a source that
    already committed during the failed attempt gets re-fetched, burning
    API quota for data that's already saved (the exact bug this PR's
    per-source-commit design is meant to avoid)."""
    with patch("ingestion.batch.batch_ingest.ingest_event") as mock_ingest, \
         patch("ingestion.batch.batch_ingest.time.sleep"):  # skip real backoff delay
        mock_ingest.side_effect = [RuntimeError("transient failure"), "ok"]

        ingest_event_with_retries(_dummy_event(), resume=False, max_attempts=3)

        assert mock_ingest.call_count == 2
        first_call_kwargs = mock_ingest.call_args_list[0].kwargs
        second_call_kwargs = mock_ingest.call_args_list[1].kwargs
        assert first_call_kwargs["resume"] is False
        assert second_call_kwargs["resume"] is True


def test_raises_after_exhausting_all_attempts():
    with patch("ingestion.batch.batch_ingest.ingest_event") as mock_ingest, \
         patch("ingestion.batch.batch_ingest.time.sleep"):
        mock_ingest.side_effect = RuntimeError("persistent failure")

        with pytest.raises(RuntimeError, match="persistent failure"):
            ingest_event_with_retries(_dummy_event(), resume=False, max_attempts=3)

        assert mock_ingest.call_count == 3


# ---------------------------------------------------------------------------
# ingest_event -- NCEI + PurpleAir wiring
# ---------------------------------------------------------------------------

def _weather(qc_flag="V", rh_pct=40.0):
    return {"station_id": "KRDD", "qc_flag": qc_flag, "rh_pct": rh_pct,
            "wind_speed_ms": 2.0, "wind_dir_deg": 270.0, "temp_c": 30.0,
            "pressure_hpa": 1010.0, "precip_1h_mm": None}


def _purpleair(sensor="1", correction="purpleair_barkjohn", qa_flag="ok"):
    return {"monitor": {"external_id": sensor},
            "observation": {"correction": correction, "qa_flag": qa_flag,
                            "pm25_cf1_a": 10.0, "pm25_cf1_b": 11.0, "rh_pct": 40.0}}


@patch("ingestion.batch.batch_ingest.mark_progress")
@patch("ingestion.batch.batch_ingest.SessionLocal")
@patch("ingestion.batch.batch_ingest.insert_airnow_observations")
@patch("ingestion.batch.batch_ingest.insert_weather_observations")
@patch("ingestion.batch.batch_ingest.insert_fire_detections", return_value=0)
@patch("ingestion.batch.batch_ingest.get_purpleair_pm25_records")
@patch("ingestion.batch.batch_ingest.get_ncei_weather_records")
@patch("ingestion.batch.batch_ingest.get_airnow_pm25_records", return_value=[])
@patch("ingestion.batch.batch_ingest.get_firms_records", return_value=[])
def test_ingest_event_runs_ncei_and_purpleair(
    _firms, _airnow, get_ncei, get_purpleair, _insert_fire,
    insert_weather, insert_pm25, _session, mark,
):
    from ingestion.batch.batch_ingest import ingest_event, settings

    get_ncei.return_value = [_weather(), _weather(qc_flag="suspect", rh_pct=None)]
    insert_weather.return_value = 2
    get_purpleair.return_value = [
        _purpleair("1"),
        _purpleair("2", correction="purpleair_raw"),
    ]
    insert_pm25.return_value = 1

    event = PilotEvent(
        event_id="PE-T", name="t", bbox="-1,-1,1,1",
        start_date="2020-09-01", end_date="2020-09-02",
    )

    with patch.object(settings, "purpleair_max_sensors", 2):
        report = ingest_event(event).to_dict()["sources"]

    ncei = report["ncei"]
    assert ncei["rows_fetched"] == 2
    assert ncei["rows_written"] == 2
    assert ncei["null_counts"]["rh_pct"] == 1
    assert any("quality control" in g for g in ncei["gaps"])

    pa = report["purpleair"]
    assert pa["rows_fetched"] == 2
    assert pa["duplicates_skipped"] == 1
    assert any("1 rows not label-eligible" in g for g in pa["gaps"])
    assert any("capped" in g for g in pa["gaps"])
    assert get_purpleair.call_args.kwargs["max_sensors"] == 2

    statuses = {(c.args[2], c.kwargs["status"]) for c in mark.call_args_list}
    assert ("ncei", "success") in statuses
    assert ("purpleair", "success") in statuses


# ---------------------------------------------------------------------------
# Failed-event report reflects DB state (load_event_report)
# ---------------------------------------------------------------------------
# Reproduces the 2026-10-03 TEST-PE002-DIXIE run: FIRMS committed 9,658 rows
# (7,930 VIIRS_SNPP_SP + 1,728 MODIS_SP), then the AirNow insert failed on a
# -999 sentinel. The written report used to show "sources": {} even though
# FIRMS was safely in the DB.
#
# Only the connectors, inserts, DB session and sleeps are faked. mark_progress,
# ingest_event, ingest_event_with_retries, load_event_report and main run for
# real against an in-memory batch_ingestion_progress.

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

AIRNOW_CHECK_VIOLATION = (
    '(psycopg.errors.CheckViolation) new row for relation "observations_default" '
    'violates check constraint "observations_pm25_check"'
)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **criteria):
        return _FakeQuery(
            [r for r in self._rows if all(getattr(r, k) == v for k, v in criteria.items())]
        )

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        assert len(self._rows) <= 1
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Just enough of a Session for batch_ingestion_progress reads/writes."""

    def __init__(self, store):
        self._store = store

    def query(self, _model):
        return _FakeQuery(self._store)

    def add(self, obj):
        if obj not in self._store:
            self._store.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _run_main_with_airnow_insert_failure(tmp_path, store):
    from ingestion.batch import batch_ingest

    events_config = tmp_path / "events.json"
    events_config.write_text(json.dumps({"events": [{
        "event_id": "TEST-PE002-DIXIE",
        "name": "mid-event failure",
        "start_date": "2021-08-05",
        "end_date": "2021-08-06",
        "bbox": "-123.1,39.3,-120.0,41.2",
        "firms_products": ["VIIRS_SNPP_SP", "MODIS_SP"],
    }]}))
    report_out = tmp_path / "report.json"

    detections = {"VIIRS_SNPP_SP": 7930, "MODIS_SP": 1728}

    def fake_firms(**kwargs):
        return [{} for _ in range(detections[kwargs["source"]])]

    def fake_load_progress(event_id):
        return batch_ingest.EventProgress(event_id, {
            r.source for r in store
            if r.pilot_event_id == event_id and r.status == "success"
        })

    with patch.object(batch_ingest, "SessionLocal", lambda: _FakeSession(store)), \
         patch.object(batch_ingest, "load_progress", fake_load_progress), \
         patch.object(batch_ingest, "get_firms_records", side_effect=fake_firms) as firms, \
         patch.object(batch_ingest, "insert_fire_detections", return_value=9658), \
         patch.object(batch_ingest, "get_airnow_pm25_records", return_value=[{}] * 286), \
         patch.object(batch_ingest, "insert_airnow_observations",
                      side_effect=RuntimeError(AIRNOW_CHECK_VIOLATION)), \
         patch.object(batch_ingest, "get_ncei_weather_records") as ncei, \
         patch.object(batch_ingest, "get_purpleair_pm25_records") as purpleair, \
         patch.object(batch_ingest.time, "sleep"), \
         patch("sys.argv", ["batch_ingest", "--event", "TEST-PE002-DIXIE",
                            "--events-config", str(events_config),
                            "--report-out", str(report_out)]):
        with pytest.raises(SystemExit) as exit_info:
            batch_ingest.main()

    report = json.loads(report_out.read_text())
    return exit_info.value.code, report, firms, ncei, purpleair


def test_failed_event_report_keeps_already_succeeded_source(tmp_path):
    store = []
    exit_code, report, firms, ncei, purpleair = _run_main_with_airnow_insert_failure(
        tmp_path, store
    )

    assert exit_code == 1
    (event,) = report
    assert "observations_pm25_check" in event["event_error"]

    sources = event["sources"]
    assert list(sources) == ["firms", "airnow", "ncei", "purpleair"]

    # FIRMS committed before AirNow broke: its real counts must survive.
    assert sources["firms"]["rows_fetched"] == 9658
    assert sources["firms"]["rows_written"] == 9658
    assert sources["firms"]["duplicates_skipped"] == 0
    assert sources["firms"]["gaps"] == []

    # The source that broke says why, from its progress row.
    assert sources["airnow"]["gaps"] == [f"failed: {AIRNOW_CHECK_VIOLATION}"]

    # Sources after the failure never ran.
    for name in ("ncei", "purpleair"):
        assert sources[name]["gaps"] == [
            "not attempted (event failed before this source ran)"
        ]
    ncei.assert_not_called()
    purpleair.assert_not_called()

    # Retries forced resume, so FIRMS was fetched once (2 products), not 3x.
    assert firms.call_count == 2


def test_failed_event_report_matches_progress_table(tmp_path):
    store = []
    _, report, *_ = _run_main_with_airnow_insert_failure(tmp_path, store)

    by_source = {r.source: r for r in store}
    assert by_source["firms"].status == "success"
    assert by_source["airnow"].status == "failed"
    assert set(by_source) == {"firms", "airnow"}

    sources = report[0]["sources"]
    assert sources["firms"]["rows_written"] == by_source["firms"].rows_written


def test_load_event_report_running_row_is_reported_as_unfinished():
    from ingestion.batch import batch_ingest

    store = [SimpleNamespace(pilot_event_id="E", source="ncei", status="running",
                             error=None, rows_fetched=None, rows_written=None)]

    with patch.object(batch_ingest, "SessionLocal", lambda: _FakeSession(store)):
        report = batch_ingest.load_event_report("E", "boom").to_dict()

    assert report["event_error"] == "boom"
    assert report["sources"]["ncei"]["gaps"] == ["did not finish (status 'running')"]


def test_main_still_writes_report_if_progress_cannot_be_read(tmp_path):
    from ingestion.batch import batch_ingest

    events_config = tmp_path / "events.json"
    events_config.write_text(json.dumps({"events": [{
        "event_id": "E", "name": "e", "start_date": "2021-08-05",
        "end_date": "2021-08-05", "bbox": "-1,-1,1,1",
    }]}))
    report_out = tmp_path / "report.json"

    with patch.object(batch_ingest, "ingest_event_with_retries",
                      side_effect=RuntimeError("db down")), \
         patch.object(batch_ingest, "load_event_report",
                      side_effect=RuntimeError("db still down")), \
         patch("sys.argv", ["batch_ingest", "--event", "E",
                            "--events-config", str(events_config),
                            "--report-out", str(report_out)]):
        with pytest.raises(SystemExit):
            batch_ingest.main()

    (event,) = json.loads(report_out.read_text())
    assert event["event_error"] == "RuntimeError('db down')"
    assert event["sources"] == {}

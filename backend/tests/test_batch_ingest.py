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

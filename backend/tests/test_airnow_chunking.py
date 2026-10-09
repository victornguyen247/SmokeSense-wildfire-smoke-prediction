"""Unit tests for AirNow date-range chunking and record-limit handling.

AirNow's /aq/data/ endpoint rejects queries over a per-request record cap
with HTTP 400 ("exceeds the record query limit"). These tests cover the
pure splitting logic and the connector's response to that error, with the
HTTP layer mocked -- no API key or network needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from ingestion.connectors import airnow
from ingestion.connectors.airnow import (
    AirNowRecordLimitError,
    fetch_airnow_rows,
    padded_airnow_windows,
    split_airnow_range,
)

LIMIT_BODY = (
    '{"WebServiceError":[{"Message":"This query exceeds the record query '
    "limit. Please narrow the date range and/or area of interest.\"}]}"
)


# ---------------------------------------------------------------------------
# split_airnow_range
# ---------------------------------------------------------------------------

def test_split_single_day():
    assert split_airnow_range("2026-09-01", "2026-09-01") == [
        ("2026-09-01", "2026-09-01")
    ]


def test_split_exactly_at_cap_is_one_chunk():
    assert split_airnow_range("2026-09-01", "2026-09-07", max_days=7) == [
        ("2026-09-01", "2026-09-07")
    ]


def test_split_one_over_cap():
    assert split_airnow_range("2026-09-01", "2026-09-08", max_days=7) == [
        ("2026-09-01", "2026-09-07"),
        ("2026-09-08", "2026-09-08"),
    ]


def test_split_pilot_event_pe020():
    """PE-020 (Jul 6-12, 7 days) fits one default chunk."""
    assert split_airnow_range("2017-07-06", "2017-07-12") == [
        ("2017-07-06", "2017-07-12")
    ]


def test_split_long_event_tiles_range_without_gap_or_overlap():
    """87 days (Aug Complex-length) -> contiguous chunks, none over the cap."""
    chunks = split_airnow_range("2020-08-16", "2020-11-10")  # 87 days
    days = [
        (
            datetime.fromisoformat(end) - datetime.fromisoformat(start)
        ).days
        + 1
        for start, end in chunks
    ]

    assert sum(days) == 87
    assert max(days) <= airnow.MAX_CHUNK_DAYS
    assert chunks[0][0] == "2020-08-16"
    assert chunks[-1][1] == "2020-11-10"

    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert datetime.fromisoformat(next_start) - datetime.fromisoformat(
            prev_end
        ) == timedelta(days=1)


def test_split_crosses_month_and_year_boundaries():
    assert split_airnow_range("2025-12-30", "2026-01-03", max_days=3) == [
        ("2025-12-30", "2026-01-01"),
        ("2026-01-02", "2026-01-03"),
    ]


def test_split_rejects_end_before_start():
    with pytest.raises(ValueError):
        split_airnow_range("2026-09-10", "2026-09-01")


def test_split_rejects_bad_max_days():
    with pytest.raises(ValueError):
        split_airnow_range("2026-09-01", "2026-09-02", max_days=0)


# ---------------------------------------------------------------------------
# padded_airnow_windows
# ---------------------------------------------------------------------------

def _hours(window):
    start_date, start_hour, end_date, end_hour = window
    start = datetime.fromisoformat(f"{start_date}T{start_hour}:00")
    end = datetime.fromisoformat(f"{end_date}T{end_hour}:00")
    return [start + timedelta(hours=h) for h in range(int((end - start).total_seconds() // 3600) + 1)]


def test_padded_single_chunk():
    assert padded_airnow_windows("2021-08-05", "2021-08-06", 1) == [
        ("2021-08-04", "23", "2021-08-07", "00")
    ]


def test_zero_padding_matches_split_airnow_range():
    windows = padded_airnow_windows("2026-09-01", "2026-09-10", 0, max_days=7)
    assert windows == [
        ("2026-09-01", "00", "2026-09-07", "23"),
        ("2026-09-08", "00", "2026-09-10", "23"),
    ]


def test_padding_moves_only_outer_ends_and_tiles_hourly():
    """Long range, 2 h pad crossing a year boundary: contiguous hours, no
    gap or overlap, first and last padded."""
    windows = padded_airnow_windows("2020-12-20", "2021-01-15", 2, max_days=7)

    hours = [h for w in windows for h in _hours(w)]
    assert hours[0] == datetime(2020, 12, 19, 22)
    assert hours[-1] == datetime(2021, 1, 16, 1)
    assert hours == [hours[0] + timedelta(hours=i) for i in range(len(hours))]
    # inner boundaries are untouched
    assert [w[1] for w in windows[1:]] == ["00"] * (len(windows) - 1)
    assert [w[3] for w in windows[:-1]] == ["23"] * (len(windows) - 1)


def test_padding_rejects_negative():
    with pytest.raises(ValueError):
        padded_airnow_windows("2021-08-05", "2021-08-06", -1)


def test_bisection_of_padded_window_covers_every_hour_once():
    """A padded 7-day chunk (170 h) hitting the cap repeatedly is bisected
    down to <=24 h requests that still tile it exactly."""
    window = padded_airnow_windows("2021-08-05", "2021-08-11", 1)[0]
    assert window == ("2021-08-04", "23", "2021-08-12", "00")

    def fake_request(api_key, bbox, start, end, verbose=False):
        hours = int((end - start).total_seconds() // 3600) + 1
        if hours > 24:
            raise AirNowRecordLimitError("over cap")
        return [start + timedelta(hours=h) for h in range(hours)]

    with patch.object(airnow, "_request_airnow_rows", side_effect=fake_request):
        rows = fetch_airnow_rows(
            "key", start_date=window[0], start_hour=window[1],
            end_date=window[2], end_hour=window[3],
        )

    assert rows == _hours(window)


# ---------------------------------------------------------------------------
# Record-limit handling
# ---------------------------------------------------------------------------

def _response(status: int, body: str, json_payload=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.text = body
    if json_payload is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_payload
    return response


def _patched_client(responses):
    """Patch httpx.Client so successive .get() calls return `responses`."""
    client = MagicMock()
    client.get.side_effect = responses
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client
    return patch.object(airnow.httpx, "Client", return_value=client_cm), client


def test_http_400_record_limit_raises_typed_error():
    patcher, _ = _patched_client([_response(400, LIMIT_BODY)])

    with patcher, pytest.raises(AirNowRecordLimitError):
        # single-hour window cannot be bisected, so the error surfaces
        fetch_airnow_rows(
            "key", start_date="2026-09-01", start_hour="05",
            end_date="2026-09-01", end_hour="05",
        )


def test_other_http_errors_are_not_treated_as_record_limit():
    patcher, _ = _patched_client([_response(500, "server exploded")])

    with patcher, pytest.raises(RuntimeError) as excinfo:
        fetch_airnow_rows("key", start_date="2026-09-01", end_date="2026-09-02")

    assert not isinstance(excinfo.value, AirNowRecordLimitError)


def test_record_limit_error_under_http_200_envelope_is_detected():
    envelope = {"WebServiceError": [{"Message": "exceeds the record query limit"}]}
    patcher, _ = _patched_client([_response(200, "", json_payload=envelope)])

    with patcher, pytest.raises(AirNowRecordLimitError):
        fetch_airnow_rows(
            "key", start_date="2026-09-01", start_hour="05",
            end_date="2026-09-01", end_hour="05",
        )


def test_window_over_cap_is_bisected_and_rows_are_joined():
    """First request hits the cap; each half succeeds; result is both halves."""
    first_half = [{"id": "a"}]
    second_half = [{"id": "b"}]
    patcher, client = _patched_client(
        [
            _response(400, LIMIT_BODY),
            _response(200, "", json_payload=first_half),
            _response(200, "", json_payload=second_half),
        ]
    )

    with patcher:
        rows = fetch_airnow_rows(
            "key",
            start_date="2026-09-01", start_hour="00",
            end_date="2026-09-01", end_hour="23",
        )

    assert rows == first_half + second_half
    assert client.get.call_count == 3

    # The halves must tile the 24-hour window exactly: 00-11 then 12-23.
    sent = [call.kwargs["params"] for call in client.get.call_args_list]
    assert (sent[0]["startDate"], sent[0]["endDate"]) == (
        "2026-09-01T00", "2026-09-01T23"
    )
    assert (sent[1]["startDate"], sent[1]["endDate"]) == (
        "2026-09-01T00", "2026-09-01T11"
    )
    assert (sent[2]["startDate"], sent[2]["endDate"]) == (
        "2026-09-01T12", "2026-09-01T23"
    )


def test_bisection_with_odd_hour_count_has_no_gap_or_overlap():
    patcher, client = _patched_client(
        [
            _response(400, LIMIT_BODY),
            _response(200, "", json_payload=[]),
            _response(200, "", json_payload=[]),
        ]
    )

    with patcher:
        fetch_airnow_rows(
            "key",
            start_date="2026-09-01", start_hour="00",
            end_date="2026-09-01", end_hour="04",  # 5 hours
        )

    sent = [call.kwargs["params"] for call in client.get.call_args_list]
    assert (sent[1]["startDate"], sent[1]["endDate"]) == (
        "2026-09-01T00", "2026-09-01T01"
    )
    assert (sent[2]["startDate"], sent[2]["endDate"]) == (
        "2026-09-01T02", "2026-09-01T04"
    )


def test_fetch_rejects_end_before_start():
    with pytest.raises(ValueError):
        fetch_airnow_rows(
            "key",
            start_date="2026-09-02", start_hour="00",
            end_date="2026-09-01", end_hour="23",
        )

"""API keys must never reach the logs.

httpx logs every request line, full URL included, at INFO. AirNow takes its
key as a query parameter and FIRMS puts its map key in the URL path, so a
process logging at INFO would write both keys out. A scratchpad log of a
PE-002 run held the AirNow key this way. ingestion/__init__.py raises the
httpx/httpcore loggers to WARNING (app/core/logging.py); these tests run
the real connectors against httpx.MockTransport with the root logger at
INFO and check the keys are absent.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import httpx
import pytest

from app.core.logging import QUIET_LOGGERS, quiet_http_loggers
from ingestion.connectors.airnow import fetch_airnow_rows
from ingestion.connectors.firms import fetch_firms_rows

FIRMS_KEY = "firms-test-map-key-0123456789"
AIRNOW_KEY = "AIRNOW-TEST-KEY-0000-1111-2222"

_RealClient = httpx.Client


def _handler(request: httpx.Request) -> httpx.Response:
    if "firms" in request.url.host:
        return httpx.Response(200, text="latitude,longitude,bright_ti4\n")
    return httpx.Response(200, json=[])


def _mock_client(seen: list[str]):
    """httpx.Client factory that serves canned responses and records URLs."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _handler(request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _RealClient(*args, **kwargs)

    return patch.object(httpx, "Client", side_effect=factory)


def _call_both(seen: list[str]) -> None:
    with _mock_client(seen):
        fetch_firms_rows(FIRMS_KEY, bbox="-122.3,40.15,-122.2,40.2", day_range=1)
        fetch_airnow_rows(
            AIRNOW_KEY, bbox="-122.30,40.15,-122.21,40.19",
            start_date="2021-08-05", start_hour="12",
            end_date="2021-08-05", end_hour="12",
        )


def test_keys_are_not_logged_at_info(caplog):
    caplog.set_level(logging.INFO)  # root at INFO, like basicConfig or celery --loglevel=info
    seen: list[str] = []

    _call_both(seen)

    # The keys really were in the request URLs...
    assert any(FIRMS_KEY in url for url in seen)
    assert any(AIRNOW_KEY in url for url in seen)
    # ...and none of it reached the logs.
    assert FIRMS_KEY not in caplog.text
    assert AIRNOW_KEY not in caplog.text
    assert not [r for r in caplog.records if r.name in QUIET_LOGGERS]


def test_keys_are_not_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG)

    _call_both([])

    assert FIRMS_KEY not in caplog.text
    assert AIRNOW_KEY not in caplog.text


@pytest.mark.parametrize("name", QUIET_LOGGERS)
def test_http_loggers_are_quiet_after_importing_ingestion(name):
    assert logging.getLogger(name).level == logging.WARNING


def test_without_the_guard_httpx_would_log_both_keys(caplog):
    """Control: proves the test above would catch a regression."""
    caplog.set_level(logging.INFO)
    try:
        for name in QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)

        _call_both([])

        assert FIRMS_KEY in caplog.text
        assert AIRNOW_KEY in caplog.text
    finally:
        quiet_http_loggers()

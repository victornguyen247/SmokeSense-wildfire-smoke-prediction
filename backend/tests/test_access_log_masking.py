"""API-05: tokens in the query of /api/v1/alerts/* never reach the access log.

The one-click unsubscribe URL (RFC 8058) is `POST /api/v1/alerts/unsubscribe?token=…`, and
uvicorn logs every request line with its query string. app/main.py installs a filter on
the `uvicorn.access` logger that masks it (docs/alerts.md section 2).
"""

from __future__ import annotations

import logging

import pytest

import app.main  # noqa: F401  (installs the filter, as starting the app does)
from app.core.logging import ACCESS_LOGGER, MaskedQueryFilter, mask_access_log_queries, mask_query

TOKEN = "Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGx"  # 43 chars, like a real token
# uvicorn's access log call: logger.info(fmt, client, method, path_with_query, http_version, status)
UVICORN_FORMAT = '%s - "%s %s HTTP/%s" %d'


def log_request(method: str, path: str, status: int = 200) -> None:
    logging.getLogger(ACCESS_LOGGER).info(UVICORN_FORMAT, "127.0.0.1:50000", method, path, "1.1", status)


def test_one_click_unsubscribe_token_is_not_in_the_access_log(caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        log_request("POST", f"/api/v1/alerts/unsubscribe?token={TOKEN}")
    assert TOKEN not in caplog.text
    assert '"POST /api/v1/alerts/unsubscribe?*** HTTP/1.1" 200' in caplog.text


@pytest.mark.parametrize(
    ("path", "logged"),
    [
        (f"/api/v1/alerts/confirm?token={TOKEN}", "/api/v1/alerts/confirm?***"),
        ("/api/v1/alerts/subscriptions", "/api/v1/alerts/subscriptions"),  # no query: unchanged
        ("/api/v1/forecast/point?lat=39.7&lon=-121.8", "/api/v1/forecast/point?lat=39.7&lon=-121.8"),
        (f"/api/v1/alertsX?token={TOKEN}", f"/api/v1/alertsX?token={TOKEN}"),  # not an alert path
    ],
)
def test_only_alert_paths_are_masked(path, logged):
    assert mask_query(path) == logged


def test_the_filter_is_installed_once():
    mask_access_log_queries()
    mask_access_log_queries()
    filters = logging.getLogger(ACCESS_LOGGER).filters
    assert sum(isinstance(f, MaskedQueryFilter) for f in filters) == 1


def test_records_with_unexpected_args_pass_through_unchanged():
    record = logging.LogRecord(ACCESS_LOGGER, logging.INFO, __file__, 1, "plain message", None, None)
    assert MaskedQueryFilter().filter(record) is True
    assert record.getMessage() == "plain message"

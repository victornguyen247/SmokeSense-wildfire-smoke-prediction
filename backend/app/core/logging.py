"""Process-wide logging defaults.

httpx logs every request line, full URL included, at INFO. AirNow takes its
API key as a query parameter and FIRMS puts its map key in the URL path, so
any process logging at INFO (logging.basicConfig(level=logging.INFO), a
Celery worker started with --loglevel=info) would write those keys to its
logs. httpcore is quieted for the same reason at DEBUG.
"""

from __future__ import annotations

import logging

QUIET_LOGGERS = ("httpx", "httpcore")


def quiet_http_loggers() -> None:
    """Raise the HTTP client loggers to WARNING so request URLs are never logged.

    Sets each logger's own level, so it holds whatever level or handlers the
    root logger is given later (basicConfig, Celery's worker logging setup).
    """
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

"""Process-wide logging defaults.

httpx logs every request line, full URL included, at INFO. AirNow takes its
API key as a query parameter and FIRMS puts its map key in the URL path, so
any process logging at INFO (logging.basicConfig(level=logging.INFO), a
Celery worker started with --loglevel=info) would write those keys to its
logs. httpcore is quieted for the same reason at DEBUG.

The API's own access log (uvicorn.access) gets the query string of /api/v1/alerts/*
masked, because the one-click unsubscribe URL carries a token there.
"""

from __future__ import annotations

import logging

QUIET_LOGGERS = ("httpx", "httpcore")

# The one-click unsubscribe URL carries its token in the query string (RFC 8058, see
# docs/alerts.md section 2), so access logs must never show the query of these paths.
MASKED_QUERY_PREFIXES = ("/api/v1/alerts/",)
ACCESS_LOGGER = "uvicorn.access"


def quiet_http_loggers() -> None:
    """Raise the HTTP client loggers to WARNING so request URLs are never logged.

    Sets each logger's own level, so it holds whatever level or handlers the
    root logger is given later (basicConfig, Celery's worker logging setup).
    """
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def mask_query(path: str) -> str:
    """`path?query` with the query replaced by `?***` for the masked prefixes."""
    base, sep, _ = path.partition("?")
    if sep and base.startswith(MASKED_QUERY_PREFIXES):
        return f"{base}?***"
    return path


class MaskedQueryFilter(logging.Filter):
    """Masks the query string of /api/v1/alerts/* in uvicorn access log lines.

    uvicorn logs `'%s - "%s %s HTTP/%s" %d'` with args (client, method, path_with_query,
    http_version, status). The record is changed, not dropped, so the request still
    shows up in the log.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], mask_query(args[2]), *args[3:])
        return True


def mask_access_log_queries() -> None:
    """Install MaskedQueryFilter on uvicorn's access logger (idempotent).

    A logger filter runs for every record logged on that logger, whatever handlers
    uvicorn's log config attaches. uvicorn configures logging before it imports the app,
    so calling this from app/main.py adds the filter after that.
    """
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, MaskedQueryFilter) for f in logger.filters):
        logger.addFilter(MaskedQueryFilter())

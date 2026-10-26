"""Shared plumbing for the live jobs: settings, HTTP retries, ingestion_runs bookkeeping.

Every job goes through run_job(), which opens its ingestion_runs row, runs the job,
and records success, partial or failure. A job never raises out of run_job(), so one
source failing cannot stop another, and nothing chains the sources together.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

import httpx
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import IngestionRun

logger = logging.getLogger("ingestion.live")

# Cadence and window knobs are plain environment variables, like the rest of
# ingestion/ (CLAUDE.md rule 2). Load backend/.env once so a CLI run sees them;
# Docker passes the same variables through env_file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

# Rough California extent (west, south, east, north): the same box as API-01's
# CALIFORNIA_BBOX (PR #83). Defined here until that lands in app/core/scope.py.
CA_BBOX = (-124.5, 32.5, -114.1, 42.1)

# Live rows older than this are deleted by retention (live rows only).
DEFAULT_WINDOW_HOURS = 72

# Read timeout per request (LIVE_HTTP_TIMEOUT_S). Generous: AirNow took 40-55 s for
# even a small box on 2026-10-23, and the statewide FIRMS pull is large.
DEFAULT_READ_TIMEOUT_S = 120.0


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def floor_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def bbox_str(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:g}" for v in bbox)


# ---------------------------------------------------------------------------
# HTTP with bounded retries
# ---------------------------------------------------------------------------


def retry_after_seconds(
    response: httpx.Response, now: datetime | None = None
) -> float | None:
    """Retry-After as seconds (delta-seconds or HTTP-date form), or None if absent/unreadable."""
    value = response.headers.get("retry-after", "").strip()
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - (now or utc_now())).total_seconds(), 0.0)


class RetryTransport(httpx.BaseTransport):
    """Retry transient failures with bounded exponential backoff, honoring Retry-After.

    Retries network errors and the given statuses up to `attempts` times in total,
    waiting backoff_s, 2x, 4x, ... (never less than the server's Retry-After). A wait
    longer than max_wait_s is not slept: the response is returned as is and the next
    scheduled run tries again. Request URLs are never logged (they carry keys).
    """

    def __init__(
        self,
        retry_statuses: frozenset[int],
        *,
        attempts: int = 3,
        backoff_s: float = 2.0,
        max_wait_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.retry_statuses = retry_statuses
        self.attempts = attempts
        self.backoff_s = backoff_s
        self.max_wait_s = max_wait_s
        self.sleep = sleep
        self.transport = transport or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for attempt in range(1, self.attempts + 1):
            wait = self.backoff_s * 2 ** (attempt - 1)
            try:
                response = self.transport.handle_request(request)
            except httpx.TransportError:
                if attempt == self.attempts:
                    raise
                logger.warning(
                    "network error, retry %d/%d in %.0fs",
                    attempt,
                    self.attempts - 1,
                    wait,
                )
                self.sleep(wait)
                continue

            if (
                response.status_code not in self.retry_statuses
                or attempt == self.attempts
            ):
                return response

            server_wait = retry_after_seconds(response)
            if server_wait is not None:
                wait = max(wait, server_wait)
            if wait > self.max_wait_s:
                logger.warning(
                    "HTTP %d asks to wait %.0fs (> %.0fs cap); not retrying this run",
                    response.status_code,
                    wait,
                    self.max_wait_s,
                )
                return response

            response.close()
            logger.warning(
                "HTTP %d, retry %d/%d in %.0fs",
                response.status_code,
                attempt,
                self.attempts - 1,
                wait,
            )
            self.sleep(wait)

        raise AssertionError("unreachable")  # the loop always returns or raises

    def close(self) -> None:
        self.transport.close()


def live_client(
    retry_statuses: frozenset[int],
    *,
    headers: dict[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Client:
    """httpx client for a live job: retrying transport, live timeout, redirects followed."""
    transport = RetryTransport(
        retry_statuses,
        attempts=env_int("LIVE_HTTP_ATTEMPTS", 3),
        backoff_s=env_float("LIVE_HTTP_BACKOFF_S", 2.0),
        max_wait_s=env_float("LIVE_HTTP_MAX_WAIT_S", 60.0),
        sleep=sleep,
    )
    timeout = httpx.Timeout(
        env_float("LIVE_HTTP_TIMEOUT_S", DEFAULT_READ_TIMEOUT_S), connect=10.0
    )
    return httpx.Client(
        transport=transport,
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    )


def client_scope(
    client: httpx.Client | None,
    retry_statuses: frozenset[int],
    headers: dict[str, str] | None = None,
):
    """Context for a job's HTTP client: the caller's (left open) or a new live_client."""
    if client is not None:
        return contextlib.nullcontext(client)
    return live_client(retry_statuses, headers=headers)


# ---------------------------------------------------------------------------
# Errors and secrets
# ---------------------------------------------------------------------------


def _secrets() -> list[str]:
    values = (
        settings.firms_map_key,
        settings.airnow_api_key,
        settings.purpleair_api_key,
        settings.nws_user_agent,
    )
    return [v for v in values if v and len(v) >= 4]


def safe_error(exc: BaseException, limit: int = 500) -> str:
    """One-line error summary with every configured key or contact string removed."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in _secrets():
        text = text.replace(secret, "[redacted]")
    return " ".join(text.split())[:limit]


# ---------------------------------------------------------------------------
# ingestion_runs bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class JobResult:
    """What a job reports back to run_job."""

    rows_fetched: int = 0
    rows_written: int = 0
    watermark: datetime | None = None
    errors: list[str] = field(
        default_factory=list
    )  # partial failures (e.g. one NWS station)
    failed: bool = False  # every unit of work failed

    def see(self, ts: datetime | None) -> None:
        if ts is not None and (self.watermark is None or ts > self.watermark):
            self.watermark = ts


Job = Callable[[Session, str, datetime], JobResult]


def run_job(
    source: str, job: Job, *, session_factory, now: datetime | None = None
) -> dict:
    """Run one live job inside its own ingestion_runs row. Never raises.

    The run row is committed as 'running' first, so a crash mid-run is visible. The
    job gets (session, run_id, now) and commits its own writes as it goes; on an
    exception its uncommitted work is rolled back and the run is marked failed.
    """
    # The run's clock: started_at is `now` and finished_at adds the real elapsed time,
    # so a run replayed at a fixed time (tests, backfills) has a consistent timeline.
    wall_start = utc_now()
    now = now or wall_start
    session = session_factory()
    run = IngestionRun(
        source=source,
        started_at=now,
        status="running",
        rows_fetched=0,
        rows_written=0,
    )
    try:
        session.add(run)
        session.commit()
    except Exception as exc:  # DB down: nothing to record into
        session.rollback()
        session.close()
        logger.error(
            "live %s: could not open an ingestion run: %s", source, safe_error(exc)
        )
        return {"source": source, "status": "failed", "error": safe_error(exc)}

    run_id = run.id
    try:
        result = job(session, run_id, now)
        session.commit()
        status = (
            "failed" if result.failed else ("partial" if result.errors else "success")
        )
        error = "; ".join(result.errors)[:500] or None
    except Exception as exc:
        session.rollback()
        result = JobResult()
        status, error = "failed", safe_error(exc)

    run = session.get(IngestionRun, run_id)
    run.status = status
    run.finished_at = now + (utc_now() - wall_start)
    run.rows_fetched = result.rows_fetched
    run.rows_written = result.rows_written
    run.watermark = result.watermark
    run.error = error
    session.commit()
    session.close()

    log = logger.error if status == "failed" else logger.info
    log(
        "live %s: %s, fetched=%d written=%d%s",
        source,
        status,
        result.rows_fetched,
        result.rows_written,
        f" error={error}" if error else "",
    )
    return {
        "source": source,
        "status": status,
        "run_id": run_id,
        "rows_fetched": result.rows_fetched,
        "rows_written": result.rows_written,
        "watermark": result.watermark.isoformat() if result.watermark else None,
        "error": error,
    }


def lookback_start(
    session: Session,
    source: str,
    now: datetime,
    overlap_hours: int,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> datetime:
    """Start of the window a run should fetch.

    From overlap_hours before the last successful (or partial) run started, so a
    gap after failed runs is filled and late arrivals and revisions in the overlap
    are picked up. Never earlier than the window, so a first run backfills exactly
    window_hours.
    """
    window_start = now - timedelta(hours=window_hours)
    last = session.scalar(
        select(func.max(IngestionRun.started_at)).where(
            IngestionRun.source == source,
            IngestionRun.status.in_(("success", "partial")),
            IngestionRun.started_at >= window_start,
        )
    )
    if last is None:
        return window_start
    return max(window_start, min(last, now) - timedelta(hours=overlap_hours))

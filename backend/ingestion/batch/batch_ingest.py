"""DATA-03: Historical batch ingestion CLI for pilot events.

Generalizes the DATA-02 POC into a batch job that loops over every pilot
event, pulls fire/weather/PM2.5 data for its date range + downwind region,
and writes to the cleaned historical store.

Usage:
    python -m ingestion.batch.batch_ingest --event kincade_2026
    python -m ingestion.batch.batch_ingest --all
    python -m ingestion.batch.batch_ingest --event kincade_2026 --resume
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from datetime import date, datetime, timedelta, timezone

from ingestion.connectors.firms import get_firms_records
from ingestion.connectors.airnow import get_airnow_pm25_records

# TODO: once built, import the weather + PurpleAir connectors here too:
# from ingestion.connectors.ncei import get_ncei_weather_records
# from ingestion.connectors.purpleair import get_purpleair_records

from ingestion.db import SessionLocal, insert_fire_detections, insert_airnow_observations
from app.core.config import settings

# Confirmed 2026-09-29 via Claude Code against origin/dev (PR #12):
# insert_fire_detections(session, rows: list[dict]) -> int
# insert_airnow_observations(session, rows: list[dict]) -> int
# Both return a plain written-count, not a tuple. Duplicate/skipped counts
# aren't returned directly -- derived below as rows_fetched - rows_written.


# ---------------------------------------------------------------------------
# Pilot event definitions
# ---------------------------------------------------------------------------
# NOTE: this assumes pilot events get a structured config (pilot_events.yaml
# or .json) rather than parsing docs/pilot-events.md directly. Worth raising
# with whoever owns PM-01/pilot-events.md if that doesn't exist yet.

PILOT_EVENTS_PATH = Path("docs/pilot_events.json")


@dataclass
class PilotEvent:
    event_id: str
    name: str
    bbox: str
    start_date: str  # "YYYY-MM-DD"
    end_date: str  # "YYYY-MM-DD"
    firms_products: list[str] = field(default_factory=list)
    region: str = ""
    tier: str = ""
    bbox_note: str = ""
    firms_products_note: str = ""
    nws_grid: list[str] = field(default_factory=list)
    airnow_monitors_nearby: list[str] = field(default_factory=list)
    purpleair_density: str = ""
    verification_status: str = "pending"
    verification_note: str = ""


def load_pilot_events(path: Path = PILOT_EVENTS_PATH) -> list[PilotEvent]:
    """Load the structured pilot event list.

    Raises a clear error if the config doesn't exist yet, rather than
    failing on a confusing KeyError deep in the loop below.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Pilot event config not found at {path}. "
            "This needs a machine-readable list (YAML/JSON) derived from "
            "docs/pilot-events.md before batch ingestion can run — check "
            "with whoever owns PM-01 if this hasn't been created."
        )

    with path.open() as f:
        raw = json.load(f)

    known_fields = {f.name for f in dataclasses.fields(PilotEvent)}
    events = []

    for raw_event in raw["events"]:
        unknown = set(raw_event) - known_fields
        if unknown:
            print(
                f"[load_pilot_events] warning: dropping unrecognized field(s) "
                f"{sorted(unknown)} on event {raw_event.get('event_id', '?')} "
                "-- add them to the PilotEvent dataclass if they should be used."
            )
        filtered = {k: v for k, v in raw_event.items() if k in known_fields}
        events.append(PilotEvent(**filtered))

    return events


# ---------------------------------------------------------------------------
# Raw snapshot retention — INTENTIONALLY NOT IMPLEMENTED
# ---------------------------------------------------------------------------
# Resolved 2026-09-29 via team Discord: direction confirmed as NOT storing
# raw provider payloads (Vuong updating the DATA-03 issue to match). This
# matches DATA-02's existing decision in docs/poc-ingestion.md — provenance
# metadata (source, external_id, source_timestamp) is preserved on each row
# instead, which is enough to trace a record back to its provider without
# keeping the full raw response around.
#
# If this ever needs to change, save_raw_snapshot() lived here before and
# can be resurrected from version control — no need to redesign from
# scratch.


# ---------------------------------------------------------------------------
# FIRMS date-range splitting
# ---------------------------------------------------------------------------
# FIRMS's area/csv API caps day_range at 1-5 per request (confirmed during
# DATA-01). Any pilot event longer than 5 days needs multiple requests
# stitched together. Even PE-020, the simplest test event, needs this --
# it spans 6 days (Jul 6-12), one day over the cap.

def split_date_range(
    start_date: str, end_date: str, max_days: int = 5
) -> list[tuple[str, int]]:
    """Split a start/end date range into FIRMS-sized (start, day_range) chunks.

    e.g. split_date_range("2017-07-06", "2017-07-12") ->
        [("2017-07-06", 5), ("2017-07-11", 2)]
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    total_days = (end - start).days + 1

    if total_days <= 0:
        raise ValueError(f"end_date {end_date} is not after start_date {start_date}")

    chunks = []
    cursor = start
    remaining = total_days

    while remaining > 0:
        chunk_len = min(max_days, remaining)
        chunks.append((cursor.isoformat(), chunk_len))
        cursor += timedelta(days=chunk_len)
        remaining -= chunk_len

    return chunks


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------

def with_retries(
    fn: Callable[[], object],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 2.0,
    label: str = "request",
) -> object:
    """Retry a transient-failure-prone call with exponential backoff.

    Only retries on exceptions — callers should raise (not swallow) on
    HTTP errors from the connectors so this actually has something to
    catch. Does not retry on the last attempt; the final exception
    propagates so the run gets marked failed rather than silently
    succeeding with partial data.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_attempts:
                raise
            delay = base_delay_s * (2 ** (attempt - 1))
            print(
                f"[{label}] attempt {attempt}/{max_attempts} failed "
                f"({exc!r}); retrying in {delay:.1f}s"
            )
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Resumability
# ---------------------------------------------------------------------------
# Backed by batch_ingestion_progress (see the 0002 migration) -- a durable,
# purpose-built completion tracker, separate from DATA-02's ingestion_runs
# (which is a 90-day rolling audit log and would silently "forget" progress
# on old events).

from app.models.operations import BatchIngestionProgress  # noqa: E402


@dataclass
class EventProgress:
    event_id: str
    completed_sources: set[str] = field(default_factory=set)

    def is_done(self, source: str) -> bool:
        return source in self.completed_sources

    def mark_done(self, source: str) -> None:
        self.completed_sources.add(source)


def load_progress(event_id: str) -> EventProgress:
    """Check batch_ingestion_progress for sources already marked success."""
    session = SessionLocal()
    try:
        rows = (
            session.query(BatchIngestionProgress.source)
            .filter(
                BatchIngestionProgress.pilot_event_id == event_id,
                BatchIngestionProgress.status == "success",
            )
            .all()
        )
        completed_sources = {row[0] for row in rows}
    finally:
        session.close()

    return EventProgress(event_id=event_id, completed_sources=completed_sources)


def mark_progress(
    session,
    event_id: str,
    source: str,
    status: str,
    rows_fetched: int | None = None,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    """Upsert this (event, source) pair's progress row and commit immediately.

    Commits on its own -- deliberately not sharing a transaction with the
    source's data-insert commit -- so a "failed" status write survives even
    when the caller's own rollback() has already discarded that attempt's
    data. This sidesteps the exact bug found in DATA-02's tasks.py, where
    session.rollback() before updating the run's status likely discards
    the status write along with the failed data.
    """
    now = datetime.now(timezone.utc)

    existing = (
        session.query(BatchIngestionProgress)
        .filter_by(pilot_event_id=event_id, source=source)
        .one_or_none()
    )

    if existing is None:
        existing = BatchIngestionProgress(
            pilot_event_id=event_id,
            source=source,
            status=status,
            started_at=now,
        )
        session.add(existing)
    else:
        existing.status = status

    if status == "running":
        # Starting a fresh attempt -- clear whatever the previous attempt
        # left behind, so a row read mid-run doesn't show stale numbers
        # or an old error message from a prior failed try.
        existing.started_at = now
        existing.finished_at = None
        existing.rows_fetched = None
        existing.rows_written = None
        existing.error = None
    else:
        if rows_fetched is not None:
            existing.rows_fetched = rows_fetched
        if rows_written is not None:
            existing.rows_written = rows_written
        # Set explicitly (even to None) rather than "if error is not None"
        # -- a success after a prior failure needs to actually clear the
        # old error message, not leave it sitting on a success row.
        existing.error = error
        if status in ("success", "failed", "partial"):
            existing.finished_at = now

    session.commit()


# ---------------------------------------------------------------------------
# Data-quality report
# ---------------------------------------------------------------------------

@dataclass
class SourceCoverage:
    source: str
    rows_fetched: int = 0
    rows_written: int = 0
    duplicates_skipped: int = 0  # rows_fetched - rows_written; expected/healthy, not a gap
    null_counts: dict[str, int] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)  # genuine coverage problems only
    skipped_resume: bool = False  # True = not re-run this pass, already done in an earlier run


@dataclass
class CoverageReport:
    event_id: str
    sources: dict[str, SourceCoverage] = field(default_factory=dict)

    def record(self, coverage: SourceCoverage) -> None:
        self.sources[coverage.source] = coverage

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "sources": {
                name: {
                    "rows_fetched": c.rows_fetched,
                    "rows_written": c.rows_written,
                    "duplicates_skipped": c.duplicates_skipped,
                    "null_counts": c.null_counts,
                    "gaps": c.gaps,
                    "skipped_resume": c.skipped_resume,
                }
                for name, c in self.sources.items()
            },
        }


def load_existing_coverage(session, event_id: str, source: str) -> SourceCoverage:
    """Build a report entry for a source skipped via --resume.

    Without this, a resumed run's report would simply omit already-done
    sources -- making it impossible for the ML reviewer to tell "already
    complete" apart from "never ran at all." Pulls the last known counts
    from batch_ingestion_progress instead of just a bare placeholder note.

    skipped_resume (not gaps) carries the "this is a resumed skip" signal
    -- gaps is reserved for genuine coverage problems, and an ML reviewer
    filtering for non-empty gaps shouldn't see a perfectly healthy resumed
    source flagged as if something went wrong.
    """
    row = (
        session.query(BatchIngestionProgress)
        .filter_by(pilot_event_id=event_id, source=source, status="success")
        .one_or_none()
    )

    if row is None:
        # Shouldn't normally happen -- is_done() was derived from this same
        # table -- but if EventProgress and the DB ever disagree, that's a
        # real anomaly worth flagging, unlike a normal resumed skip.
        return SourceCoverage(
            source=source,
            gaps=["expected a stored success row for a resumed source, found none"],
            skipped_resume=True,
        )

    rows_fetched = row.rows_fetched or 0
    rows_written = row.rows_written or 0

    return SourceCoverage(
        source=source,
        rows_fetched=rows_fetched,
        rows_written=rows_written,
        duplicates_skipped=rows_fetched - rows_written,
        skipped_resume=True,
    )


def write_coverage_report(reports: list[CoverageReport], out_path: Path) -> None:
    """Write the combined data-quality report for ML-owner review.

    Acceptance criteria requires gaps to be flagged, not hidden — so this
    intentionally writes every event's report, including ones with zero
    rows for a source, rather than skipping empty results.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump([r.to_dict() for r in reports], f, indent=2, default=str)

    print(f"Coverage report written to {out_path}")


# ---------------------------------------------------------------------------
# Per-event ingestion
# ---------------------------------------------------------------------------

def ingest_event(event: PilotEvent, resume: bool = False) -> CoverageReport:
    """Run all sources for a single pilot event.

    Commits per-source rather than once at the end: if AirNow fails after
    FIRMS already succeeded, FIRMS's rows stay committed and marked done,
    so a --resume rerun only retries what actually failed instead of
    re-pulling everything (and re-burning API quota) for the whole event.
    """

    progress = load_progress(event.event_id) if resume else EventProgress(event.event_id)
    report = CoverageReport(event_id=event.event_id)
    session = SessionLocal()

    try:
        # --- FIRMS (fire detections) ---
        if progress.is_done("firms"):
            report.record(load_existing_coverage(session, event.event_id, "firms"))
        else:
            mark_progress(session, event.event_id, "firms", status="running")
            try:
                coverage = SourceCoverage(source="firms")
                all_records: list[dict] = []

                # One source at a time (VIIRS-SNPP, MODIS, etc. are separate
                # API sources) x one date-chunk at a time (5-day cap).
                for fire_source in event.firms_products:
                    for chunk_start, chunk_days in split_date_range(
                        event.start_date, event.end_date
                    ):
                        chunk_records = with_retries(
                            lambda fs=fire_source, cs=chunk_start, cd=chunk_days: get_firms_records(
                                map_key=settings.firms_map_key,
                                source=fs,
                                bbox=event.bbox,
                                day_range=cd,
                                start_date=cs,
                            ),
                            label=f"firms:{event.event_id}:{fire_source}:{chunk_start}",
                        )
                        all_records.extend(chunk_records)

                coverage.rows_fetched = len(all_records)
                if coverage.rows_fetched == 0:
                    coverage.gaps.append("no rows returned")

                coverage.rows_written = insert_fire_detections(session, all_records)
                coverage.duplicates_skipped = coverage.rows_fetched - coverage.rows_written
                session.commit()

                mark_progress(
                    session, event.event_id, "firms", status="success",
                    rows_fetched=coverage.rows_fetched,
                    rows_written=coverage.rows_written,
                )
                report.record(coverage)
                progress.mark_done("firms")

            except Exception as exc:
                session.rollback()
                mark_progress(
                    session, event.event_id, "firms", status="failed", error=str(exc)
                )
                raise

        # --- AirNow (PM2.5, regulatory) ---
        if progress.is_done("airnow"):
            report.record(load_existing_coverage(session, event.event_id, "airnow"))
        else:
            mark_progress(session, event.event_id, "airnow", status="running")
            try:
                coverage = SourceCoverage(source="airnow")

                # NOTE: requesting the full event date range in one call.
                # fetch_airnow_rows doesn't document a range cap the way
                # FIRMS does -- if this errors or times out on a long event
                # (Aug Complex is ~87 days), this will need chunking too,
                # e.g. one call per day. Confirm empirically on a long
                # event before assuming this scales as-is.
                records = with_retries(
                    lambda: get_airnow_pm25_records(
                        api_key=settings.airnow_api_key,
                        bbox=event.bbox,
                        start_date=event.start_date,
                        start_hour="00",
                        end_date=event.end_date,
                        end_hour="23",
                    ),
                    label=f"airnow:{event.event_id}",
                )

                coverage.rows_fetched = len(records)
                if coverage.rows_fetched == 0:
                    coverage.gaps.append("no rows returned")

                coverage.rows_written = insert_airnow_observations(session, records)
                coverage.duplicates_skipped = coverage.rows_fetched - coverage.rows_written
                session.commit()

                mark_progress(
                    session, event.event_id, "airnow", status="success",
                    rows_fetched=coverage.rows_fetched,
                    rows_written=coverage.rows_written,
                )
                report.record(coverage)
                progress.mark_done("airnow")

            except Exception as exc:
                session.rollback()
                mark_progress(
                    session, event.event_id, "airnow", status="failed", error=str(exc)
                )
                raise

        # --- NCEI (historical weather) — connector not built yet ---
        if not progress.is_done("ncei"):
            report.record(SourceCoverage(
                source="ncei",
                gaps=["NCEI connector not yet implemented"],
            ))

        # --- PurpleAir (PM2.5, low-cost, Barkjohn-corrected) — not built yet ---
        if not progress.is_done("purpleair"):
            report.record(SourceCoverage(
                source="purpleair",
                gaps=["PurpleAir connector + Barkjohn correction not yet implemented"],
            ))

    finally:
        session.close()

    return report


def ingest_event_with_retries(
    event: PilotEvent, resume: bool, max_attempts: int = 3
) -> CoverageReport:
    """Retry ingest_event, forcing resume=True on any attempt after the first.

    The generic with_retries() can't be used here: it can't change the
    arguments passed to fn() between attempts. That matters because of
    the per-source commits in ingest_event() -- if AirNow fails after
    FIRMS already succeeded, FIRMS's row is durably committed. Retrying
    the first attempt's own resume=False choice would re-fetch FIRMS
    anyway, burning API quota for data that's already saved. The first
    attempt still honors whatever the user actually asked for; only the
    retries force resume=True, since by then real progress may exist.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return ingest_event(event, resume=resume if attempt == 1 else True)
        except Exception as exc:
            if attempt == max_attempts:
                raise
            delay = 2.0 * (2 ** (attempt - 1))
            print(
                f"[event:{event.event_id}] attempt {attempt}/{max_attempts} failed "
                f"({exc!r}); retrying in {delay:.1f}s (forcing --resume from here on)"
            )
            time.sleep(delay)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="DATA-03 historical batch ingestion")
    parser.add_argument("--event", help="Single pilot event ID to ingest")
    parser.add_argument("--all", action="store_true", help="Ingest all pilot events")
    parser.add_argument("--resume", action="store_true", help="Skip sources already completed")
    parser.add_argument(
        "--report-out",
        default="data/coverage_report.json",
        help="Where to write the combined coverage report",
    )
    parser.add_argument(
        "--events-config",
        default=str(PILOT_EVENTS_PATH),
        help="Pilot event config to load (defaults to docs/pilot_events.json)",
    )
    args = parser.parse_args()

    if not args.event and not args.all:
        parser.error("Specify --event <id> or --all")

    events = load_pilot_events(Path(args.events_config))

    if args.event:
        events = [e for e in events if e.event_id == args.event]
        if not events:
            parser.error(f"No pilot event found with id '{args.event}'")

    reports = []
    for event in events:
        print(f"--- Ingesting {event.event_id} ({event.name}) ---")
        report = ingest_event_with_retries(event, resume=args.resume)
        reports.append(report)

    write_coverage_report(reports, Path(args.report_out))


if __name__ == "__main__":
    main()

"""DATA-03: Historical batch ingestion CLI for pilot events.

Generalizes the DATA-02 POC into a batch job that loops over every pilot
event, pulls fire/weather/PM2.5 data for its date range + downwind region,
and writes to the cleaned historical store.

Usage (run from backend/):
    python -m ingestion.batch.batch_ingest --event kincade_2026
    python -m ingestion.batch.batch_ingest --all
    python -m ingestion.batch.batch_ingest --event kincade_2026 --resume

NOTE: --report-out defaults to "data/coverage_report.json", which is
relative to the current working directory -- resolves to
backend/data/coverage_report.json only when run from backend/, as the
usage above and the test instructions do. Pass an absolute path if
running from elsewhere.
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

from ingestion.batch.firms_extent import expand_bbox_km, lead_start_date
from ingestion.connectors.firms import get_firms_records
from ingestion.connectors.airnow import get_airnow_pm25_records, padded_airnow_windows
from ingestion.connectors.airnow_time_offsets import max_abs_shift_hours
from ingestion.connectors.ncei import get_ncei_weather_records
from ingestion.connectors.purpleair import get_purpleair_pm25_records

from ingestion.db import (
    SessionLocal,
    insert_airnow_observations,
    insert_fire_detections,
    insert_weather_observations,
)
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
    # Derived, never read from the config: FIRMS pulls the bbox grown by
    # FIRMS_MARGIN_KM over [firms_start_date, end_date] (firms_extent.py).
    firms_bbox: str = field(init=False)
    firms_start_date: str = field(init=False)

    def __post_init__(self) -> None:
        self.firms_bbox = expand_bbox_km(self.bbox)
        self.firms_start_date = lead_start_date(self.start_date)


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

    # Derived fields (init=False) are not config fields: a config that sets
    # them gets the same unrecognized-field warning as any other.
    known_fields = {f.name for f in dataclasses.fields(PilotEvent) if f.init}
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
    event_error: str | None = None  # set when the whole event failed after all retries

    def record(self, coverage: SourceCoverage) -> None:
        self.sources[coverage.source] = coverage

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_error": self.event_error,
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


def count_nulls(records: list[dict], fields: tuple[str, ...]) -> dict[str, int]:
    """Count missing values per field, for the report's null_counts."""
    return {name: sum(record.get(name) is None for record in records) for name in fields}


WEATHER_FIELDS = (
    "wind_speed_ms",
    "wind_dir_deg",
    "temp_c",
    "rh_pct",
    "pressure_hpa",
    "precip_1h_mm",
)

# FIRMS fields where a null is a real gap. confidence_level is NOT NULL in
# fire_detections, so it is always 0 in a report that got written -- a null
# fails the insert and shows up as the source's error instead.
FIRMS_FIELDS = (
    "confidence_level",
    "frp_mw",
    "scan_km",
    "track_km",
    "daynight",
)


def count_firms_nulls(records: list[dict]) -> dict[str, int]:
    """null_counts for FIRMS detections.

    bright_t31_k is counted over MODIS rows only: VIIRS has no T31 band, so
    it is null on every VIIRS row by design.
    """
    counts = count_nulls(records, FIRMS_FIELDS)
    modis = [r for r in records if str(r.get("satellite", "")).startswith("MODIS")]
    counts["bright_t31_k"] = sum(r.get("bright_t31_k") is None for r in modis)
    return counts


def event_window(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """UTC [start, end) covering an inclusive start/end date range."""
    window_start = datetime.combine(
        date.fromisoformat(start_date), datetime.min.time(), timezone.utc
    )
    window_end = datetime.combine(
        date.fromisoformat(end_date) + timedelta(days=1),
        datetime.min.time(),
        timezone.utc,
    )
    return window_start, window_end


def count_missing_station_hours(
    records: list[dict], start_date: str, end_date: str
) -> int:
    """Hours in the window that each reporting AirNow site has no reading for.

    This is AirNow's real null rate: every stored column that can be null is
    null by design (PurpleAir-only QA fields, no elevation from /aq/data/),
    while gaps show up as missing hours -- either never sent, or dropped as a
    -999 sentinel. Sites with no rows at all in the window aren't counted,
    since the response doesn't say they exist.
    """
    window_start, window_end = event_window(start_date, end_date)
    window_hours = int((window_end - window_start).total_seconds() // 3600)

    hours_by_site: dict[str, set[datetime]] = {}
    for record in records:
        valid_at = record["observation"]["valid_at"]
        if window_start <= valid_at < window_end:
            hours_by_site.setdefault(record["monitor"]["external_id"], set()).add(valid_at)

    return sum(window_hours - len(hours) for hours in hours_by_site.values())


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


# Every source ingest_event() runs, in order. Matches the source CHECK on
# batch_ingestion_progress.
SOURCES = ("firms", "airnow", "ncei", "purpleair")


def load_event_report(event_id: str, event_error: str) -> CoverageReport:
    """Rebuild a failed event's report from batch_ingestion_progress.

    Sources commit independently, so when an event fails after all retries,
    the sources that succeeded before the failure are safely in the DB. The
    report should say so -- not show an empty "sources" block. Successful
    sources reuse load_existing_coverage(); anything else gets a gap with
    its real state.

    Counts for successful sources come from the progress row, so
    null_counts are not available for them here.
    """
    report = CoverageReport(event_id=event_id, event_error=event_error)

    session = SessionLocal()
    try:
        rows = {
            row.source: row
            for row in session.query(BatchIngestionProgress)
            .filter_by(pilot_event_id=event_id)
            .all()
        }

        for source in SOURCES:
            row = rows.get(source)

            if row is None:
                gap = "not attempted (event failed before this source ran)"
            elif row.status == "success":
                report.record(load_existing_coverage(session, event_id, source))
                continue
            elif row.status == "failed":
                gap = f"failed: {row.error or 'no error recorded'}"
            else:
                gap = f"did not finish (status {row.status!r})"

            report.record(SourceCoverage(source=source, gaps=[gap]))
    finally:
        session.close()

    return report


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
                # FIRMS alone uses the widened box and the lead window, so
                # fire features near the bbox edge and on day one have their
                # fires; the other sources keep the tight bbox and window.
                for fire_source in event.firms_products:
                    for chunk_start, chunk_days in split_date_range(
                        event.firms_start_date, event.end_date
                    ):
                        chunk_records = with_retries(
                            lambda fs=fire_source, cs=chunk_start, cd=chunk_days: get_firms_records(
                                map_key=settings.firms_map_key,
                                source=fs,
                                bbox=event.firms_bbox,
                                day_range=cd,
                                start_date=cs,
                            ),
                            label=f"firms:{event.event_id}:{fire_source}:{chunk_start}",
                        )
                        all_records.extend(chunk_records)

                coverage.rows_fetched = len(all_records)
                coverage.null_counts = count_firms_nulls(all_records)
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

                # AirNow's /aq/data/ rejects queries over a per-request
                # record cap (HTTP 400, ~8.3k-8.7k rows; measured 2026-10-02
                # -- a 21-day Sacramento-box query failed, 20 days passed),
                # and slow responses approach the 30s client timeout on
                # multi-week windows. So chunk like FIRMS does, and retry
                # per chunk so a late failure doesn't re-pull earlier ones.
                # The connector also bisects a chunk on its own if a dense
                # bbox still trips the cap.
                #
                # The window is padded by the largest configured time
                # correction, so a site whose labels are shifted still
                # supplies the event's first and last true hours. Rows
                # whose corrected valid_at lands outside the event are
                # dropped, which leaves unshifted sites exactly as before.
                records: list[dict] = []
                for start_date, start_hour, end_date, end_hour in padded_airnow_windows(
                    event.start_date, event.end_date, max_abs_shift_hours()
                ):
                    chunk_records = with_retries(
                        lambda sd=start_date, sh=start_hour, ed=end_date, eh=end_hour: (
                            get_airnow_pm25_records(
                                api_key=settings.airnow_api_key,
                                bbox=event.bbox,
                                start_date=sd,
                                start_hour=sh,
                                end_date=ed,
                                end_hour=eh,
                            )
                        ),
                        label=f"airnow:{event.event_id}:{start_date}T{start_hour}",
                    )
                    records.extend(chunk_records)

                window_start, window_end = event_window(event.start_date, event.end_date)
                records = [
                    r for r in records
                    if window_start <= r["observation"]["valid_at"] < window_end
                ]

                coverage.rows_fetched = len(records)
                coverage.null_counts = {
                    "pm25_missing_station_hours": count_missing_station_hours(
                        records, event.start_date, event.end_date
                    )
                }
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

        # --- NCEI (historical weather) ---
        if progress.is_done("ncei"):
            report.record(load_existing_coverage(session, event.event_id, "ncei"))
        else:
            mark_progress(session, event.event_id, "ncei", status="running")
            try:
                coverage = SourceCoverage(source="ncei")

                # The connector chunks by month and retries each request
                # itself; with_retries here covers a failure mid-event.
                records = with_retries(
                    lambda: get_ncei_weather_records(
                        bbox=event.bbox,
                        start_date=event.start_date,
                        end_date=event.end_date,
                    ),
                    label=f"ncei:{event.event_id}",
                )

                coverage.rows_fetched = len(records)
                coverage.null_counts = count_nulls(records, WEATHER_FIELDS)
                if coverage.rows_fetched == 0:
                    coverage.gaps.append("no rows returned (no ISD stations in bbox?)")

                suspect = sum(r["qc_flag"] != "V" for r in records)
                if suspect:
                    coverage.gaps.append(
                        f"{suspect} rows had a value dropped by NCEI quality control"
                    )

                coverage.rows_written = insert_weather_observations(session, records)
                coverage.duplicates_skipped = coverage.rows_fetched - coverage.rows_written
                session.commit()

                mark_progress(
                    session, event.event_id, "ncei", status="success",
                    rows_fetched=coverage.rows_fetched,
                    rows_written=coverage.rows_written,
                )
                report.record(coverage)
                progress.mark_done("ncei")

            except Exception as exc:
                session.rollback()
                mark_progress(
                    session, event.event_id, "ncei", status="failed", error=str(exc)
                )
                raise

        # --- PurpleAir (PM2.5, low-cost, Barkjohn-corrected) ---
        if progress.is_done("purpleair"):
            report.record(load_existing_coverage(session, event.event_id, "purpleair"))
        else:
            mark_progress(session, event.event_id, "purpleair", status="running")
            try:
                coverage = SourceCoverage(source="purpleair")

                # PurpleAir bills points per sensor-hour. A cap keeps a
                # large event from draining the balance; 0 means no cap.
                max_sensors = settings.purpleair_max_sensors or None

                records = with_retries(
                    lambda: get_purpleair_pm25_records(
                        api_key=settings.purpleair_api_key,
                        bbox=event.bbox,
                        start_date=event.start_date,
                        end_date=event.end_date,
                        max_sensors=max_sensors,
                    ),
                    label=f"purpleair:{event.event_id}",
                )

                observations = [r["observation"] for r in records]
                coverage.rows_fetched = len(records)
                coverage.null_counts = count_nulls(
                    observations, ("pm25_cf1_a", "pm25_cf1_b", "rh_pct")
                )

                if coverage.rows_fetched == 0:
                    coverage.gaps.append("no rows returned")

                # Raw (no humidity) or failed-QA rows are stored for audit
                # but are never usable as training labels -- say how many.
                not_label = sum(
                    o["correction"] != "purpleair_barkjohn" or o["qa_flag"] != "ok"
                    for o in observations
                )
                if not_label:
                    coverage.gaps.append(
                        f"{not_label} rows not label-eligible "
                        "(uncorrected or failed A/B channel check)"
                    )

                if max_sensors is not None:
                    sensors = {r["monitor"]["external_id"] for r in records}
                    if len(sensors) >= max_sensors:
                        coverage.gaps.append(
                            f"capped at PURPLEAIR_MAX_SENSORS={max_sensors}; "
                            "more sensors may exist in bbox"
                        )

                coverage.rows_written = insert_airnow_observations(session, records)
                coverage.duplicates_skipped = coverage.rows_fetched - coverage.rows_written
                session.commit()

                mark_progress(
                    session, event.event_id, "purpleair", status="success",
                    rows_fetched=coverage.rows_fetched,
                    rows_written=coverage.rows_written,
                )
                report.record(coverage)
                progress.mark_done("purpleair")

            except Exception as exc:
                session.rollback()
                mark_progress(
                    session, event.event_id, "purpleair", status="failed", error=str(exc)
                )
                raise

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
    had_failure = False

    for event in events:
        print(f"--- Ingesting {event.event_id} ({event.name}) ---")
        try:
            report = ingest_event_with_retries(event, resume=args.resume)
        except Exception as exc:
            # A persistently-failing event (bad bbox, prolonged outage, the
            # known MODIS confidence bug, etc.) must not take down the
            # whole --all batch. Record it and move on, so events that
            # already succeeded earlier in this same run still make it
            # into the report instead of the process just dying with no
            # output at all.
            had_failure = True
            print(f"[event:{event.event_id}] failed after all retries: {exc!r}")
            try:
                report = load_event_report(event.event_id, repr(exc))
            except Exception as report_exc:
                # e.g. the DB itself is what failed -- still write a report.
                print(
                    f"[event:{event.event_id}] could not read progress for the "
                    f"report: {report_exc!r}"
                )
                report = CoverageReport(event_id=event.event_id, event_error=repr(exc))
        reports.append(report)

    write_coverage_report(reports, Path(args.report_out))

    if had_failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

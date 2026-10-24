"""Run one live job without a Celery worker (cron, GitHub Actions, by hand).

Run from backend/:
    python -m ingestion.live firms|airnow|nws|purpleair
    python -m ingestion.live retention [--delete]
    python -m ingestion.live freshness
    LIVE_INGEST_SMOKE=1 python -m ingestion.live smoke [source ...]

smoke calls the live APIs and normalizes the rows but writes nothing; it prints
counts only. Keys come from the environment / backend/.env and are never printed.
Exit code 1 when the job failed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from datetime import timedelta

JOBS = {
    "airnow": "ingestion.live.airnow",
    "firms": "ingestion.live.firms",
    "nws": "ingestion.live.nws",
    "purpleair": "ingestion.live.purpleair",
}

# Short windows: a smoke run checks the path, not the backfill.
SMOKE_HOURS = 3
SMOKE_NWS_STATIONS = ("KSAC", "KRDD", "KLAX")


def smoke(sources: list[str]) -> int:
    """Fetch + normalize each source live, no DB writes; print counts only."""
    from ingestion.live import airnow, firms, nws, purpleair
    from ingestion.live.common import client_scope, safe_error, utc_now

    now = utc_now()
    start = now - timedelta(hours=SMOKE_HOURS)
    failed = False
    for source in sources:
        try:
            if source == "firms":
                with client_scope(None, firms.RETRY_STATUSES) as http:
                    fetched, records = firms.fetch_records(http, start, now)
            elif source == "airnow":
                with client_scope(None, airnow.RETRY_STATUSES) as http:
                    fetched, records = airnow.fetch_records(http, start, now)
            elif source == "purpleair":
                with client_scope(None, purpleair.RETRY_STATUSES) as http:
                    fetched, records = purpleair.fetch_records(http, now)
            else:
                headers = nws.nws_headers(nws.user_agent())
                fetched, records = 0, []
                with client_scope(None, nws.RETRY_STATUSES) as http:
                    for station in SMOKE_NWS_STATIONS:
                        n, recs = nws.station_records(
                            http, station, start, now, headers
                        )
                        fetched, records = fetched + n, records + recs
            print(f"{source}: fetched={fetched} normalized={len(records)}")
        except Exception as exc:
            failed = True
            print(f"{source}: FAILED {safe_error(exc, 200)}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingestion.live",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command", choices=[*sorted(JOBS), "retention", "freshness", "smoke"]
    )
    parser.add_argument(
        "sources", nargs="*", help="smoke only: sources to check (default all)"
    )
    parser.add_argument(
        "--delete", action="store_true", help="retention: delete, not dry run"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.command == "smoke":
        from ingestion.live.common import env_flag

        if not env_flag("LIVE_INGEST_SMOKE"):
            print("smoke calls the live APIs; set LIVE_INGEST_SMOKE=1 to run it.")
            return 2
        unknown = set(args.sources) - set(JOBS)
        if unknown:
            parser.error(f"unknown source(s): {', '.join(sorted(unknown))}")
        return smoke(args.sources or sorted(JOBS))

    if args.command == "freshness":
        from ingestion.db import SessionLocal
        from ingestion.live.freshness import source_freshness

        with SessionLocal() as session:
            print(json.dumps(source_freshness(session), indent=2))
        return 0

    if args.command == "retention":
        from ingestion.live import retention

        result = retention.run(delete=True if args.delete else None)
    else:
        result = importlib.import_module(JOBS[args.command]).run()
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())

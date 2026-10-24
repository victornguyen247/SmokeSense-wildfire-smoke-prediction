"""Run one live job without a Celery worker (cron, GitHub Actions, by hand).

Run from backend/:
    python -m ingestion.live firms|airnow|nws|purpleair
    python -m ingestion.live retention [--delete]
    python -m ingestion.live freshness
    LIVE_INGEST_SMOKE=1 python -m ingestion.live smoke [source ...]

Keys come from the environment / backend/.env and are never printed. Exit code 1
when the job failed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys

JOBS = {
    "airnow": "ingestion.live.airnow",
    "firms": "ingestion.live.firms",
    "nws": "ingestion.live.nws",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingestion.live",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", choices=sorted(JOBS))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    result = importlib.import_module(JOBS[args.command]).run()
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())

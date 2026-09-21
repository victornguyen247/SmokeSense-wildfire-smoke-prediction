"""Credential check for NASA FIRMS active-fire detections.

Fetches VIIRS S-NPP near-real-time detections over the contiguous US for the
last day and prints a sample.

Run (from backend/):
    python -m ingestion.connectors.validate_firms

Docs: https://firms.modaps.eosdis.nasa.gov/api/area/
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import httpx

try:
    from ._common import (
        TIMEOUT,
        ValidationError,
        mask,
        preview_rows,
        report_response,
        require_env,
        require_ok,
        run,
    )
except ImportError:  # also runnable as a plain file path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import (  # type: ignore[no-redef]
        TIMEOUT,
        ValidationError,
        mask,
        preview_rows,
        report_response,
        require_env,
        require_ok,
        run,
    )

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# FIRMS documents the country endpoint as unreliable for large countries
# (USA included) because the polygon is too complex and the query times out,
# so we use the area endpoint with a CONUS bounding box instead.
# Order is west,south,east,north.
CONUS_BBOX = "-125,24,-66.5,49.5"

SOURCE = "VIIRS_SNPP_NRT"

# day_range counts back from the current UTC day, and range 1 means "today (UTC)
# so far" — routinely empty in the early UTC hours, which reads like a broken key.
# 2 covers today plus yesterday and reliably returns detections.
DAY_RANGE = 2

HOW_TO_GET = "https://firms.modaps.eosdis.nasa.gov/api/map_key/ (free, instant)"


def check() -> None:
    map_key = require_env("FIRMS_MAP_KEY", how_to_get=HOW_TO_GET)

    url = f"{BASE_URL}/{map_key}/{SOURCE}/{CONUS_BBOX}/{DAY_RANGE}"
    print(f"MAP_KEY     : {mask(map_key)}")
    print(f"Request     : {BASE_URL}/<MAP_KEY>/{SOURCE}/{CONUS_BBOX}/{DAY_RANGE}\n")

    response = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    report_response(response)
    require_ok(response, secret=map_key)

    body = response.text.strip()

    # FIRMS answers an unusable MAP_KEY with HTTP 200 and a plain-text message,
    # so a 2xx alone does not prove the key works — inspect the body.
    if not body.lower().startswith("country_id,latitude") and "," not in body.split("\n")[0]:
        raise ValidationError(
            f"FIRMS returned a message instead of CSV: {body[:300]}\n"
            "  An invalid or over-quota MAP_KEY shows up here rather than as an HTTP error."
        )
    if "invalid" in body[:200].lower() and "map_key" in body[:200].lower():
        raise ValidationError(
            f"FIRMS rejected the MAP_KEY: {body[:300]}\n  Request a key at {HOW_TO_GET}"
        )

    rows = list(csv.DictReader(io.StringIO(body)))
    print(f"\nDetections  : {len(rows):,} (VIIRS S-NPP NRT, CONUS, last {DAY_RANGE} UTC days)")

    if rows:
        print(f"Columns     : {', '.join(rows[0].keys())}")
    print("\nSample detections:")
    preview_rows(rows)

    if not rows:
        print(
            "\n[note] Zero detections is a valid response — the key worked and the "
            "satellite simply logged no CONUS fires in this window."
        )


if __name__ == "__main__":
    raise SystemExit(run(check, source="NASA FIRMS"))

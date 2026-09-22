"""Credential check for the PurpleAir API (low-cost air-quality sensors).

Fetches a small bounding box of outdoor sensors near Sacramento, CA.

Scope note: this proves connectivity only. PurpleAir readings over-report
during heavy wildfire smoke and MUST have the EPA (Barkjohn) correction
applied before they are used as training labels — that lands in the real
connector, not here. Never train on the raw values printed below.

PurpleAir bills per field per sensor, so this asks for the fewest fields
that still make the response readable.

Run (from backend/):
    python -m ingestion.connectors.validate_purpleair

Docs: https://api.purpleair.com/
"""

from __future__ import annotations

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

BASE_URL = "https://api.purpleair.com/v1"

FIELDS = "name,latitude,longitude,pm2.5_60minute,humidity,last_seen"

# Small box around Sacramento, CA. nw = north-west corner, se = south-east.
BBOX = {"nwlng": -121.70, "nwlat": 38.70, "selng": -121.20, "selat": 38.40}

LOCATION_TYPE = 0  # 0 = outside, 1 = inside. Only outdoor sensors are useful to us.
MAX_AGE = 3600  # seconds; skip sensors that have not reported within the hour.

HOW_TO_GET = "https://develop.purpleair.com/ — request a READ key (keys are read or write)"


def check() -> None:
    api_key = require_env("PURPLEAIR_API_KEY", how_to_get=HOW_TO_GET)

    url = f"{BASE_URL}/sensors"
    params = {
        "fields": FIELDS,
        "location_type": LOCATION_TYPE,
        "max_age": MAX_AGE,
        **BBOX,
    }
    headers = {"X-API-Key": api_key}

    print(f"API key     : {mask(api_key)}")
    print(f"Request     : GET {url}")
    print(f"Fields      : {FIELDS}")
    print(f"Bounding box: {BBOX} (outdoor sensors, seen in last {MAX_AGE}s)\n")

    response = httpx.get(url, params=params, headers=headers, timeout=TIMEOUT)
    report_response(response)

    # A write-only key authenticates fine but cannot read sensor data.
    if response.status_code == 403:
        raise ValidationError(
            "PurpleAir returned 403. The key is probably a WRITE key — the sensors "
            f"endpoint needs a READ key.\n  Request one at {HOW_TO_GET}\n"
            f"  Response body: {response.text[:300]}"
        )
    require_ok(response, secret=api_key)

    payload = response.json()
    fields = payload.get("fields", [])
    data = payload.get("data", [])

    if not fields:
        raise ValidationError(f"PurpleAir response carried no 'fields' key: {payload}")

    print(f"\nAPI version : {payload.get('api_version')}")
    print(f"Sensors     : {len(data)} in the sample box")
    print(f"Fields      : {', '.join(fields)}")

    # PurpleAir returns positional rows plus a field list; zip them for readability.
    print("\nSample sensors:")
    preview_rows([dict(zip(fields, row)) for row in data])

    if not data:
        print(
            "\n[note] Zero sensors means the key worked but nothing in this box "
            "reported recently. Widen the box or raise max_age."
        )

    print(
        "\n[reminder] Raw PurpleAir PM2.5 over-reports in wildfire smoke. "
        "Apply the EPA/Barkjohn correction before using these as labels."
    )


if __name__ == "__main__":
    raise SystemExit(run(check, source="PurpleAir"))

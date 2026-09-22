"""Credential check for the EPA AirNow API (regulatory air quality).

Fetches current observations for a sample zip code.

IMPORTANT — this targets AirNow's 2026 web services. The legacy endpoint
(/aq/observation/zipCode/current/) is retired on 2026-09-30; its replacement
is /aq/observation/current/ziplatLong, used below. The replacement differs in
three ways that will bite whoever writes the real connector:

  * it takes `api_key` (lowercase) where the legacy service took `API_KEY`;
  * it dropped `distance` — each reporting area now has a fixed search radius;
  * the response is camelCase (`parameterName`, `nowcastAQI`, `aqiCategoryName`)
    and no longer carries Latitude/Longitude, so monitor coordinates have to
    come from elsewhere (reporting-area metadata or the monitoring-site service).

Run (from backend/):
    python -m ingestion.connectors.validate_airnow

Docs: https://docs.airnowapi.org/webservices
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

# https, always: the API 301-redirects http and the key would make its first hop in plaintext.
BASE_URL = "https://www.airnowapi.org/aq"
OBSERVATION_PATH = "/observation/current/ziplatLong"

SAMPLE_ZIP = "95814"  # Sacramento, CA

HOW_TO_GET = "https://docs.airnowapi.org/account/request/ (free, email confirmation)"


def check() -> None:
    api_key = require_env("AIRNOW_API_KEY", how_to_get=HOW_TO_GET)

    url = f"{BASE_URL}{OBSERVATION_PATH}"
    params = {"zipCode": SAMPLE_ZIP, "format": "application/json", "api_key": api_key}

    print(f"API key     : {mask(api_key)}")
    print(f"Request     : {url}?zipCode={SAMPLE_ZIP}&format=application/json&api_key=<KEY>\n")

    response = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True)
    report_response(response)
    require_ok(response, secret=api_key)

    payload = response.json()

    # AirNow reports problems as {"WebServiceError":[{"Message": "..."}]} and
    # serves that under HTTP 200, so a 2xx does not by itself mean success.
    if isinstance(payload, dict) and "WebServiceError" in payload:
        messages = "; ".join(
            err.get("Message", "") for err in payload.get("WebServiceError", [])
        )
        raise ValidationError(
            f"AirNow returned an error envelope under HTTP 200: {messages}\n"
            "  An invalid key, an unregistered key, or an hourly-limit breach all land here."
        )

    if not isinstance(payload, list):
        raise ValidationError(f"Unexpected AirNow response shape: {type(payload).__name__}")

    print(f"\nObservations: {len(payload)} (one row per pollutant) for zip {SAMPLE_ZIP}")
    if payload:
        area = payload[0]
        print(f"Reporting area: {area.get('reportingAreaName')} ({area.get('reportingAgency')})")
        print(
            "Observed at : "
            f"{area.get('dateObserved', '').strip()} {area.get('hourObserved')} "
            f"{area.get('localTimeZone')} (hour label marks the END of the period)"
        )

    print("\nSample observations:")
    preview_rows(
        [
            {
                "parameterName": row.get("parameterName"),
                "nowcastAQI": row.get("nowcastAQI"),
                "aqiCategoryName": row.get("aqiCategoryName"),
                "siteName": row.get("siteName"),
                "lookupBehavior": row.get("lookupBehavior"),
            }
            for row in payload
        ],
        limit=5,
    )

    if payload and all(row.get("parameterName") is None for row in payload):
        raise ValidationError(
            "Rows came back but none carried 'parameterName'. AirNow likely changed "
            "the response schema again — re-check https://docs.airnowapi.org/webservices"
        )

    if not payload:
        print(
            "\n[note] An empty list means the key worked but no monitor reported for "
            "this area in the current hour. Observations post 10-30 minutes past the hour."
        )


if __name__ == "__main__":
    raise SystemExit(run(check, source="EPA AirNow"))

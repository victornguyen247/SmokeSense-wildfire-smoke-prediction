"""Credential check for the NOAA/NWS weather API.

The NWS API takes no key, but it rejects requests without a descriptive
User-Agent — that header is the credential we are validating here.

A point forecast takes two calls: /points/{lat},{lon} resolves the coordinate
to a forecast grid, and the URL it hands back returns the actual forecast.

Run (from backend/):
    python -m ingestion.connectors.validate_nws

Docs: https://www.weather.gov/documentation/services-web-api
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

BASE_URL = "https://api.weather.gov"

# Sacramento, CA — inside a fire-prone region we actually care about.
SAMPLE_LAT = 38.5816
SAMPLE_LON = -121.4944

# The example deliberately avoids example.com: _common._PLACEHOLDER_MARKERS
# rejects that domain, so suggesting it here would loop the user on the error.
HOW_TO_GET = (
    "no registration; set any descriptive identifier with a real contact, "
    "e.g. 'SmokeSense (dev@smokesense.local)' — example.com is rejected as a placeholder"
)


def check() -> None:
    user_agent = require_env("NWS_USER_AGENT", how_to_get=HOW_TO_GET)

    if "@" not in user_agent:
        raise ValidationError(
            f"NWS_USER_AGENT ({user_agent!r}) has no contact address.\n"
            "  NWS asks for an app identifier plus a way to reach you, so they can "
            "warn you before blocking traffic.\n"
            "  Example: SmokeSense (dev@smokesense.local)"
        )

    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    # Masked like every other credential: this value carries a personal email.
    print(f"User-Agent  : {mask(user_agent)}")
    print(f"Request     : {BASE_URL}/points/{SAMPLE_LAT},{SAMPLE_LON}\n")

    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        points = client.get(f"{BASE_URL}/points/{SAMPLE_LAT},{SAMPLE_LON}")
        report_response(points)
        require_ok(points)

        props = points.json().get("properties", {})
        grid = f"{props.get('gridId')}/{props.get('gridX')},{props.get('gridY')}"
        location = props.get("relativeLocation", {}).get("properties", {})

        print(f"\nResolved to : {location.get('city')}, {location.get('state')}")
        print(f"Forecast grid: {grid}")

        forecast_url = props.get("forecast")
        if not forecast_url:
            raise ValidationError(
                "The /points response carried no 'forecast' URL — the coordinate may "
                "be outside NWS coverage (the API is US-only)."
            )

        print(f"\nRequest     : {forecast_url}\n")
        forecast = client.get(forecast_url)
        report_response(forecast)
        require_ok(forecast)

    periods = forecast.json().get("properties", {}).get("periods", [])
    print(f"\nPeriods     : {len(periods)} (12-hour periods, ~7 days)")
    print("\nSample forecast periods:")
    preview_rows(
        [
            {
                "name": p.get("name"),
                "startTime": p.get("startTime"),
                "temperature": f"{p.get('temperature')} {p.get('temperatureUnit')}",
                "windSpeed": p.get("windSpeed"),
                "windDirection": p.get("windDirection"),
                "shortForecast": p.get("shortForecast"),
            }
            for p in periods
        ]
    )


if __name__ == "__main__":
    raise SystemExit(run(check, source="NOAA / NWS"))

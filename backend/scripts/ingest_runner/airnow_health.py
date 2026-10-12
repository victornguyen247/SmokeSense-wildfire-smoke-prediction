"""Wait for AirNow /aq/data/ to answer a tiny 1-hour query with HTTP 200.

Probes every PROBE_EVERY_S seconds, at most MAX_PROBES times; prints only
timestamps and status codes. Exit 0 when healthy, 1 when it gives up.
"""
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ingestion.connectors._common import load_env  # noqa: E402
from ingestion.connectors.airnow import AIRNOW_BASE_URL  # noqa: E402

PROBE_EVERY_S = 300
MAX_PROBES = 36  # 3 hours


def main():
    load_env()
    params = {"startDate": "2020-09-10T20", "endDate": "2020-09-10T20", "parameters": "PM25",
              "BBOX": "-121.5,38.5,-121.4,38.6", "dataType": "B", "format": "application/json",
              "verbose": "1", "monitorType": "0", "includerawconcentrations": "1",
              "API_KEY": os.environ["AIRNOW_API_KEY"]}
    for _ in range(MAX_PROBES):
        try:
            code = httpx.get(f"{AIRNOW_BASE_URL}/data/", params=params, timeout=30).status_code
        except Exception as exc:  # timeouts during an outage; never print the URL
            code = type(exc).__name__
        print(time.strftime("%H:%M:%S"), "airnow", code, flush=True)
        if code == 200:
            return 0
        time.sleep(PROBE_EVERY_S)
    return 1


if __name__ == "__main__":
    sys.exit(main())

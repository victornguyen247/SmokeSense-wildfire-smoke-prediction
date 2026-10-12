"""Run batch_ingest.main() with the given arguments, counting HTTP requests per host.

Prints "REQUESTS {host: count}" at exit for run_events.py to collect.
"""
import atexit
import json
import sys
from collections import Counter
from urllib.parse import urlsplit

import httpx

counts = Counter()
_send = httpx.Client.send


def send(self, request, *args, **kwargs):
    counts[urlsplit(str(request.url)).hostname] += 1
    return _send(self, request, *args, **kwargs)


httpx.Client.send = send
atexit.register(lambda: print("REQUESTS " + json.dumps(counts), flush=True))

from ingestion.batch import batch_ingest  # noqa: E402

sys.argv = ["batch_ingest", *sys.argv[1:]]
batch_ingest.main()

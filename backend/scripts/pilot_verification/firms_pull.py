"""Pull FIRMS _SP rows for a bbox + window, cached on disk. Never prints the key."""
import json
import os
import sys
import time
import hashlib
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/
from paths import OFFLINE, CacheMiss, cache_dir
from ingestion.connectors._common import load_env, redact
from ingestion.connectors.firms import fetch_firms_rows

load_env()
KEY = os.environ.get("FIRMS_MAP_KEY")  # only needed on a cache miss
CACHE = cache_dir("firms_cache")


def chunks(start, end, n=5):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out = []
    while s <= e:
        L = min(n, (e - s).days + 1)
        out.append((s.isoformat(), L))
        s += timedelta(days=L)
    return out


def _one(product, bbox, cstart, L):
    h = hashlib.md5(f"{product}|{bbox}|{cstart}|{L}".encode()).hexdigest()
    f = CACHE / f"{h}.json"
    if f.exists():
        return json.loads(f.read_text())
    if OFFLINE:
        raise CacheMiss(f"firms_cache/{f.name} ({product} {bbox} {cstart}+{L})")
    if not KEY:
        raise RuntimeError("FIRMS_MAP_KEY is not set")
    for attempt in range(20):
        try:
            rows = fetch_firms_rows(KEY, source=product, bbox=bbox, day_range=L, start_date=cstart)
            f.write_text(json.dumps(rows))
            return rows
        except Exception as exc:  # redact: httpx errors can carry the URL
            msg = redact(str(exc), KEY)
            print(f"  [firms] {product} {cstart}+{L} attempt {attempt+1}: {type(exc).__name__}: {msg[:200]}", file=sys.stderr)
            # The key allows 5,000 transactions per 10 minutes; wait the window out.
            time.sleep(60 if "transaction limit" in msg else 3 * (attempt + 1))
    raise RuntimeError(f"FIRMS {product} {cstart}+{L} failed after retries")


def pull(product, bbox, start, end):
    """All rows for product in bbox over [start, end] inclusive, restricted to that date range."""
    with ThreadPoolExecutor(2) as ex:
        parts = list(ex.map(lambda c: _one(product, bbox, c[0], c[1]), chunks(start, end)))
    rows = [r for p in parts for r in p if start <= r["acq_date"] <= end]
    for r in rows:
        r["_product"] = product
    return rows

"""Shared locations and run mode for the pilot verification scripts.

PILOT_VERIFY_CACHE   cache root holding firms_cache/, airnow_cache/, airdata/
                     (default: .cache/ in this folder, gitignored)
PILOT_VERIFY_OFFLINE "1" = fail on any cache miss instead of calling an API
Generated outputs go to out/ in this folder (gitignored).
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CACHE = Path(os.environ.get("PILOT_VERIFY_CACHE") or HERE / ".cache")
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
OFFLINE = os.environ.get("PILOT_VERIFY_OFFLINE") == "1"


class CacheMiss(RuntimeError):
    """Raised in offline mode when a request is not in the cache."""


def cache_dir(name):
    d = CACHE / name
    if not OFFLINE:
        d.mkdir(parents=True, exist_ok=True)
    return d

"""Shared locations and run mode for the pilot verification scripts.

PILOT_VERIFY_CACHE   cache root holding firms_cache/, airnow_cache/, airdata/
                     (default: .cache/ in this folder, gitignored)
PILOT_VERIFY_OFFLINE "1" = fail on any cache miss instead of calling an API
PILOT_EVENTS         event set: unset = events.py (the PR #26 set),
                     "pr21" = events_pr21.py (PR #21's set)
PILOT_VERIFY_OUT     output folder in this folder (default: out/, gitignored)
"""
import importlib
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CACHE = Path(os.environ.get("PILOT_VERIFY_CACHE") or HERE / ".cache")
OUT = HERE / (os.environ.get("PILOT_VERIFY_OUT") or "out")
OUT.mkdir(exist_ok=True)
OFFLINE = os.environ.get("PILOT_VERIFY_OFFLINE") == "1"

EVENT_SETS = {"": "events", "pr21": "events_pr21"}
EVENT_SET = os.environ.get("PILOT_EVENTS", "")
if EVENT_SET not in EVENT_SETS:
    raise SystemExit(f"PILOT_EVENTS must be one of {sorted(EVENT_SETS)}, got {EVENT_SET!r}")
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
EVENTS_MODULE = importlib.import_module(EVENT_SETS[EVENT_SET])
EVENTS = EVENTS_MODULE.EVENTS
products_for = EVENTS_MODULE.products_for


class CacheMiss(RuntimeError):
    """Raised in offline mode when a request is not in the cache."""


def cache_dir(name):
    d = CACHE / name
    if not OFFLINE:
        d.mkdir(parents=True, exist_ok=True)
    return d

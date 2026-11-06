"""In-process cache of responses for the current forecast cycle.

A forecast cycle never changes once written, so a response stays valid until a newer
cycle exists. Entries are keyed by cycle, and the first request for a new cycle drops
the old ones, so nothing has to be invalidated by hand. Each API process has its own
cache; staging runs one uvicorn worker.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from threading import Lock
from typing import Any

# A California-wide grid is about 15,000 small dicts and bboxes are unbounded, so this
# has to stay small.
MAX_ENTRIES = 32


class CycleCache:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self.max_entries = max_entries
        self._cycle: Hashable = None
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = Lock()

    def get_or_build(self, cycle: Hashable, key: Hashable, build: Callable[[], Any]) -> Any:
        """The cached value of key for cycle, building it on a miss.

        Callers must not change the value they get back: it is shared between requests.
        Two concurrent misses both build; the result is the same, and no lock is held
        during a database query.
        """
        with self._lock:
            if cycle != self._cycle:
                self._cycle = cycle
                self._entries.clear()
            elif key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
        value = build()
        with self._lock:
            if cycle == self._cycle:
                self._entries[key] = value
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
        return value

"""HTTP client plumbing shared by the connectors."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx


@contextmanager
def client_or_new(client: httpx.Client | None, **kwargs) -> Iterator[httpx.Client]:
    """The caller's client (left open), or a new httpx.Client(**kwargs) closed on exit.

    Lets a caller supply its own (e.g. retrying) client while a plain call still
    opens one for the request.
    """
    if client is not None:
        yield client
        return
    with httpx.Client(**kwargs) as own:
        yield own

"""Shared helpers for the data-source validation scripts.

Each `validate_*.py` in this package makes one live call to its provider and
prints what came back. They answer a single question — *do our credentials and
network path actually work?* — before any real connector is built on top.

Everything shared lives here so all four scripts fail the same way, with the
same message, when a key is missing or still holds a placeholder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# connectors -> ingestion -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BACKEND_DIR / ".env"

# Network calls are validation-only: fail fast rather than hang a student's terminal.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Substrings that mean "copied from .env.example but never filled in".
_PLACEHOLDER_MARKERS = (
    "your-email@example.com",
    "contact@example.com",
    "example.com",
    "changeme",
    "replace-me",
    "<your",
)


class ValidationError(RuntimeError):
    """Raised for any condition that makes the check fail, with a fixable message."""


def load_env() -> None:
    """Load backend/.env into the process environment.

    Missing file is a warning, not a fatal error: in Docker the same variables
    arrive through `env_file`/`environment` instead.
    """
    if ENV_PATH.is_file():
        load_dotenv(dotenv_path=ENV_PATH, override=False)
    else:
        print(
            f"[warn] No {ENV_PATH} found. Falling back to the process environment.\n"
            f"       Locally: cp {BACKEND_DIR / '.env.example'} {ENV_PATH} and fill it in.",
            file=sys.stderr,
        )


def require_env(name: str, *, how_to_get: str) -> str:
    """Return an env var, or fail loudly with instructions for obtaining it."""
    raw = os.getenv(name)

    if raw is None:
        raise ValidationError(
            f"{name} is not set.\n"
            f"  Add it to {ENV_PATH} — the variable is listed (blank) in .env.example.\n"
            f"  Where to get it: {how_to_get}"
        )

    value = raw.strip()
    if not value:
        raise ValidationError(
            f"{name} is set but empty.\n"
            f"  Fill in a real value in {ENV_PATH}.\n"
            f"  Where to get it: {how_to_get}"
        )

    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise ValidationError(
            f"{name} still looks like the .env.example placeholder ({value!r}).\n"
            f"  Replace it with a real value in {ENV_PATH}.\n"
            f"  Where to get it: {how_to_get}"
        )

    return value


def mask(secret: str) -> str:
    """Render a credential safe to print, so logs and screenshots never leak it."""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def redact(text: str, secret: str) -> str:
    """Strip a secret out of text that is about to be printed (e.g. a URL in an error)."""
    return text.replace(secret, mask(secret)) if secret else text


def report_response(response: httpx.Response) -> None:
    """Print the HTTP outcome in a consistent shape across all four scripts."""
    print(f"HTTP status : {response.status_code} {response.reason_phrase}")
    print(f"Content-Type: {response.headers.get('content-type', '(none)')}")
    print(f"Elapsed     : {response.elapsed.total_seconds():.2f}s")
    print(f"Body size   : {len(response.content):,} bytes")


def require_ok(response: httpx.Response, *, secret: str = "") -> None:
    """Fail loudly on a non-2xx, showing the body so the provider's message is visible."""
    if response.is_success:
        return

    body = redact(response.text[:600].strip(), secret)
    hint = ""
    if response.status_code in (401, 403):
        hint = "\n  This status usually means the API key is wrong, expired, or not yet activated."
    elif response.status_code == 429:
        hint = "\n  Rate limited. Wait and retry; see docs/data-sources.md for each source's limits."

    raise ValidationError(
        f"Request failed with HTTP {response.status_code} {response.reason_phrase}."
        f"{hint}\n  Response body: {body or '(empty)'}"
    )


def preview_rows(rows: list[dict[str, Any]], limit: int = 3) -> None:
    """Print the first few records as aligned key/value blocks."""
    if not rows:
        print("  (no records returned)")
        return

    for i, row in enumerate(rows[:limit], start=1):
        print(f"  [{i}]")
        width = max(len(str(k)) for k in row)
        for key, value in row.items():
            print(f"      {str(key).ljust(width)} : {value}")


def run(check, *, source: str) -> int:
    """Wrap a check function with banner, error handling, and an exit code.

    Returns 0 on success and 1 on failure so these can be chained in CI or a
    shell loop later.
    """
    banner = f" {source} credential check "
    print(banner.center(72, "="))
    load_env()

    try:
        check()
    except ValidationError as exc:
        print(f"\nFAIL: {exc}", file=sys.stderr)
        print("=" * 72)
        return 1
    except httpx.HTTPError as exc:
        print(
            f"\nFAIL: Could not reach {source}: {type(exc).__name__}: {exc}\n"
            "  Check your network connection and whether the provider is up.",
            file=sys.stderr,
        )
        print("=" * 72)
        return 1

    print(f"\nOK: {source} credentials work and the endpoint returned usable data.")
    print("=" * 72)
    return 0

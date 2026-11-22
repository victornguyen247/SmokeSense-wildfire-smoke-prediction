"""Alert subscription tokens (docs/alerts.md section 3).

Both tokens are 32 bytes, base64url without padding (43 characters). Only their SHA-256
hashes are stored, and the raw tokens are never logged.

- Confirm token: random, made at subscribe time and only needed in that request's
  confirmation email.
- Unsubscribe token: HMAC-SHA256 of the subscription id, so the alert job can rebuild the
  link days later without storing it. Changing the secret breaks every link already sent.

The two are looked up by different hash columns, so a confirm token can never
unsubscribe and an unsubscribe token can never confirm.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

TOKEN_BYTES = 32
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")  # 32 bytes, base64url, no padding; fullmatch

# Domain separation: the same secret could sign other things later.
UNSUBSCRIBE_PURPOSE = b"unsubscribe:"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def token_hash(token: str) -> str:
    """SHA-256 hex of a raw token: what the database stores and looks up."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_confirm_token() -> tuple[str, str]:
    """A fresh random confirm token and its hash, as (token, hash)."""
    token = _b64url(secrets.token_bytes(TOKEN_BYTES))
    return token, token_hash(token)


def unsubscribe_token(secret: str, subscription_id: str) -> str:
    """The unsubscribe token for a subscription; the same id always gives the same token."""
    digest = hmac.new(secret.encode(), UNSUBSCRIBE_PURPOSE + subscription_id.encode(), hashlib.sha256)
    return _b64url(digest.digest())


def is_well_formed(token: str) -> bool:
    """True for 43 base64url characters. Anything else is 404 invalid_token, not 400."""
    return TOKEN_PATTERN.fullmatch(token) is not None

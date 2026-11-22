"""Alert subscriptions: subscribe, confirm, unsubscribe, clean-up (docs/alerts.md section 2).

Never logs an email address or a token, and no error message repeats either one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.ids import uuid7
from app.core.tokens import is_well_formed, new_confirm_token, token_hash, unsubscribe_token
from app.repositories.alerts import AlertRepository, PendingSignup, SavedPending
from app.repositories.base import Body
from app.schemas.alerts import AlertSubscribeRequest
from app.services import email
from app.services.scope_service import check_point

logger = logging.getLogger(__name__)

CONFIRM_TTL = timedelta(hours=48)
MAX_CONFIRMATION_SENDS = 3  # per email, per SEND_WINDOW (decision D1)
SEND_WINDOW = timedelta(hours=24)



def invalid_token() -> ApiError:
    return ApiError(404, "invalid_token", "This link is not valid.")


def token_expired() -> ApiError:
    return ApiError(410, "token_expired", "This confirmation link has expired. Sign up again from the map.")


def utc_now() -> datetime:
    return datetime.now(UTC)


def subscribe(repo: AlertRepository, request: AlertSubscribeRequest) -> Body:
    """The same 202 for every valid request, so it never reveals who has subscribed."""
    point = request.location()
    check_point(point)
    secret = get_settings().alerts_token_secret
    now = utc_now()
    token, confirm_hash = new_confirm_token()
    new_id = uuid7()
    saved = repo.save_pending(
        PendingSignup(
            email=request.email,
            point=point,
            confirm_hash=confirm_hash,
            now=now,
            expires_at=now + CONFIRM_TTL,
            send_limit=MAX_CONFIRMATION_SENDS,
            send_window=SEND_WINDOW,
            new_id=new_id,
            new_unsubscribe_hash=token_hash(unsubscribe_token(secret, new_id)),
        )
    )
    if saved is not None:
        _send_confirmation(repo, request.email, saved, token, now)
    return {"status": "pending_confirmation"}


def _send_confirmation(repo: AlertRepository, to: str, saved: SavedPending, token: str, now: datetime) -> None:
    """Sent after the row is committed; a failure is recorded, not retried (alerts.md §2)."""
    settings = get_settings()
    unsubscribe = unsubscribe_token(settings.alerts_token_secret, saved.subscription_id)
    try:
        email.send(
            email.render_confirmation(
                to=to,
                place=saved.place,
                confirm_url=f"{settings.alerts_frontend_base_url}/alerts/confirm#token={token}",
                unsubscribe_url=one_click_unsubscribe_url(unsubscribe),
                expires_at=now + CONFIRM_TTL,
            )
        )
    except email.EmailSendError as exc:
        # The message never holds the recipient (EmailSendError's contract).
        logger.warning("confirmation email not sent: %s", exc)
        repo.record_confirmation(saved.subscription_id, sent=False, error=str(exc)[:200], now=now)
        return
    repo.record_confirmation(saved.subscription_id, sent=True, error=None, now=now)


def one_click_unsubscribe_url(token: str) -> str:
    """The RFC 8058 List-Unsubscribe URL: the only link with the token in its query string."""
    return f"{get_settings().alerts_api_base_url}/api/v1/alerts/unsubscribe?token={token}"


def confirm(repo: AlertRepository, token: str) -> Body:
    if not is_well_formed(token):
        raise invalid_token()
    outcome = repo.confirm(token_hash(token), utc_now())
    if outcome == "unknown":
        raise invalid_token()
    if outcome == "expired":
        raise token_expired()
    return {"status": outcome}


def unsubscribe(repo: AlertRepository, token: str) -> Body:
    """Idempotent: a well-formed token whose row is already gone gets the same 200."""
    if not is_well_formed(token):
        raise invalid_token()
    repo.unsubscribe(token_hash(token))
    return {"status": "unsubscribed"}


def purge_expired_pending(repo: AlertRepository, now: datetime | None = None) -> int:
    """Delete pending sign-ups whose link expired (decision D2; the alert job, OPS-06, calls it)."""
    return repo.purge_expired_pending(now or utc_now())

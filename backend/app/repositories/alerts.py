"""Data access for the alert endpoints (API-05, docs/alerts.md sections 2 and 3).

The rules (rate limit, token checks, emails) are in app/services/alert_service.py; each
method here is one transaction. Raw tokens never reach this module, only their hashes,
and nothing here logs an email address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.alerts import AlertNotification, AlertSubscription
from app.repositories.database import resolve_location
from app.schemas.query import PointQuery

ConfirmOutcome = Literal["confirmed", "already_confirmed", "expired", "unknown"]


@dataclass(frozen=True)
class PendingSignup:
    """A valid subscribe request, with everything the service already decided."""

    email: str  # trimmed and lower-cased
    point: PointQuery
    confirm_hash: str
    now: datetime
    expires_at: datetime
    send_limit: int  # confirmation emails per email per send_window
    send_window: timedelta
    # Used only when a new row is inserted; an updated pending row keeps its own id.
    new_id: str
    new_unsubscribe_hash: str


@dataclass(frozen=True)
class SavedPending:
    """The pending row a confirmation email is now owed for."""

    subscription_id: str
    place: str  # "ZIP 95928" or "39.73, -121.84" (the stored, rounded point)


class AlertRepository(Protocol):
    def save_pending(self, signup: PendingSignup) -> SavedPending | None:
        """Insert or update the email's pending row; None when no email should be sent."""
        ...

    def record_confirmation(self, subscription_id: str, *, sent: bool, error: str | None, now: datetime) -> None: ...

    def confirm(self, confirm_hash: str, now: datetime) -> ConfirmOutcome: ...

    def unsubscribe(self, unsubscribe_hash: str) -> None: ...

    def purge_expired_pending(self, now: datetime) -> int: ...


def round2(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


class DatabaseAlertRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def save_pending(self, signup: PendingSignup) -> SavedPending | None:
        point = signup.point
        try:
            with self.sessions() as session, session.begin():
                # The cell comes from the exact point; only the rounded point is stored.
                cell_id = resolve_location(session, point).cell_id
                if point.zip is not None:
                    zip_code, lat, lon, place = point.zip, None, None, f"ZIP {point.zip}"
                else:
                    zip_code, lat, lon = None, round2(point.lat), round2(point.lon)
                    place = f"{lat}, {lon}"

                rows = session.scalars(
                    select(AlertSubscription)
                    .where(AlertSubscription.email == signup.email)
                    .with_for_update()
                ).all()
                active = next((r for r in rows if r.status == "active"), None)
                pending = next((r for r in rows if r.status == "pending"), None)

                # D3: already active for this cell, so there is nothing to confirm.
                if active is not None and active.forecast_point_id == cell_id:
                    return None

                if pending is None:
                    pending = AlertSubscription(
                        id=signup.new_id,
                        email=signup.email,
                        status="pending",
                        unsubscribe_token_hash=signup.new_unsubscribe_hash,
                        confirmation_sends_24h=0,
                    )
                    session.add(pending)
                else:
                    last = pending.last_confirmation_sent_at
                    if last is None or signup.now - last >= signup.send_window:
                        pending.confirmation_sends_24h = 0
                    elif pending.confirmation_sends_24h >= signup.send_limit:
                        return None  # rate-limited: the row and its last link stay valid

                pending.forecast_point_id = cell_id
                pending.zip, pending.query_lat, pending.query_lon = zip_code, lat, lon
                pending.confirm_token_hash = signup.confirm_hash
                pending.confirm_expires_at = signup.expires_at
                pending.confirmation_sends_24h += 1
                pending.last_confirmation_sent_at = signup.now
                return SavedPending(pending.id, place)
        except IntegrityError:
            # A concurrent request for the same email inserted its pending row first; that
            # request sends the email, this one changes nothing (still 202).
            return None

    def record_confirmation(self, subscription_id: str, *, sent: bool, error: str | None, now: datetime) -> None:
        try:
            with self.sessions() as session, session.begin():
                session.add(
                    AlertNotification(
                        subscription_id=subscription_id,
                        kind="confirmation",
                        status="sent" if sent else "failed",
                        attempts=1,
                        sent_at=now if sent else None,
                        error=error,
                    )
                )
        except IntegrityError:
            pass  # unsubscribed in the meantime: nothing left to record against

    def confirm(self, confirm_hash: str, now: datetime) -> ConfirmOutcome:
        with self.sessions() as session, session.begin():
            row = session.scalars(
                select(AlertSubscription)
                .where(AlertSubscription.confirm_token_hash == confirm_hash)
                .with_for_update()
            ).first()
            if row is None:
                return "unknown"
            if row.status == "active":
                return "already_confirmed"
            if row.confirm_expires_at <= now:
                return "expired"
            # Replace the email's previous subscription (its notifications cascade). The
            # delete runs first, so the one-active-per-email index never sees two rows.
            session.execute(
                delete(AlertSubscription).where(
                    AlertSubscription.email == row.email,
                    AlertSubscription.status == "active",
                    AlertSubscription.id != row.id,
                )
            )
            row.status = "active"
            row.confirmed_at = now
            return "confirmed"

    def unsubscribe(self, unsubscribe_hash: str) -> None:
        with self.sessions() as session, session.begin():
            session.execute(
                delete(AlertSubscription).where(AlertSubscription.unsubscribe_token_hash == unsubscribe_hash)
            )

    def purge_expired_pending(self, now: datetime) -> int:
        with self.sessions() as session, session.begin():
            result = session.execute(
                delete(AlertSubscription).where(
                    AlertSubscription.status == "pending",
                    AlertSubscription.confirm_expires_at < now,
                )
            )
            return result.rowcount


class FixtureAlertRepository:
    """Mock mode: no database, so nothing is stored and no email is sent.

    Every well-formed token confirms and unsubscribes, which is enough for the frontend
    and the contract tests (docs/api/fixtures/alerts_*.json).
    """

    def save_pending(self, signup: PendingSignup) -> SavedPending | None:
        return None

    def record_confirmation(self, subscription_id: str, *, sent: bool, error: str | None, now: datetime) -> None:
        return None

    def confirm(self, confirm_hash: str, now: datetime) -> ConfirmOutcome:
        return "confirmed"

    def unsubscribe(self, unsubscribe_hash: str) -> None:
        return None

    def purge_expired_pending(self, now: datetime) -> int:
        return 0

"""Email alerts: alert_subscriptions, alert_notifications (API-04; docs/alerts.md §3)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import uuid7
from app.models.base import Base, one_of
from app.models.predictions import Alert
from app.models.reference import ForecastPoint
from app.models.values import (
    NOTIFICATION_KINDS,
    NOTIFICATION_STATUSES,
    SUBSCRIPTION_STATUSES,
)


class AlertSubscription(Base):
    """One email subscription to one grid cell. Personal data: hard-deleted on unsubscribe.

    At most one pending and one active row per email; confirming a pending row deletes
    the active one in the same transaction. Raw tokens are never stored, only SHA-256 hex.
    """

    __tablename__ = "alert_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email))", name="ck_alert_subscriptions_email"
        ),
        CheckConstraint("zip ~ '^[0-9]{5}$'", name="ck_alert_subscriptions_zip"),
        one_of("status", SUBSCRIPTION_STATUSES, name="ck_alert_subscriptions_status"),
        CheckConstraint(
            "confirmation_sends_24h >= 0",
            name="ck_alert_subscriptions_confirmation_sends",
        ),
        # Exactly one location form: a ZIP or a (lat, lon) pair.
        CheckConstraint(
            "(zip IS NOT NULL) <> (query_lat IS NOT NULL)",
            name="ck_alert_subscriptions_location",
        ),
        CheckConstraint(
            "(query_lat IS NULL) = (query_lon IS NULL)",
            name="ck_alert_subscriptions_lat_lon",
        ),
        CheckConstraint(
            "(status = 'active') = (confirmed_at IS NOT NULL)",
            name="ck_alert_subscriptions_confirmed",
        ),
        UniqueConstraint(
            "confirm_token_hash", name="uq_alert_subscriptions_confirm_token"
        ),
        UniqueConstraint(
            "unsubscribe_token_hash", name="uq_alert_subscriptions_unsubscribe_token"
        ),
        Index(
            "one_pending_per_email",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "one_active_per_email",
            "email",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_alert_subscriptions_active_point",
            "forecast_point_id",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str]  # trimmed + lower-cased; never logged in full
    forecast_point_id: Mapped[str] = mapped_column(ForeignKey("forecast_points.id"))
    zip: Mapped[str | None]
    # Rounded to 2 decimals (~1 km); the exact point is never stored.
    query_lat: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    query_lon: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str]
    confirm_token_hash: Mapped[str]
    unsubscribe_token_hash: Mapped[str]
    confirm_expires_at: Mapped[datetime]  # last confirmation email + 48 h
    confirmation_sends_24h: Mapped[int] = mapped_column(
        SmallInteger, server_default="0"
    )
    last_confirmation_sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None]

    forecast_point: Mapped["ForecastPoint"] = relationship()


class AlertNotification(Base):
    """One email attempt for a subscription: a confirmation, or one alert per episode."""

    __tablename__ = "alert_notifications"
    __table_args__ = (
        one_of("kind", NOTIFICATION_KINDS, name="ck_alert_notifications_kind"),
        one_of("status", NOTIFICATION_STATUSES, name="ck_alert_notifications_status"),
        CheckConstraint(
            "attempts BETWEEN 1 AND 3", name="ck_alert_notifications_attempts"
        ),
        CheckConstraint(
            "(kind = 'confirmation') = (alert_id IS NULL)",
            name="ck_alert_notifications_alert_id",
        ),
        CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name="ck_alert_notifications_sent_at",
        ),
        CheckConstraint(
            "char_length(error) <= 200", name="ck_alert_notifications_error_length"
        ),
        # At most one email per subscription per episode; NULL alert_id rows don't collide.
        UniqueConstraint(
            "subscription_id",
            "alert_id",
            name="uq_alert_notifications_subscription_alert",
        ),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=uuid7)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("alert_subscriptions.id", ondelete="CASCADE")
    )
    alert_id: Mapped[str | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE")
    )
    kind: Mapped[str]
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None]  # short reason, never an address, token or URL
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    subscription: Mapped["AlertSubscription"] = relationship()
    alert: Mapped["Alert | None"] = relationship()


Index(
    "ix_alert_notifications_subscription_sent",
    AlertNotification.subscription_id,
    AlertNotification.sent_at.desc(),
)

"""alert_subscriptions and alert_notifications: email alerts (API-04, #110)

Tables exactly as docs/schema.md; rules in docs/alerts.md §3. At most one pending and
one active subscription per email (two partial unique indexes, not one across both).
Raw tokens are never stored, only their SHA-256 hashes. Deleting a subscription or an
alert episode deletes its notifications.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_subscriptions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "forecast_point_id",
            sa.Text(),
            sa.ForeignKey("forecast_points.id"),
            nullable=False,
        ),
        sa.Column("zip", sa.Text()),
        sa.Column("query_lat", sa.Numeric(4, 2)),
        sa.Column("query_lon", sa.Numeric(5, 2)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("confirm_token_hash", sa.Text(), nullable=False),
        sa.Column("unsubscribe_token_hash", sa.Text(), nullable=False),
        sa.Column("confirm_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "confirmation_sends_24h",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_confirmation_sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "email = lower(btrim(email))", name="ck_alert_subscriptions_email"
        ),
        sa.CheckConstraint("zip ~ '^[0-9]{5}$'", name="ck_alert_subscriptions_zip"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'unsubscribed')",
            name="ck_alert_subscriptions_status",
        ),
        sa.CheckConstraint(
            "confirmation_sends_24h >= 0",
            name="ck_alert_subscriptions_confirmation_sends",
        ),
        sa.CheckConstraint(
            "(zip IS NOT NULL) <> (query_lat IS NOT NULL)",
            name="ck_alert_subscriptions_location",
        ),
        sa.CheckConstraint(
            "(query_lat IS NULL) = (query_lon IS NULL)",
            name="ck_alert_subscriptions_lat_lon",
        ),
        sa.CheckConstraint(
            "(status = 'active') = (confirmed_at IS NOT NULL)",
            name="ck_alert_subscriptions_confirmed",
        ),
        sa.UniqueConstraint(
            "confirm_token_hash", name="uq_alert_subscriptions_confirm_token"
        ),
        sa.UniqueConstraint(
            "unsubscribe_token_hash", name="uq_alert_subscriptions_unsubscribe_token"
        ),
    )
    op.create_index(
        "one_pending_per_email",
        "alert_subscriptions",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "one_active_per_email",
        "alert_subscriptions",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_alert_subscriptions_active_point",
        "alert_subscriptions",
        ["forecast_point_id"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "alert_notifications",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "subscription_id",
            sa.Text(),
            sa.ForeignKey("alert_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alert_id", sa.Text(), sa.ForeignKey("alerts.id", ondelete="CASCADE")
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('confirmation', 'alert')", name="ck_alert_notifications_kind"
        ),
        sa.CheckConstraint(
            "status IN ('sent', 'failed')", name="ck_alert_notifications_status"
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 1 AND 3", name="ck_alert_notifications_attempts"
        ),
        sa.CheckConstraint(
            "(kind = 'confirmation') = (alert_id IS NULL)",
            name="ck_alert_notifications_alert_id",
        ),
        sa.UniqueConstraint(
            "subscription_id",
            "alert_id",
            name="uq_alert_notifications_subscription_alert",
        ),
    )
    op.create_index(
        "ix_alert_notifications_subscription_sent",
        "alert_notifications",
        ["subscription_id", sa.text("sent_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_alert_notifications_subscription_sent", table_name="alert_notifications"
    )
    op.drop_table("alert_notifications")
    op.drop_index(
        "ix_alert_subscriptions_active_point", table_name="alert_subscriptions"
    )
    op.drop_index("one_active_per_email", table_name="alert_subscriptions")
    op.drop_index("one_pending_per_email", table_name="alert_subscriptions")
    op.drop_table("alert_subscriptions")

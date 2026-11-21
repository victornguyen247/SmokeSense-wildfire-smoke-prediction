"""alert_subscriptions / alert_notifications constraints (API-04, docs/alerts.md §3).

Runs on the *_test database (TEST_DATABASE_URL, see conftest.py); skipped without it.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.core.ids import uuid7
from app.models import Alert, AlertNotification, AlertSubscription, ForecastPoint
from conftest import BACKEND, alembic_env

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
_tokens = count()


def _alembic(engine, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=alembic_env(engine.url),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def point_id(live_db) -> str:
    with live_db() as s:
        p = ForecastPoint(
            kind="grid_cell",
            label="test cell",
            geom="SRID=4326;POINT(-121.5 38.5)",
            timezone="America/Los_Angeles",
        )
        s.add(p)
        s.commit()
        return p.id


def _subscription(point_id: str, **kw) -> AlertSubscription:
    n = next(_tokens)
    row = {
        "id": uuid7(),
        "email": "someone@example.com",
        "forecast_point_id": point_id,
        "zip": "95814",
        "status": "pending",
        "confirm_token_hash": f"confirm-{n}",
        "unsubscribe_token_hash": f"unsubscribe-{n}",
        "confirm_expires_at": NOW + timedelta(hours=48),
    }
    row.update(kw)
    return AlertSubscription(**row)


def _insert(live_db, *rows) -> None:
    with live_db() as s:
        s.add_all(rows)
        s.commit()


def test_upgrade_downgrade_upgrade(live_db_engine):
    _alembic(live_db_engine, "downgrade", "0008")
    tables = inspect(live_db_engine).get_table_names()
    assert "alert_subscriptions" not in tables
    assert "alert_notifications" not in tables

    _alembic(live_db_engine, "upgrade", "head")
    tables = inspect(live_db_engine).get_table_names()
    assert {"alert_subscriptions", "alert_notifications"} <= set(tables)


def test_valid_zip_and_point_subscriptions(live_db, point_id):
    _insert(
        live_db,
        _subscription(point_id),
        _subscription(
            point_id,
            email="other@example.com",
            zip=None,
            query_lat=Decimal("38.58"),
            query_lon=Decimal("-121.49"),
        ),
    )


def test_email_not_lower_cased_is_rejected(live_db, point_id):
    with pytest.raises(IntegrityError, match="ck_alert_subscriptions_email"):
        _insert(live_db, _subscription(point_id, email="Someone@Example.com"))


def test_zip_and_point_together_are_rejected(live_db, point_id):
    sub = _subscription(
        point_id, query_lat=Decimal("38.58"), query_lon=Decimal("-121.49")
    )
    with pytest.raises(IntegrityError, match="ck_alert_subscriptions_location"):
        _insert(live_db, sub)


def test_second_pending_row_for_an_email_is_rejected(live_db, point_id):
    _insert(live_db, _subscription(point_id))
    with pytest.raises(IntegrityError, match="one_pending_per_email"):
        _insert(live_db, _subscription(point_id))


def test_one_pending_and_one_active_row_per_email_are_allowed(live_db, point_id):
    _insert(
        live_db,
        _subscription(point_id, status="active", confirmed_at=NOW),
        _subscription(point_id),
    )


def _alert(point_id: str) -> Alert:
    return Alert(
        id=uuid7(),
        forecast_point_id=point_id,
        severity="unhealthy",
        status="open",
        first_triggered_at=NOW,
        last_seen_at=NOW,
        pm25_threshold=55.5,
        aqi_table_version="epa-2024",
        model_key="test",
    )


def test_second_notification_for_the_same_episode_is_rejected(live_db, point_id):
    sub = _subscription(point_id, status="active", confirmed_at=NOW)
    alert = _alert(point_id)
    sub_id, alert_id = sub.id, alert.id
    _insert(live_db, sub, alert)

    def notification() -> AlertNotification:
        return AlertNotification(
            subscription_id=sub_id,
            alert_id=alert_id,
            kind="alert",
            status="sent",
            sent_at=NOW,
        )

    _insert(live_db, notification())
    with pytest.raises(
        IntegrityError, match="uq_alert_notifications_subscription_alert"
    ):
        _insert(live_db, notification())


def test_deleting_a_subscription_deletes_its_notifications(live_db, point_id):
    sub = _subscription(point_id)
    sub_id = sub.id
    _insert(live_db, sub)
    _insert(
        live_db,
        AlertNotification(
            subscription_id=sub_id, kind="confirmation", status="sent", sent_at=NOW
        ),
        AlertNotification(subscription_id=sub_id, kind="confirmation", status="failed"),
    )

    with live_db() as s:
        s.delete(s.get(AlertSubscription, sub_id))
        s.commit()
        assert s.scalars(select(AlertNotification)).all() == []

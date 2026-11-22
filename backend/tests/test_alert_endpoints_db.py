"""DatabaseAlertRepository and cell.active_alert on PostGIS (API-05, docs/alerts.md §2).

Runs on the *_test database (TEST_DATABASE_URL, see conftest.py); skipped without it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from sqlalchemy import select, text

from app.core.errors import ApiError
from app.core.ids import uuid7
from app.models import Alert, AlertNotification, AlertSubscription
from app.repositories.alerts import DatabaseAlertRepository, PendingSignup
from app.repositories.database import OPEN_ALERT, active_alert
from app.schemas.query import PointQuery

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
EMAIL = "someone@example.com"
_n = count()

# Two 0.2-degree cells: A around Chico (ZIP 95928 points at it), B just east of it.
CELLS = {"cell-a": (-121.95, 39.6), "cell-b": (-121.75, 39.6)}


@pytest.fixture
def repo(live_db) -> DatabaseAlertRepository:
    with live_db() as s:
        for cell_id, (lon, lat) in CELLS.items():
            s.execute(
                text("""
                    INSERT INTO forecast_points (id, kind, label, geom, cell_geom, timezone, active)
                    VALUES (:id, 'grid_cell', :id,
                            ST_Point(:lon + 0.1, :lat + 0.1, 4326)::geography,
                            ST_MakeEnvelope(:lon, :lat, :lon + 0.2, :lat + 0.2, 4326)::geography,
                            'America/Los_Angeles', true)
                """),
                {"id": cell_id, "lon": lon, "lat": lat},
            )
        s.execute(
            text("""
                INSERT INTO zip_codes (zcta, state, geom, area_km2, forecast_point_id)
                VALUES ('95928', 'CA', ST_Point(-121.84, 39.72, 4326)::geography, 90.5, 'cell-a'),
                       ('95929', 'CA', ST_Point(-121.84, 39.72, 4326)::geography, 1.0, NULL)
            """)
        )
        s.commit()
    return DatabaseAlertRepository(live_db)


def signup(now: datetime = NOW, email: str = EMAIL, **point) -> PendingSignup:
    n = next(_n)
    return PendingSignup(
        email=email,
        point=PointQuery(**(point or {"zip": "95928"})),
        confirm_hash=f"confirm-{n}",
        now=now,
        expires_at=now + timedelta(hours=48),
        send_limit=3,
        send_window=timedelta(hours=24),
        new_id=uuid7(),
        new_unsubscribe_hash=f"unsubscribe-{n}",
    )


def rows(repo, email: str = EMAIL) -> list[AlertSubscription]:
    with repo.sessions() as s:
        return list(s.scalars(select(AlertSubscription).where(AlertSubscription.email == email)))


def activate(repo, **point) -> AlertSubscription:
    first = signup(**point)
    repo.save_pending(first)
    assert repo.confirm(first.confirm_hash, NOW) == "confirmed"
    [row] = [r for r in rows(repo) if r.status == "active"]
    return row


# --- subscribe ---


def test_a_new_signup_inserts_one_pending_row(repo):
    s = signup()
    saved = repo.save_pending(s)
    assert saved is not None and saved.place == "ZIP 95928"
    [row] = rows(repo)
    assert (row.id, row.status, row.forecast_point_id, row.zip) == (s.new_id, "pending", "cell-a", "95928")
    assert (row.confirm_token_hash, row.unsubscribe_token_hash) == (s.confirm_hash, s.new_unsubscribe_hash)
    assert row.confirmation_sends_24h == 1 and row.last_confirmation_sent_at == NOW
    assert row.confirm_expires_at == NOW + timedelta(hours=48)


def test_a_point_is_stored_rounded_and_resolved_from_the_exact_point(repo):
    saved = repo.save_pending(signup(lat=39.7949, lon=-121.8461))
    assert saved.place == "39.79, -121.85"
    [row] = rows(repo)
    assert (row.query_lat, row.query_lon, row.zip) == (Decimal("39.79"), Decimal("-121.85"), None)
    assert row.forecast_point_id == "cell-a"


@pytest.mark.parametrize(
    ("point", "code"),
    [({"zip": "95929"}, "zip_not_found"), ({"zip": "90001"}, "zip_not_found"), ({"lat": 38.0, "lon": -121.0}, "out_of_scope")],
)
def test_unknown_locations_are_404_and_store_nothing(repo, point, code):
    with pytest.raises(ApiError) as err:
        repo.save_pending(signup(**point))
    assert err.value.code == code
    assert rows(repo) == []


def test_a_repeat_signup_updates_the_pending_row_in_place(repo):
    first, second = signup(), signup(NOW + timedelta(hours=1), lat=39.7, lon=-121.7)
    repo.save_pending(first)
    saved = repo.save_pending(second)
    [row] = rows(repo)
    assert saved.subscription_id == row.id == first.new_id
    assert row.unsubscribe_token_hash == first.new_unsubscribe_hash  # links already sent still work
    assert row.confirm_token_hash == second.confirm_hash  # the old confirm link stops working
    assert (row.forecast_point_id, row.zip, row.query_lat) == ("cell-b", None, Decimal("39.70"))
    assert row.confirmation_sends_24h == 2
    assert repo.confirm(first.confirm_hash, NOW) == "unknown"


def test_the_fourth_signup_in_24_hours_changes_nothing(repo):
    sent = [signup(NOW + timedelta(hours=h)) for h in range(3)]
    for s in sent:
        assert repo.save_pending(s) is not None
    assert repo.save_pending(signup(NOW + timedelta(hours=23))) is None
    [row] = rows(repo)
    assert row.confirm_token_hash == sent[-1].confirm_hash  # the last link stays valid
    assert row.confirmation_sends_24h == 3


def test_the_counter_resets_24_hours_after_the_last_email(repo):
    for h in range(3):
        repo.save_pending(signup(NOW + timedelta(hours=h)))
    assert repo.save_pending(signup(NOW + timedelta(hours=26))) is not None
    [row] = rows(repo)
    assert row.confirmation_sends_24h == 1


def test_already_active_for_the_same_cell_is_a_no_op(repo):
    activate(repo)
    assert repo.save_pending(signup(lat=39.7, lon=-121.9)) is None  # another point in cell A
    assert [r.status for r in rows(repo)] == ["active"]


def test_active_elsewhere_gets_a_pending_row_next_to_it(repo):
    activate(repo)
    assert repo.save_pending(signup(lat=39.7, lon=-121.7)) is not None
    assert sorted(r.status for r in rows(repo)) == ["active", "pending"]


def test_record_confirmation(repo):
    saved = repo.save_pending(signup())
    repo.record_confirmation(saved.subscription_id, sent=False, error="SMTP delivery failed (OSError)", now=NOW)
    with repo.sessions() as s:
        [n] = s.scalars(select(AlertNotification))
    assert (n.kind, n.status, n.attempts, n.sent_at, n.alert_id) == ("confirmation", "failed", 1, None, None)
    # A row unsubscribed in the meantime is not an error.
    repo.record_confirmation("gone", sent=True, error=None, now=NOW)


# --- confirm ---


def test_confirm_then_already_confirmed(repo):
    s = signup()
    repo.save_pending(s)
    assert repo.confirm(s.confirm_hash, NOW + timedelta(hours=1)) == "confirmed"
    [row] = rows(repo)
    assert (row.status, row.confirmed_at) == ("active", NOW + timedelta(hours=1))
    assert repo.confirm(s.confirm_hash, NOW + timedelta(hours=2)) == "already_confirmed"


def test_confirm_after_48_hours_is_expired(repo):
    s = signup()
    repo.save_pending(s)
    assert repo.confirm(s.confirm_hash, NOW + timedelta(hours=48)) == "expired"
    assert rows(repo)[0].status == "pending"


def test_confirm_unknown_hash(repo):
    assert repo.confirm("nope", NOW) == "unknown"


def test_confirming_replaces_the_previous_subscription(repo):
    old = activate(repo)
    repo.record_confirmation(old.id, sent=True, error=None, now=NOW)
    new = signup(lat=39.7, lon=-121.7)
    repo.save_pending(new)
    assert repo.confirm(new.confirm_hash, NOW) == "confirmed"
    [row] = rows(repo)
    assert (row.id, row.forecast_point_id, row.status) == (new.new_id, "cell-b", "active")
    with repo.sessions() as s:
        assert s.scalars(select(AlertNotification)).all() == []  # cascaded with the old row


# --- unsubscribe and clean-up ---


def test_unsubscribe_deletes_and_repeats(repo):
    s = signup()
    repo.save_pending(s)
    repo.unsubscribe(s.new_unsubscribe_hash)
    repo.unsubscribe(s.new_unsubscribe_hash)
    assert rows(repo) == []


def test_purge_deletes_only_expired_pending_rows(repo):
    activate(repo)
    repo.save_pending(signup(email="expired@example.com"))
    repo.save_pending(signup(NOW + timedelta(hours=10), email="fresh@example.com"))
    assert repo.purge_expired_pending(NOW + timedelta(hours=49)) == 1
    assert rows(repo, "expired@example.com") == []
    assert len(rows(repo, "fresh@example.com")) == 1
    assert len(rows(repo)) == 1  # active rows are never purged


# --- cell.active_alert ---


def test_active_alert_is_the_cells_open_episode(repo):
    def episode(status: str, **kw) -> Alert:
        return Alert(
            forecast_point_id="cell-a",
            severity="unhealthy_sensitive",
            status=status,
            first_triggered_at=NOW,
            last_seen_at=NOW,
            pm25_threshold=25.5,
            aqi_table_version="epa-2024",
            peak_pm25_predicted=105.17,
            peak_target_time=NOW + timedelta(hours=6),
            horizon_hours=6,
            model_key="baseline_v2/1.0.0",
            **kw,
        )

    with repo.sessions() as s:
        s.add_all([episode("resolved", resolved_at=NOW), episode("open")])
        s.commit()
        assert active_alert(s.execute(OPEN_ALERT, {"id": "cell-a"}).first()) == {
            "severity": "unhealthy_sensitive",
            "first_triggered_at": "2026-11-20T12:00:00Z",
            "peak_pm25_predicted": 105.1,
            "peak_target_time": "2026-11-20T18:00:00Z",
            "horizon_hours": 6,
        }
        assert active_alert(s.execute(OPEN_ALERT, {"id": "cell-b"}).first()) is None

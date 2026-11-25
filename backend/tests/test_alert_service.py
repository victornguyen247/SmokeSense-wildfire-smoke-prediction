"""Alert service rules with a fake repository (API-05, docs/alerts.md section 2).

The database side is in test_alert_endpoints_db.py.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.tokens import is_well_formed, token_hash, unsubscribe_token
from app.repositories.alerts import PendingSignup, SavedPending
from app.schemas.alerts import AlertSubscribeRequest
from app.services import alert_service
from app.services.email import EmailSendError, memory_backend, sender

SECRET = "s" * 40
EMAIL = "someone@example.com"


class FakeRepo:
    def __init__(self, saved: SavedPending | None = None, outcome: str = "confirmed") -> None:
        self.saved = saved
        self.outcome = outcome
        self.signups: list[PendingSignup] = []
        self.recorded: list[tuple[str, bool, str | None]] = []
        self.confirmed: list[str] = []
        self.unsubscribed: list[str] = []

    def save_pending(self, signup):
        self.signups.append(signup)
        return self.saved

    def record_confirmation(self, subscription_id, *, sent, error, now):
        self.recorded.append((subscription_id, sent, error))

    def confirm(self, confirm_hash, now):
        self.confirmed.append(confirm_hash)
        return self.outcome

    def unsubscribe(self, unsubscribe_hash):
        self.unsubscribed.append(unsubscribe_hash)

    def purge_expired_pending(self, now):
        return 2


@pytest.fixture(autouse=True)
def alert_settings(monkeypatch):
    settings = Settings(
        _env_file=None,
        email_backend="memory",
        environment="development",
        alerts_token_secret=SECRET,
        alerts_frontend_base_url="https://map.example",
        alerts_api_base_url="https://api.example",
    )
    monkeypatch.setattr(alert_service, "get_settings", lambda: settings)
    monkeypatch.setattr(sender, "get_settings", lambda: settings)
    memory_backend.outbox.clear()
    yield
    memory_backend.outbox.clear()


def subscribe(repo, **body):
    return alert_service.subscribe(repo, AlertSubscribeRequest(email=EMAIL, **(body or {"zip": "95928"})))


def token_in(url: str, marker: str) -> str:
    token = url.split(marker, 1)[1].split()[0]
    assert is_well_formed(token)
    return token


def test_subscribe_sends_one_confirmation_with_fragment_and_one_click_links():
    repo = FakeRepo(SavedPending("sub-1", "ZIP 95928"))
    assert subscribe(repo) == {"status": "pending_confirmation"}

    [message] = memory_backend.outbox
    assert message.to == EMAIL
    assert "ZIP 95928" in message.subject
    confirm = token_in(message.text, "https://map.example/alerts/confirm#token=")
    assert repo.signups[0].confirm_hash == token_hash(confirm)
    # List-Unsubscribe is the only link with ?token=, and it unsubscribes this row.
    assert message.unsubscribe_url == (
        f"https://api.example/api/v1/alerts/unsubscribe?token={unsubscribe_token(SECRET, 'sub-1')}"
    )
    assert "?token=" not in message.text
    assert repo.recorded == [("sub-1", True, None)]


def test_subscribe_passes_the_rules_and_a_new_rows_unsubscribe_hash():
    repo = FakeRepo()
    subscribe(repo, lat=39.7285, lon=-121.8375)
    [signup] = repo.signups
    assert signup.email == EMAIL
    assert (signup.point.lat, signup.point.lon) == (39.7285, -121.8375)
    assert signup.expires_at - signup.now == timedelta(hours=48)
    assert (signup.send_limit, signup.send_window) == (3, timedelta(hours=24))
    assert signup.new_unsubscribe_hash == token_hash(unsubscribe_token(SECRET, signup.new_id))


def test_nothing_to_send_is_the_same_202_and_sends_nothing():
    repo = FakeRepo(saved=None)  # rate-limited, or already active for the cell
    assert subscribe(repo) == {"status": "pending_confirmation"}
    assert not memory_backend.outbox
    assert not repo.recorded


def test_outside_california_is_404_before_the_repository():
    repo = FakeRepo()
    with pytest.raises(ApiError) as err:
        subscribe(repo, lat=45.52, lon=-122.68)
    assert (err.value.status, err.value.code) == (404, "out_of_scope")
    assert not repo.signups


def test_a_failed_confirmation_email_is_recorded_and_still_202(monkeypatch, caplog):
    def fail(message):
        raise EmailSendError("SMTP delivery failed (ConnectionRefusedError)")

    monkeypatch.setattr(alert_service.email, "send", fail)
    repo = FakeRepo(SavedPending("sub-1", "ZIP 95928"))
    with caplog.at_level(logging.DEBUG):
        assert subscribe(repo) == {"status": "pending_confirmation"}
    assert repo.recorded == [("sub-1", False, "SMTP delivery failed (ConnectionRefusedError)")]
    assert EMAIL not in caplog.text and "example.com" not in caplog.text


def test_no_email_or_token_is_logged(caplog):
    repo = FakeRepo(SavedPending("sub-1", "ZIP 95928"))
    with caplog.at_level(logging.DEBUG):
        subscribe(repo)
        alert_service.confirm(repo, "A" * 43)
        alert_service.unsubscribe(repo, "B" * 43)
    [message] = memory_backend.outbox
    confirm = token_in(message.text, "#token=")
    for secret_value in (EMAIL, confirm, "A" * 43, "B" * 43, unsubscribe_token(SECRET, "sub-1")):
        assert secret_value not in caplog.text


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [("unknown", 404, "invalid_token"), ("expired", 410, "token_expired")],
)
def test_confirm_errors(outcome, status, code):
    with pytest.raises(ApiError) as err:
        alert_service.confirm(FakeRepo(outcome=outcome), "A" * 43)
    assert (err.value.status, err.value.code) == (status, code)
    assert "A" * 43 not in err.value.message


@pytest.mark.parametrize("outcome", ["confirmed", "already_confirmed"])
def test_confirm_looks_up_the_token_hash(outcome):
    repo = FakeRepo(outcome=outcome)
    assert alert_service.confirm(repo, "A" * 43) == {"status": outcome}
    assert repo.confirmed == [token_hash("A" * 43)]


@pytest.mark.parametrize("token", ["", "short", "A" * 42, "A" * 44, "A" * 42 + "=", "A" * 42 + "+"])
def test_malformed_tokens_are_404_without_a_lookup(token):
    repo = FakeRepo()
    for call in (alert_service.confirm, alert_service.unsubscribe):
        with pytest.raises(ApiError) as err:
            call(repo, token)
        assert (err.value.status, err.value.code) == (404, "invalid_token")
    assert not repo.confirmed and not repo.unsubscribed


def test_unsubscribe_is_idempotent_and_deletes_by_hash():
    repo = FakeRepo()
    for _ in range(2):
        assert alert_service.unsubscribe(repo, "B" * 43) == {"status": "unsubscribed"}
    assert repo.unsubscribed == [token_hash("B" * 43)] * 2


def test_purge_expired_pending_delegates():
    assert alert_service.purge_expired_pending(FakeRepo()) == 2

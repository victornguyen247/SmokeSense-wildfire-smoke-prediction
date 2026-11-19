"""API-07: email templates and backends. No network: SMTP is replaced by a fake."""

import pytest

from app.core.config import get_settings
from app.services.email import (
    EXPERIMENTAL_LINE,
    EmailSendError,
    memory_backend,
    render_alert,
    render_confirmation,
    send,
)
from app.services.email import backends

UNSUB = "https://example.test/unsubscribe?token=abc"


def _messages():
    return [
        render_confirmation(
            to="a@example.test", location="Redding, CA",
            confirm_url="https://example.test/confirm?token=xyz", unsubscribe_url=UNSUB,
        ),
        render_alert(
            to="a@example.test", location="Redding, CA", category="Unhealthy for Sensitive Groups",
            horizon_hours=6, pm25=41.234, valid_time_utc="2026-11-19T18:00:00Z", unsubscribe_url=UNSUB,
        ),
    ]


@pytest.fixture(autouse=True)
def memory_mode(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "memory")
    get_settings.cache_clear()
    memory_backend.outbox.clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("message", _messages())
def test_every_template_has_experimental_line_and_unsubscribe(message):
    for body in (message.text, message.html):
        assert EXPERIMENTAL_LINE in body
        assert UNSUB in body


def test_html_escapes_values():
    m = render_alert(
        to="a@example.test", location="<script>x</script>", category="c",
        horizon_hours=1, pm25=1.0, valid_time_utc="t", unsubscribe_url=UNSUB,
    )
    assert "<script>" not in m.html
    assert "<script>" in m.text  # plain text is not escaped


def test_memory_backend_records_messages():
    first, second = _messages()
    send(first)
    send(second)
    assert memory_backend.outbox == [first, second]


def test_smtp_backend_sets_one_click_headers(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, mime):
            sent.append(mime)

    monkeypatch.setattr(backends.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    get_settings.cache_clear()
    send(_messages()[1])
    assert sent[0]["List-Unsubscribe"] == f"<{UNSUB}>"
    assert sent[0]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert not memory_backend.outbox


def test_smtp_failure_does_not_leak_recipient(monkeypatch):
    def boom(*a, **k):
        raise backends.smtplib.SMTPRecipientsRefused({"a@example.test": (550, b"no")})

    monkeypatch.setattr(backends.smtplib, "SMTP", boom)
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    get_settings.cache_clear()
    with pytest.raises(EmailSendError) as err:
        send(_messages()[0])
    assert "example.test" not in str(err.value)


def test_unknown_backend_is_an_error(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "carrier-pigeon")
    get_settings.cache_clear()
    with pytest.raises(EmailSendError):
        send(_messages()[0])

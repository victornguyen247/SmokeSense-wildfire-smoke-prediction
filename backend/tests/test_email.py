"""API-07: email templates and backends. No network: SMTP is replaced by a fake."""

import pytest

from app.core.config import Settings
from app.services.email import (
    EXPERIMENTAL_LINE,
    EmailMessage,
    EmailSendError,
    backends,
    memory_backend,
    render_alert,
    render_confirmation,
    send,
    send_many,
    sender,
)

UNSUB = "https://example.test/unsubscribe?token=abc"


def _messages():
    return [
        render_confirmation(
            to="a@example.test", location="Redding, CA",
            confirm_url="https://example.test/confirm?token=xyz", unsubscribe_url=UNSUB,
        ),
        render_alert(
            to="a@example.test", location="Redding, CA",
            horizon_hours=6, pm25=41.234, valid_time_utc="2026-11-19T18:00:00Z", unsubscribe_url=UNSUB,
        ),
    ]


def use_settings(monkeypatch, **overrides):
    """Settings built directly (no env file or global cache), so nothing leaks between tests."""
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(sender, "get_settings", lambda: settings)


@pytest.fixture(autouse=True)
def memory_mode(monkeypatch):
    use_settings(monkeypatch, email_backend="memory", environment="development")
    memory_backend.outbox.clear()
    yield
    memory_backend.outbox.clear()


@pytest.mark.parametrize("message", _messages())
def test_every_template_has_experimental_line_and_unsubscribe(message):
    for body in (message.text, message.html):
        assert EXPERIMENTAL_LINE in body
        assert UNSUB in body


def test_alert_category_comes_from_aqi_table():
    alert = _messages()[1]
    assert "Unhealthy for Sensitive Groups" in alert.subject  # 41.2 ug/m3
    assert "41.2" in alert.text


def test_html_escapes_values():
    m = render_alert(
        to="a@example.test", location="<script>x</script>",
        horizon_hours=1, pm25=1.0, valid_time_utc="t", unsubscribe_url=UNSUB,
    )
    assert "<script>" not in m.html
    assert "<script>" in m.text  # plain text is not escaped


def test_memory_backend_records_messages():
    first, second = _messages()
    send(first)
    send(second)
    assert memory_backend.outbox == [first, second]


def test_memory_backend_refused_on_staging(monkeypatch):
    use_settings(monkeypatch, email_backend="memory", environment="staging")
    with pytest.raises(EmailSendError):
        send(_messages()[0])


def test_bad_backend_name_stops_startup():
    with pytest.raises(ValueError):
        Settings(_env_file=None, email_backend="carrier-pigeon")


class FakeSMTP:
    instances: list = []

    def __init__(self, host, port, timeout):
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, mime):
        self.sent.append(mime)


def test_smtp_backend_sets_one_click_headers_over_one_connection(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(backends.smtplib, "SMTP", FakeSMTP)
    use_settings(monkeypatch, email_backend="smtp")
    send_many(_messages())
    assert len(FakeSMTP.instances) == 1
    sent = FakeSMTP.instances[0].sent
    assert len(sent) == 2
    assert sent[1]["List-Unsubscribe"] == f"<{UNSUB}>"
    assert sent[1]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert not memory_backend.outbox


@pytest.mark.parametrize("exc", [
    backends.smtplib.SMTPRecipientsRefused({"a@example.test": (550, b"no")}),
    ConnectionRefusedError("a@example.test"),
])
def test_smtp_failure_does_not_leak_recipient(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(backends.smtplib, "SMTP", boom)
    use_settings(monkeypatch, email_backend="smtp")
    with pytest.raises(EmailSendError) as err:
        send(_messages()[0])
    assert "example.test" not in str(err.value)


def test_non_ascii_address_does_not_leak_recipient(monkeypatch):
    monkeypatch.setattr(backends.smtplib, "SMTP", FakeSMTP)
    use_settings(monkeypatch, email_backend="smtp")
    msg = EmailMessage(to="é\u0000@example.test", subject="s", text="t", html="h", unsubscribe_url=UNSUB)
    try:
        send(msg)
    except EmailSendError as err:
        assert "example.test" not in str(err)


@pytest.mark.parametrize("field,value", [
    ("to", "a@example.test\r\nBcc: x@evil.test"),
    ("subject", "hi\nBcc: x@evil.test"),
    ("unsubscribe_url", "https://example.test/u\r\nX: y"),
    ("unsubscribe_url", "javascript:alert(1)"),
    ("unsubscribe_url", "https://example.test/u>, <https://evil.test"),
])
def test_bad_header_values_are_rejected(field, value):
    fields = dict(to="a@example.test", subject="s", text="t", html="h", unsubscribe_url=UNSUB)
    fields[field] = value
    with pytest.raises(EmailSendError) as err:
        EmailMessage(**fields)
    assert "example.test" not in str(err.value) and "evil" not in str(err.value)

"""API-07: email templates and backends. No network: SMTP is replaced by a fake."""

from datetime import datetime, timezone

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
MAP = "https://example.test/?zip=96001"
ISSUED = datetime(2024, 7, 27, 17, 0, tzinfo=timezone.utc)  # Sat, Jul 27, 10 AM PDT
TARGET_6H = datetime(2024, 7, 27, 23, 0, tzinfo=timezone.utc)  # Sat, Jul 27, 4 PM PDT
TARGET_24H = datetime(2024, 7, 28, 17, 0, tzinfo=timezone.utc)  # Sun, Jul 28, 10 AM PDT
EXPIRES = datetime(2024, 7, 29, 17, 0, tzinfo=timezone.utc)


def _messages():
    return [
        render_confirmation(
            to="a@example.test", place="ZIP 96001",
            confirm_url="https://example.test/confirm?token=xyz",
            unsubscribe_url=UNSUB, expires_at=EXPIRES,
        ),
        render_alert(
            to="a@example.test", place="ZIP 96001",
            horizons=[(6, TARGET_6H, 41.234)],
            issued_at=ISSUED, map_url=MAP,
            nearest_monitor_dist_km=5.0, unsubscribe_url=UNSUB,
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
def test_every_template_has_experimental_line(message):
    for body in (message.text, message.html):
        assert EXPERIMENTAL_LINE in body


def test_alert_has_unsubscribe_and_section6_copy():
    alert = _messages()[1]
    assert alert.subject == "Smoke alert for ZIP 96001: unhealthy for sensitive groups expected"
    assert "41.2" in alert.text  # truncated, not rounded from 41.234
    assert "In 6 h, around Sat, Jul 27, 4 PM PDT" in alert.text
    assert "What this means" in alert.text
    assert "What you can do" in alert.text
    assert f"See the forecast on the map: {MAP}" in alert.text
    assert "You get at most one SmokeSense alert a day." in alert.text
    assert UNSUB in alert.text and UNSUB in alert.html
    assert "lower confidence" not in alert.text


def test_alert_24h_only_subject_is_not_moderate():
    # 20.0 µg/m³ is Moderate on the AQI table, but the subject is the episode risk.
    alert = render_alert(
        to="a@example.test", place="ZIP 96001",
        horizons=[(24, TARGET_24H, 20.0)],
        issued_at=ISSUED, map_url=MAP,
        nearest_monitor_dist_km=5.0, unsubscribe_url=UNSUB,
    )
    assert "Moderate" not in alert.subject
    assert "unhealthy for sensitive groups expected" in alert.subject
    assert "Moderate" in alert.text  # body still shows the AQI label for that value


def test_alert_horizons_earliest_first_and_low_confidence():
    alert = render_alert(
        to="a@example.test", place="ZIP 96001",
        horizons=[(24, TARGET_24H, 22.0), (6, TARGET_6H, 40.0)],
        issued_at=ISSUED, map_url=MAP,
        nearest_monitor_dist_km=30.0, unsubscribe_url=UNSUB,
    )
    six = alert.text.index("In 6 h")
    twenty_four = alert.text.index("In 24 h")
    assert six < twenty_four
    assert "The nearest air monitor is 30 km away" in alert.text
    assert "lower confidence" in alert.text


def test_confirmation_subject_and_expires_local():
    conf = _messages()[0]
    assert conf.subject == "Confirm your SmokeSense smoke alerts for ZIP 96001"
    assert "expires in 48 hours (Mon, Jul 29, 10 AM PDT)" in conf.text


def test_html_escapes_values():
    m = render_alert(
        to="a@example.test", place="<script>x</script>",
        horizons=[(1, TARGET_6H, 1.0)],
        issued_at=ISSUED, map_url=MAP,
        nearest_monitor_dist_km=1.0, unsubscribe_url=UNSUB,
    )
    assert "<script>" not in m.html
    assert "<script>" in m.text  # plain text is not escaped


def test_memory_backend_records_messages():
    first, second = _messages()
    send(first)
    send(second)
    assert memory_backend.outbox == [first, second]


def test_memory_backend_refused_on_staging(monkeypatch):
    # Staging settings need a token secret to load (API-05); this test is about the backend.
    use_settings(monkeypatch, email_backend="memory", environment="staging", alerts_token_secret="k" * 32)
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

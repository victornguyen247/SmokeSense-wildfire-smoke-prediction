"""monitors.aqs_code (#32): the AirNow connector emits the normalized code; upserts fill it."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from ingestion import db
from ingestion.connectors.airnow import normalize_airnow_row
from tests.test_airnow_aqs_code import _row


def test_connector_emits_the_normalized_aqs_code():
    assert normalize_airnow_row(_row("840060072003"))["monitor"]["aqs_code"] == "060072003"
    assert normalize_airnow_row(_row("840TT5821016"))["monitor"]["aqs_code"] == "TT5821016"


def test_existing_monitor_without_code_gets_it_on_upsert():
    existing = SimpleNamespace(aqs_code=None)
    session = MagicMock()
    session.scalar.return_value = existing
    db.get_or_create_monitor(session, {"source": "airnow", "external_id": "airnow:x", "aqs_code": "061030007"})
    assert existing.aqs_code == "061030007"


def test_new_monitor_is_created_with_its_code():
    session = MagicMock()
    session.scalar.return_value = None
    data = normalize_airnow_row(_row("840060072003"))["monitor"]
    monitor = db.get_or_create_monitor(session, data)
    assert monitor.aqs_code == "060072003"

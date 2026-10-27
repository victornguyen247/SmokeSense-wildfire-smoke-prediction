"""DATA-06 live AirNow job: training-identical cleaning, California scope, idempotent upserts.

NOW is inside Red Bluff's -1 h offset period (airnow_time_offsets.py), so the fixture
also checks that the per-site correction applies on the live path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

from ingestion.connectors.airnow import get_airnow_pm25_records, normalize_aqs_code
from ingestion.live import airnow
from ingestion.live.common import RetryTransport

ROWS = json.loads(
    (Path(__file__).parent / "fixtures/live/airnow_aq_data.json").read_text()
)
NOW = datetime(2021, 8, 6, 18, 20, tzinfo=timezone.utc)
KEY = "AIRNOW-LIVE-TEST-KEY-0000"


def utc(text_: str) -> datetime:
    return datetime.fromisoformat(text_).replace(tzinfo=timezone.utc)


def mock_client(rows=ROWS, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url)
        return httpx.Response(200, json=rows)

    return httpx.Client(transport=httpx.MockTransport(handler))


def records_by_code(records):
    return {
        (r["source_metadata"]["station_id"], r["observation"]["valid_at"]): r[
            "observation"
        ]["pm25"]
        for r in records
    }


def test_cleaning_scope_and_offsets(monkeypatch):
    monkeypatch.setattr(airnow.settings, "airnow_api_key", KEY)
    seen: list[httpx.URL] = []
    fetched, records = airnow.fetch_records(
        mock_client(seen=seen), NOW - timedelta(hours=72), NOW
    )

    assert fetched == len(ROWS)
    assert records_by_code(records) == {
        # Red Bluff: AirNow labels 17:00 and 16:00 are the true hours 16:00 and 15:00.
        ("061030007", utc("2021-08-06T16:00")): 204.0,
        ("061030007", utc("2021-08-06T15:00")): 150.0,
        # 840-prefixed code cut to 9; -999 (16:00) and -7 (14:00) dropped; -3.2 clamped to 0.
        ("060070008", utc("2021-08-06T17:00")): 35.5,
        ("060070008", utc("2021-08-06T15:00")): 0.0,
        # Tribal site listed in CA_TRIBAL_SITES.
        ("TT5821016", utc("2021-08-06T17:00")): 8.0,
    }  # Reno (NV, 32-) is out of scope; 2021-08-03 10:00 is before the 72 h window.
    assert {r["monitor"]["aqs_code"] for r in records} == {
        "061030007",
        "060070008",
        "TT5821016",
    }
    assert {r["observation"]["correction"] for r in records} == {"regulatory"}

    params = seen[0].params
    assert params["parameters"] == "PM25" and params["monitorType"] == "0"
    assert params["includerawconcentrations"] == "1"
    assert params["BBOX"] == "-124.5,32.5,-114.1,42.1"
    # Window: 72 h back, padded 1 h for the largest offset, up to the current hour.
    assert (
        params["startDate"] == "2021-08-03T17" and params["endDate"] == "2021-08-06T18"
    )


def test_aqs_code_normalization():
    assert normalize_aqs_code("840060070008") == "060070008"
    assert normalize_aqs_code("840TT5821016") == "TT5821016"
    assert normalize_aqs_code("061030007") == "061030007"


def test_live_rows_match_the_batch_normalizer(monkeypatch):
    """Parity: the same raw rows through the DATA-03 batch path give identical records."""
    monkeypatch.setattr(airnow.settings, "airnow_api_key", KEY)
    _, live = airnow.fetch_records(mock_client(), NOW - timedelta(hours=72), NOW)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: real_client(
            *a,
            **{
                **k,
                "transport": httpx.MockTransport(
                    lambda r: httpx.Response(200, json=ROWS)
                ),
            },
        ),
    )
    batch = get_airnow_pm25_records(KEY, bbox="-124.5,32.5,-114.1,42.1")

    volatile = {"received_at", "ingested_at", "first_seen_at", "last_seen_at"}

    def stable(record):
        return {
            part: {k: v for k, v in record[part].items() if k not in volatile}
            for part in ("monitor", "observation", "source_metadata")
        }

    batch_by_key = {
        (r["monitor"]["external_id"], r["observation"]["valid_at"]): stable(r)
        for r in batch
    }
    for record in live:
        key = (record["monitor"]["external_id"], record["observation"]["valid_at"])
        assert stable(record) == batch_by_key[key]


def test_rerun_is_idempotent_and_revisions_update(monkeypatch, live_db):
    monkeypatch.setattr(airnow.settings, "airnow_api_key", KEY)

    first = airnow.run(session_factory=live_db, client=mock_client(), now=NOW)
    again = airnow.run(session_factory=live_db, client=mock_client(), now=NOW)
    revised_rows = [dict(r) for r in ROWS]
    revised_rows[2]["RawConcentration"] = 36.0  # Chico 17:00 revised upstream
    revised = airnow.run(
        session_factory=live_db,
        client=mock_client(revised_rows),
        now=NOW + timedelta(hours=1),
    )

    assert first["status"] == again["status"] == revised["status"] == "success"
    assert (first["rows_written"], again["rows_written"], revised["rows_written"]) == (
        5,
        0,
        1,
    )
    assert first["watermark"] == "2021-08-06T17:00:00+00:00"
    with live_db() as s:
        count = s.scalar(text("select count(*) from observations"))
        monitors = s.scalar(
            text("select count(*) from monitors where source = 'airnow'")
        )
        chico = s.scalar(
            text(
                "select o.pm25 from observations o join monitors m on m.id = o.monitor_id "
                "where m.aqs_code = '060070008' and o.valid_at = '2021-08-06T17:00Z'"
            )
        )
        unmarked = s.scalar(
            text("select count(*) from observations where ingestion_run_id is null")
        )
    assert (count, monitors, chico, unmarked) == (5, 3, 36.0, 0)


def test_historical_row_is_never_modified(monkeypatch, live_db):
    monkeypatch.setattr(airnow.settings, "airnow_api_key", KEY)
    airnow.run(session_factory=live_db, client=mock_client(), now=NOW)
    with (
        live_db() as s
    ):  # turn one row into a batch (historical) row with another value
        s.execute(
            text(
                "update observations set ingestion_run_id = null, pm25 = 99.0 "
                "where valid_at = '2021-08-06T17:00Z' and monitor_id = "
                "(select id from monitors where aqs_code = '060070008')"
            )
        )
        s.commit()

    result = airnow.run(
        session_factory=live_db, client=mock_client(), now=NOW + timedelta(hours=1)
    )

    assert result["rows_written"] == 0
    with live_db() as s:
        row = s.execute(
            text("select pm25, ingestion_run_id from observations where pm25 = 99.0")
        ).one()
    assert row.ingestion_run_id is None


def test_http_429_is_not_retried_and_fails_the_run(monkeypatch, live_db):
    monkeypatch.setattr(airnow.settings, "airnow_api_key", KEY)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="Rate limit exceeded")

    sleeps: list[float] = []
    transport = RetryTransport(
        airnow.RETRY_STATUSES,
        sleep=sleeps.append,
        transport=httpx.MockTransport(handler),
    )
    result = airnow.run(
        session_factory=live_db, client=httpx.Client(transport=transport), now=NOW
    )
    assert result["status"] == "failed" and "429" in result["error"]
    assert len(calls) == 1 and sleeps == []  # the hourly quota is not burned on retries

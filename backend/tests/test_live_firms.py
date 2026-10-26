"""DATA-06 live FIRMS job: SNPP NRT only, California + 200 km, idempotent upserts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

from ingestion.connectors.firms import get_firms_records
from ingestion.live import firms

FIXTURE = (Path(__file__).parent / "fixtures/live/firms_viirs_snpp_nrt.csv").read_text()
NOW = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)
KEY = "firms-live-test-key-0123456789"


def mock_client(seen: list[str] | None = None, body: str = FIXTURE) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_requests_snpp_nrt_only_over_california_plus_200km(monkeypatch):
    monkeypatch.setattr(firms.settings, "firms_map_key", KEY)
    seen: list[str] = []
    firms.fetch_records(mock_client(seen), NOW - timedelta(hours=72), NOW)

    assert len(seen) == 1
    path = httpx.URL(seen[0]).path
    assert "/VIIRS_SNPP_NRT/" in path
    for other in ("NOAA20", "NOAA21", "MODIS", "_SP"):
        assert other not in path
    assert (
        f"/{firms.firms_bbox()}/4" in path
    )  # 72 h back from 02:00 UTC spans 4 UTC days
    west, south, east, north = (float(v) for v in firms.firms_bbox().split(","))
    assert (
        west < -124.5 - 1.8
        and east > -114.1 + 1.8
        and south < 32.5 - 1.7
        and north > 42.1 + 1.7
    )


def test_keeps_snpp_in_window_and_dedupes(monkeypatch):
    monkeypatch.setattr(firms.settings, "firms_map_key", KEY)
    fetched, records = firms.fetch_records(
        mock_client(), NOW - timedelta(hours=72), NOW
    )

    assert fetched == 6
    # Dropped: the exact duplicate row, the NOAA-20 ("J") row, and the one older than 72 h.
    assert len(records) == 3
    assert {r["satellite"] for r in records} == {"VIIRS_SNPP"}
    assert {r["product"] for r in records} == {"NRT"}
    assert all(NOW - timedelta(hours=72) <= r["detected_at"] <= NOW for r in records)


def test_live_rows_match_the_batch_normalizer(monkeypatch):
    """Parity: same raw CSV through the batch connector gives the same rows."""
    monkeypatch.setattr(firms.settings, "firms_map_key", KEY)
    _, live = firms.fetch_records(mock_client(), NOW - timedelta(hours=72), NOW)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda *a, **k: real_client(
            *a,
            **{
                **k,
                "transport": httpx.MockTransport(
                    lambda r: httpx.Response(200, text=FIXTURE)
                ),
            },
        ),
    )
    batch = get_firms_records(
        KEY, source="VIIRS_SNPP_NRT", bbox=firms.firms_bbox(), day_range=4
    )

    drop = {"received_at", "ingested_at"}
    batch_by_id = {
        r["external_id"]: {k: v for k, v in r.items() if k not in drop} for r in batch
    }
    for row in live:
        assert {k: v for k, v in row.items() if k not in drop} == batch_by_id[
            row["external_id"]
        ]


def test_day_range():
    assert firms.day_range_for(NOW - timedelta(hours=24), NOW) == 2
    assert firms.day_range_for(NOW - timedelta(days=30), NOW) == firms.MAX_DAY_RANGE
    assert firms.day_range_for(NOW, NOW) == 1


def test_missing_key_fails_the_run_without_raising(monkeypatch, live_db):
    monkeypatch.setattr(firms.settings, "firms_map_key", "")
    result = firms.run(session_factory=live_db, client=mock_client(), now=NOW)
    assert result["status"] == "failed"
    assert "FIRMS_MAP_KEY is not set" in result["error"]


def test_rerun_is_idempotent_and_rows_are_marked_live(monkeypatch, live_db):
    monkeypatch.setattr(firms.settings, "firms_map_key", KEY)

    first = firms.run(session_factory=live_db, client=mock_client(), now=NOW)
    second = firms.run(
        session_factory=live_db, client=mock_client(), now=NOW + timedelta(minutes=30)
    )

    assert first["status"] == second["status"] == "success"
    assert first["rows_written"] == 3 and second["rows_written"] == 0
    with live_db() as s:
        rows = s.execute(
            text("select ingestion_run_id, satellite, product from fire_detections")
        ).all()
        runs = s.execute(
            text("select source, status, rows_fetched, finished_at from ingestion_runs")
        ).all()
    assert len(rows) == 3
    assert {r.ingestion_run_id for r in rows} == {first["run_id"]}
    assert {(r.satellite, r.product) for r in rows} == {("VIIRS_SNPP", "NRT")}
    assert len(runs) == 2 and all(r.source == "firms" and r.finished_at for r in runs)


def test_existing_historical_detection_is_not_duplicated(monkeypatch, live_db):
    """A batch (_SP) row at the same satellite/time/pixel blocks the live copy and is untouched."""
    monkeypatch.setattr(firms.settings, "firms_map_key", KEY)
    with live_db() as s:
        s.execute(
            text("""
            insert into fire_detections (id, external_id, satellite, product, geom, detected_at,
                received_at, confidence_raw, confidence_level, frp_mw)
            values ('hist-1', 'firms:hist', 'VIIRS_SNPP', 'SP',
                ST_GeogFromText('SRID=4326;POINT(-122.54321 40.12345)'),
                '2026-10-23T09:12:00Z', now(), 'n', 'nominal', 99.0)""")
        )
        s.commit()

    result = firms.run(session_factory=live_db, client=mock_client(), now=NOW)

    assert result["rows_written"] == 2
    with live_db() as s:
        hist = s.execute(
            text(
                "select product, frp_mw, ingestion_run_id from fire_detections "
                "where id = 'hist-1'"
            )
        ).one()
        total = s.scalar(text("select count(*) from fire_detections"))
    assert (hist.product, hist.frp_mw, hist.ingestion_run_id) == ("SP", 99.0, None)
    assert total == 3

"""Shared fixtures.

live_db: a real PostGIS database migrated to head, for the DATA-06 live-ingestion
tests (upserts, partitions and retention need Postgres semantics). Set
TEST_DATABASE_URL to a database whose name ends in "_test"; it is dropped and
recreated once per session. Without it those tests are skipped.

    TEST_DATABASE_URL=postgresql+psycopg://smokesense:smokesense@localhost:5433/smokesense_test pytest
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]

# Tables the live tests write; emptied before each test.
LIVE_TEST_TABLES = (
    "observations",
    "fire_detections",
    "weather_observations",
    "monitors",
    "ingestion_runs",
)


@pytest.fixture(scope="session")
def live_db_engine():
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TEST_DATABASE_URL not set (needs a PostGIS database named *_test)")
    url = make_url(raw)
    if not (url.database or "").endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must name a database ending in _test; it is dropped and recreated"
        )

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    # Alembic reads the URL from app settings, so pass it as the POSTGRES_* variables.
    env = {
        **os.environ,
        "POSTGRES_USER": url.username or "",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_HOST": url.host or "localhost",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_DB": url.database,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
    )

    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def live_db(live_db_engine):
    """sessionmaker bound to the empty, migrated test database."""
    with live_db_engine.begin() as c:
        c.execute(text(f"TRUNCATE {', '.join(LIVE_TEST_TABLES)} CASCADE"))
    return sessionmaker(bind=live_db_engine, autoflush=False, autocommit=False)

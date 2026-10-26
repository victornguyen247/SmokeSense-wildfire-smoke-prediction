"""The live-ingestion test database can only ever be the *_test database.

PR #68 adds a DATABASE_URL setting (a cloud database such as Neon) that wins over the
POSTGRES_* variables, even when it is set only in backend/.env. The alembic subprocess
that migrates the test database must not follow it anywhere else.
"""

from __future__ import annotations

import subprocess
import sys

from sqlalchemy.engine import make_url

from conftest import BACKEND, alembic_env

TEST_URL = make_url(
    "postgresql+psycopg://smokesense:smokesense@localhost:5433/smokesense_test"
)
CLOUD = "postgresql://someone:secret@cloud-db.invalid/neondb?sslmode=require"

# PR #68's rule, applied the way app settings would see the subprocess environment
# (env vars first, then backend/.env). Prints only "ok" or "bad", never a URL.
PR68_RULE = """
import sys
from pydantic import Field
from app.core.config import Settings

class WithCloudUrl(Settings):
    cloud_database_url: str = Field(default="", validation_alias="DATABASE_URL")

s = WithCloudUrl()
url = s.cloud_database_url.strip() or (
    f"postgresql+psycopg://{s.postgres_user}:{s.postgres_password}"
    f"@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
)
print("ok" if url == sys.argv[1] else "bad")
"""


def test_alembic_env_blanks_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", CLOUD)

    env = alembic_env(TEST_URL)

    assert env["DATABASE_URL"] == ""
    assert env["POSTGRES_DB"] == "smokesense_test"
    assert (env["POSTGRES_HOST"], env["POSTGRES_PORT"]) == ("localhost", "5433")


def test_settings_in_the_subprocess_resolve_to_the_test_database(monkeypatch):
    """Even with a cloud DATABASE_URL in the environment (and possibly in .env)."""
    monkeypatch.setenv("DATABASE_URL", CLOUD)
    expected = TEST_URL.render_as_string(hide_password=False)

    out = subprocess.run(
        [sys.executable, "-c", PR68_RULE, expected],
        cwd=BACKEND,  # so backend/.env is read, as alembic would read it
        env=alembic_env(TEST_URL),
        capture_output=True,
        text=True,
        check=True,
    )

    assert out.stdout.strip() == "ok"


def test_fixture_migrates_the_test_database_with_a_cloud_url_set(
    monkeypatch, live_db_engine
):
    monkeypatch.setenv("DATABASE_URL", CLOUD)
    url = live_db_engine.url

    out = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=BACKEND,
        env=alembic_env(url),
        capture_output=True,
        text=True,
        check=True,
    )

    assert "(head)" in out.stdout

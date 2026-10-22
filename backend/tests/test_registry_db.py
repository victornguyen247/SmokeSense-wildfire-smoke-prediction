"""SqlRepo against a real Postgres (the one_production index and row locking live there).

Skipped unless TEST_DATABASE_URL points at a migrated database (`alembic upgrade head`), e.g. a
throwaway Neon branch or the local docker db. Rows are created under a unique model_name and
removed afterwards.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("geoalchemy2")
URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

from sqlalchemy import create_engine, text

from mlops.registry import (
    PRODUCTION,
    RETIRED,
    SHADOW,
    LocalStore,
    Registry,
    RegistryError,
    SqlRepo,
)
from tests.test_registry import make_model_dir


@pytest.fixture
def reg(tmp_path):
    url = URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    name = f"t{uuid.uuid4().hex[:8]}"
    r = Registry(SqlRepo(engine), LocalStore(tmp_path / "store"), tmp_path / "cache")
    r.test_name = name
    yield r
    with engine.begin() as c:
        c.execute(text("DELETE FROM model_versions WHERE model_name = :n"), {"n": name})


def test_lifecycle_and_single_production(reg, tmp_path):
    n = reg.test_name
    reg.register(make_model_dir(tmp_path / "a", seed="a"), n, "v1")
    reg.register(make_model_dir(tmp_path / "b", seed="b"), n, "v2")
    with pytest.raises(RegistryError, match="already registered"):
        reg.register(make_model_dir(tmp_path / "c", seed="a"), n, "v1")
    reg.promote(f"{n}/v1")
    reg.promote(f"{n}/v2")
    assert {v.model_key.split("/")[1]: v.status for v in reg.list(n)} == {"v1": RETIRED, "v2": PRODUCTION}
    reg.rollback(n)
    assert {v.model_key.split("/")[1]: v.status for v in reg.list(n)} == {"v1": PRODUCTION, "v2": SHADOW}
    row = reg.list(n)[0]
    assert row.artifact_sha256 and json.loads(json.dumps(row.created_at.isoformat()))


def test_database_rejects_a_second_production_row(reg, tmp_path):
    n = reg.test_name
    reg.register(make_model_dir(tmp_path / "a"), n, "v1")
    reg.register(make_model_dir(tmp_path / "b", seed="b"), n, "v2")
    reg.promote(f"{n}/v1")
    with pytest.raises(Exception, match="one_production"), reg.repo.transaction(n) as tx:
        tx.set_status(f"{n}/v2", PRODUCTION, datetime.now(UTC))

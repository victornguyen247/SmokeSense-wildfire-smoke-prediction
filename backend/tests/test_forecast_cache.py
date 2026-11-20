"""API-02 parts that need no database: the cycle cache and the fake seed's guard."""

from __future__ import annotations

import pytest

from app.db.seed_fake_forecasts import require_local_database
from app.repositories.cache import CycleCache


def counting_builder():
    calls = []

    def build():
        calls.append(1)
        return len(calls)

    return build, calls


def test_a_cycle_serves_from_the_cache():
    cache = CycleCache()
    build, calls = counting_builder()
    assert cache.get_or_build("cycle-1", "grid", build) == 1
    assert cache.get_or_build("cycle-1", "grid", build) == 1
    assert len(calls) == 1


def test_a_new_cycle_replaces_the_old_responses():
    cache = CycleCache()
    build, calls = counting_builder()
    cache.get_or_build("cycle-1", "grid", build)
    assert cache.get_or_build("cycle-2", "grid", build) == 2
    assert len(calls) == 2


def test_keys_are_separate_within_a_cycle():
    cache = CycleCache()
    build, _ = counting_builder()
    assert cache.get_or_build("cycle-1", "grid", build) == 1
    assert cache.get_or_build("cycle-1", "monitors", build) == 2


def test_the_least_recently_used_entry_is_evicted():
    cache = CycleCache(max_entries=2)
    build, calls = counting_builder()
    cache.get_or_build("cycle-1", "a", build)
    cache.get_or_build("cycle-1", "b", build)
    cache.get_or_build("cycle-1", "a", build)  # refreshes a, so b is the oldest
    cache.get_or_build("cycle-1", "c", build)
    assert cache.get_or_build("cycle-1", "a", build) == 1
    assert cache.get_or_build("cycle-1", "b", build) == 4
    assert len(calls) == 4


def test_a_slow_build_from_an_old_cycle_is_not_stored():
    cache = CycleCache()

    def build_while_a_new_cycle_arrives():
        cache.get_or_build("cycle-2", "grid", lambda: "new")
        return "old"

    assert cache.get_or_build("cycle-1", "grid", build_while_a_new_cycle_arrives) == "old"
    assert cache.get_or_build("cycle-2", "grid", lambda: "rebuilt") == "new"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5433/smokesense",
        "postgresql+psycopg://u:p@127.0.0.1/smokesense",
        "postgresql+psycopg://u:p@db:5432/smokesense",
    ],
)
def test_seed_runs_against_local_databases(url):
    require_local_database(url)


def test_seed_refuses_a_cloud_database_without_naming_it():
    with pytest.raises(SystemExit) as refused:
        require_local_database("postgresql+psycopg://u:secret@cloud-db.invalid/neondb")
    assert "secret" not in str(refused.value) and "cloud-db" not in str(refused.value)

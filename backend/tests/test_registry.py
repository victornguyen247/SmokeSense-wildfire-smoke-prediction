"""Model registry (OPS-02): archive, stores, register/promote/rollback/load."""
from __future__ import annotations

import contextlib
import copy
import errno
import json
import shutil
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mlops.registry import (
    BACKEND,
    PRODUCTION,
    RETIRED,
    SHADOW,
    LocalStore,
    Registry,
    RegistryError,
    S3Store,
    Version,
    main,
    pack,
    read_metadata,
    resolve_dir,
    sha256_file,
    unpack,
)


class MemoryRepo:
    """In-memory Repo that raises, like the one_production index, on a second production row."""

    def __init__(self) -> None:
        self.rows: dict[str, Version] = {}
        self.clock = datetime(2026, 10, 1, tzinfo=UTC)
        self.in_tx = False

    @contextlib.contextmanager
    def transaction(self, model_name: str):
        snapshot, repo = copy.deepcopy(self.rows), self

        class Tx:
            def versions(self) -> list[Version]:
                return [copy.copy(v) for v in repo.rows.values() if v.model_name == model_name]

            def add(self, fields: dict[str, Any]) -> None:
                known = set(Version.__dataclass_fields__) - {"extra"}
                repo.clock += timedelta(minutes=1)
                repo.rows[fields["model_key"]] = Version(
                    **{k: v for k, v in fields.items() if k in known}, created_at=repo.clock,
                    extra={k: v for k, v in fields.items() if k not in known})

            def set_status(self, model_key: str, status: str, at: datetime) -> None:
                others = [v for v in repo.rows.values()
                          if v.model_name == model_name and v.model_key != model_key]
                if status == PRODUCTION and any(v.status == PRODUCTION for v in others):
                    raise RuntimeError("one_production violated")
                repo.clock += timedelta(minutes=1)
                repo.rows[model_key].status, repo.rows[model_key].status_changed_at = status, repo.clock

        self.in_tx = True
        try:
            yield Tx()
        except BaseException:
            self.rows = snapshot
            raise
        finally:
            self.in_tx = False

    def all_versions(self, model_name: str | None = None) -> list[Version]:
        return [copy.copy(v) for v in self.rows.values() if model_name in (None, v.model_name)]


def make_model_dir(root: Path, name: str = "m", seed: str = "a") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "release.json").write_text(json.dumps({
        "1": {"serve": "v2", "pooled_skill": 0.1, "macro_skill": 0.1, "threshold": 30.5},
        "3": {"serve": "persistence", "pooled_skill": -0.1, "macro_skill": 0.0, "threshold": 35.5},
    }))
    (d / "features.json").write_text(json.dumps({"features": ["a", "b"]}))
    (d / "params.json").write_text(json.dumps({"seed": 1}))
    (d / "manifest.json").write_text(json.dumps({"dataset": {"data_sha256": "deadbeef"}}))
    (d / "model_h1.json").write_text(seed * 100)
    (d / "sub").mkdir()
    (d / "sub" / "x.bin").write_bytes(seed.encode() * 10)
    return d


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return Registry(MemoryRepo(), LocalStore(tmp_path / "store"), tmp_path / "cache")


def register(reg: Registry, tmp_path: Path, version: str, seed: str = "a") -> Version:
    d = make_model_dir(tmp_path / f"src_{version}", seed=seed)
    return reg.register(d, "baseline", version)


# --- archive -------------------------------------------------------------------------------


def test_pack_is_deterministic_and_round_trips(tmp_path):
    d = make_model_dir(tmp_path / "one")
    pack(d, tmp_path / "a.tar.gz")
    # same content, different mtimes -> same bytes
    d2 = tmp_path / "two"
    shutil.copytree(d, d2)
    (d2 / "release.json").touch()
    pack(d2, tmp_path / "b.tar.gz")
    assert sha256_file(tmp_path / "a.tar.gz") == sha256_file(tmp_path / "b.tar.gz")

    out = tmp_path / "out"
    out.mkdir()
    unpack(tmp_path / "a.tar.gz", out)
    assert (out / "release.json").read_text() == (d / "release.json").read_text()
    assert (out / "sub" / "x.bin").exists()


def test_unpack_rejects_path_traversal(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 0
        tar.addfile(info)
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(RegistryError, match="unsafe"):
        unpack(evil, out)
    assert not (tmp_path / "escape.txt").exists()


# --- metadata ------------------------------------------------------------------------------


def test_read_metadata_from_release_json(tmp_path):
    meta = read_metadata(make_model_dir(tmp_path))
    assert meta["thresholds"] == {"1": 30.5, "3": 35.5}
    assert meta["feature_list"] == ["a", "b"]
    assert meta["training_data_hash"] == "deadbeef"
    assert meta["hyperparameters"] == {"seed": 1}
    assert meta["backtest_metrics"] is None


def test_read_metadata_ignores_non_horizon_keys(tmp_path):
    d = make_model_dir(tmp_path)
    release = json.loads((d / "release.json").read_text())
    release["basis"] = "threshold chosen on the ML-01 split"  # text mentioning "threshold"
    release["n_rows"] = 12345
    release["notes"] = {"threshold": 1.0}  # a dict, but not a horizon
    (d / "release.json").write_text(json.dumps(release))
    assert read_metadata(d)["thresholds"] == {"1": 30.5, "3": 35.5}


@pytest.mark.parametrize("bad", ["high", None, [1]])
def test_read_metadata_rejects_non_numeric_threshold(tmp_path, bad):
    d = make_model_dir(tmp_path)
    release = json.loads((d / "release.json").read_text())
    release["6"] = {"serve": "v2", "threshold": bad}
    (d / "release.json").write_text(json.dumps(release))
    with pytest.raises(RegistryError, match="horizon 6 threshold .* is not a number"):
        read_metadata(d)


def test_read_metadata_rejects_non_model_dir(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(RegistryError, match="release.json"):
        read_metadata(tmp_path / "empty")


# --- register / promote / rollback ---------------------------------------------------------


def test_register_inserts_shadow_with_checksum(reg, tmp_path):
    v = register(reg, tmp_path, "v1")
    assert (v.model_key, v.status) == ("baseline/v1", SHADOW)
    assert len(v.artifact_sha256) == 64
    assert v.artifact_uri.startswith("file:")
    assert reg.repo.rows["baseline/v1"].extra["thresholds"] == {"1": 30.5, "3": 35.5}


def test_register_twice_is_refused(reg, tmp_path):
    register(reg, tmp_path, "v1")
    with pytest.raises(RegistryError, match="already registered"):
        reg.register(make_model_dir(tmp_path / "again"), "baseline", "v1")


def test_promote_retires_previous_and_keeps_one_production(reg, tmp_path):
    register(reg, tmp_path, "v1", "a")
    register(reg, tmp_path, "v2", "b")
    new, old = reg.promote("baseline/v1")
    assert old is None and new.status == PRODUCTION
    new, old = reg.promote("baseline/v2")
    assert (new.model_key, old.model_key) == ("baseline/v2", "baseline/v1")
    status = {v.model_key: v.status for v in reg.list("baseline")}
    assert status == {"baseline/v1": RETIRED, "baseline/v2": PRODUCTION}


def test_promote_already_production_and_unknown(reg, tmp_path):
    register(reg, tmp_path, "v1")
    reg.promote("baseline/v1")
    with pytest.raises(RegistryError, match="already production"):
        reg.promote("baseline/v1")
    with pytest.raises(RegistryError, match="no such"):
        reg.promote("baseline/v9")


def test_promote_with_corrupt_artifact_changes_nothing(reg, tmp_path):
    register(reg, tmp_path, "v1", "a")
    register(reg, tmp_path, "v2", "b")
    reg.promote("baseline/v1")
    (reg.store.root / "baseline" / "v2.tar.gz").write_bytes(b"tampered")
    with pytest.raises(RegistryError, match="checksum mismatch"):
        reg.promote("baseline/v2")
    assert {v.model_key: v.status for v in reg.list("baseline")} == {
        "baseline/v1": PRODUCTION, "baseline/v2": SHADOW}


def test_rollback_restores_previous_in_one_call(reg, tmp_path):
    register(reg, tmp_path, "v1", "a")
    register(reg, tmp_path, "v2", "b")
    reg.promote("baseline/v1")
    reg.promote("baseline/v2")
    restored, demoted = reg.rollback("baseline")
    assert (restored.model_key, demoted.model_key) == ("baseline/v1", "baseline/v2")
    status = {v.model_key: v.status for v in reg.list("baseline")}
    assert status == {"baseline/v1": PRODUCTION, "baseline/v2": SHADOW}


def test_rollback_walks_back_through_history(reg, tmp_path):
    for i, seed in enumerate("abc", 1):
        register(reg, tmp_path, f"v{i}", seed)
        reg.promote(f"baseline/v{i}")
    assert reg.rollback("baseline")[0].model_key == "baseline/v2"
    assert reg.rollback("baseline")[0].model_key == "baseline/v1"
    with pytest.raises(RegistryError, match="nothing to roll back"):
        reg.rollback("baseline")
    assert [v.model_key for v in reg.list("baseline") if v.status == PRODUCTION] == ["baseline/v1"]


def test_models_are_independent_families(reg, tmp_path):
    register(reg, tmp_path, "v1")
    reg.register(make_model_dir(tmp_path / "other"), "other", "v1")
    reg.promote("baseline/v1")
    reg.promote("other/v1")
    assert sum(v.status == PRODUCTION for v in reg.list()) == 2


# --- load ----------------------------------------------------------------------------------


def test_load_production_verifies_and_extracts(reg, tmp_path):
    register(reg, tmp_path, "v1")
    with pytest.raises(RegistryError, match="no production"):
        reg.load_production("baseline")
    reg.promote("baseline/v1")
    v, path = reg.load_production("baseline")
    assert (path / "release.json").is_file() and path.name == v.artifact_sha256


def test_load_detects_tampering_after_cache_miss(reg, tmp_path):
    v = register(reg, tmp_path, "v1")
    (reg.store.root / "baseline" / "v1.tar.gz").write_bytes(b"tampered")
    with pytest.raises(RegistryError, match="checksum mismatch"):
        reg.materialize(v)
    assert not (reg.cache_dir / v.artifact_sha256).exists()


# --- S3 / R2 -------------------------------------------------------------------------------


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.objects[(bucket, key)] = Path(filename).read_bytes()

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        Path(filename).write_bytes(self.objects[(bucket, key)])


def test_s3_backend_round_trip(tmp_path):
    client = FakeS3()
    store = S3Store("smoke-sense", "models", client=client)
    reg = Registry(MemoryRepo(), store, tmp_path / "cache")
    v = register(reg, tmp_path, "v1")
    assert v.artifact_uri == "s3://smoke-sense/models/baseline/v1.tar.gz"
    assert ("smoke-sense", "models/baseline/v1.tar.gz") in client.objects
    reg.promote("baseline/v1")
    assert (reg.load_production("baseline")[1] / "release.json").is_file()


def test_s3_rejects_foreign_bucket(tmp_path):
    store = S3Store("smoke-sense", client=FakeS3())
    with pytest.raises(RegistryError, match="outside"):
        store.get("s3://other/x.tar.gz", tmp_path / "x")


# --- CLI -----------------------------------------------------------------------------------


def test_cli_end_to_end(reg, tmp_path, capsys):
    d1, d2 = make_model_dir(tmp_path / "s1", seed="a"), make_model_dir(tmp_path / "s2", seed="b")
    assert main(["register", str(d1), "--name", "baseline", "--version", "v1"], reg) == 0
    assert main(["register", str(d2), "--name", "baseline", "--version", "v2"], reg) == 0
    assert main(["promote", "baseline/v1"], reg) == 0
    assert main(["promote", "baseline/v2"], reg) == 0
    assert main(["rollback", "baseline"], reg) == 0
    capsys.readouterr()
    assert main(["list", "--name", "baseline"], reg) == 0
    out = capsys.readouterr().out
    assert "baseline/v1" in out and "production" in out and "shadow" in out
    assert main(["load", "baseline"], reg) == 0


def test_cli_reports_errors_without_traceback(reg, capsys):
    assert main(["promote", "baseline/nope"], reg) == 1
    assert "error: no such model version" in capsys.readouterr().err


# --- review fixes --------------------------------------------------------------------------


def test_cache_hit_is_reverified_and_repaired(reg, tmp_path):
    v = register(reg, tmp_path, "v1")
    path = reg.materialize(v)
    (path / "model_h1.json").write_text("corrupted")
    assert (reg.materialize(v) / "model_h1.json").read_text() == "a" * 100  # re-fetched
    (path / "extra.bin").write_bytes(b"x")  # an extra file is also damage
    assert not (reg.materialize(v) / "extra.bin").exists()


def test_cache_without_manifest_is_not_trusted(reg, tmp_path):
    v = register(reg, tmp_path, "v1")
    reg.materialize(v)
    reg._manifest_path(v).unlink()
    (reg.cache_dir / v.artifact_sha256 / "model_h1.json").write_text("corrupted")
    assert (reg.materialize(v) / "model_h1.json").read_text() == "a" * 100


def test_concurrent_loader_winning_the_rename_is_not_an_error(reg, tmp_path, monkeypatch):
    v = register(reg, tmp_path, "v1")

    def lose_race(self, target):  # the other loader already put identical content there
        shutil.copytree(self, target)
        raise OSError(errno.ENOTEMPTY, "Directory not empty")

    monkeypatch.setattr(Path, "rename", lose_race)
    assert (reg.materialize(v) / "release.json").is_file()


@pytest.mark.parametrize("name,version", [("a/b", "v1"), ("a", "v/1"), ("a", ".."), ("", "v1"),
                                          ("a", "v 1"), ("a", "../x")])
def test_register_rejects_bad_names(reg, tmp_path, name, version):
    with pytest.raises(RegistryError, match="invalid"):
        reg.register(make_model_dir(tmp_path / "d"), name, version)
    assert reg.list() == []


def test_model_key_must_have_name_and_version(reg):
    with pytest.raises(RegistryError, match="expected <name>/<version>"):
        reg.promote("baseline")


def test_download_happens_outside_the_transaction(tmp_path):
    repo = MemoryRepo()

    class CheckingStore(LocalStore):
        def get(self, uri, dest):
            assert not repo.in_tx, "downloading while holding the row locks"
            super().get(uri, dest)

    reg = Registry(repo, CheckingStore(tmp_path / "store"), tmp_path / "cache")
    register(reg, tmp_path, "v1", "a")
    register(reg, tmp_path, "v2", "b")
    reg.promote("baseline/v1")
    reg.promote("baseline/v2")
    shutil.rmtree(reg.cache_dir)  # force a fresh download for the rollback
    reg.rollback("baseline")


def test_upload_failure_is_a_registry_error(tmp_path):
    class Denied(FakeS3):
        def upload_file(self, *a):
            raise PermissionError("no credentials")

    reg = Registry(MemoryRepo(), S3Store("smoke-sense", client=Denied()), tmp_path / "cache")
    with pytest.raises(RegistryError, match="could not upload"):
        reg.register(make_model_dir(tmp_path / "d"), "baseline", "v1")
    assert reg.list() == []


def test_relative_registry_dirs_resolve_against_backend(tmp_path):
    assert resolve_dir("data/registry") == BACKEND / "data" / "registry"
    assert resolve_dir(str(tmp_path)) == tmp_path

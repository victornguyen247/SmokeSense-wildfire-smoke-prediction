"""Model registry CLI over model_versions (OPS-02, docs/mlops/registry.md).

    python -m mlops.registry register data/models/baseline_v2 --name baseline --version v2
    python -m mlops.registry list
    python -m mlops.registry promote baseline/v2
    python -m mlops.registry rollback baseline
    python -m mlops.registry load baseline          # prints the verified local model dir

A model version is one directory (release.json, per-horizon boosters, ...) stored as a single
deterministic .tar.gz. model_versions.artifact_sha256 is the sha256 of that archive and is
checked on every load. The table keeps its own status names (docs/schema.md):

    shadow      = "candidate" (registered, not serving)
    production  = "active"    (at most one per model_name; the one_production index enforces it)
    retired

Backends (REGISTRY_BACKEND=local|s3) only decide where `register` writes. `load` follows the
row's artifact_uri, so a version stays loadable whichever backend wrote it.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname

SHADOW, PRODUCTION, RETIRED = "shadow", "production", "retired"
ARCHIVE_SUFFIX = ".tar.gz"
BACKEND = Path(__file__).resolve().parents[1]
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class RegistryError(Exception):
    """A user-facing failure (bad input, missing version, checksum mismatch)."""


def check_name(kind: str, value: str) -> str:
    """Names and versions end up in model keys and storage paths: no '/', '..' or spaces."""
    if not _NAME_RE.fullmatch(value) or ".." in value:
        raise RegistryError(f"invalid {kind} {value!r}: use letters, digits, '.', '_' and '-'")
    return value


def split_key(model_key: str) -> tuple[str, str]:
    name, sep, version = model_key.partition("/")
    if not sep:
        raise RegistryError(f"expected <name>/<version>, got {model_key!r}")
    return check_name("name", name), check_name("version", version)


def resolve_dir(path: str) -> Path:
    """Relative registry paths are relative to backend/, not to wherever the CLI was started."""
    p = Path(path)
    return p if p.is_absolute() else BACKEND / p


# --------------------------------------------------------------------------- archive


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(src_dir: Path, dest: Path) -> None:
    """Deterministic .tar.gz of src_dir's files (same directory contents -> same sha256)."""
    files = sorted(p for p in src_dir.rglob("*") if p.is_file())
    # filename="" keeps the output path out of the gzip header, or the hash would depend on it.
    with (
        dest.open("wb") as raw,
        gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for p in files:
            info = tarfile.TarInfo(p.relative_to(src_dir).as_posix())
            info.size = p.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            with p.open("rb") as f:
                tar.addfile(info, f)


def unpack(archive: Path, dest: Path) -> None:
    """Extract regular files only; refuse absolute paths and '..'."""
    root = dest.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar.getmembers():
            name = PurePosixPath(m.name)
            if not m.isfile() or name.is_absolute() or ".." in name.parts:
                raise RegistryError(f"unsafe or unsupported archive member: {m.name!r}")
            target = (root / name).resolve()
            if not target.is_relative_to(root):
                raise RegistryError(f"unsafe archive member: {m.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            assert src is not None
            with target.open("wb") as out:
                shutil.copyfileobj(src, out)


# --------------------------------------------------------------------------- stores


class Store(Protocol):
    def put(self, key: str, src: Path) -> str:
        """Upload src as `key`; return the artifact_uri."""

    def get(self, uri: str, dest: Path) -> None: ...


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, key: str, src: Path) -> str:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        return target.resolve().as_uri()

    def get(self, uri: str, dest: Path) -> None:
        path = Path(url2pathname(urlparse(uri).path))
        if not path.is_file():
            raise RegistryError(f"artifact not found: {path}")
        shutil.copyfile(path, dest)


class S3Store:
    """S3 or any S3-compatible service (Cloudflare R2). Credentials come from boto3's
    standard chain (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY); nothing is read from code."""

    def __init__(self, bucket: str, prefix: str = "models", endpoint_url: str = "", client: Any = None):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is None:
            try:
                import boto3  # lazy: the local backend needs no boto3
            except ImportError as e:
                raise RegistryError("the s3 backend needs boto3 (pip install -r requirements.txt)") from e

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                region_name="auto" if endpoint_url else None,  # R2 expects "auto"
            )
        self.client = client

    def put(self, key: str, src: Path) -> str:
        full = f"{self.prefix}/{key}" if self.prefix else key
        try:
            self.client.upload_file(str(src), self.bucket, full)
        except Exception as e:  # missing credentials, bad endpoint, access denied, ...
            raise RegistryError(f"could not upload {full} to bucket {self.bucket!r}: {e}") from e
        return f"s3://{self.bucket}/{full}"

    def get(self, uri: str, dest: Path) -> None:
        u = urlparse(uri)
        if u.netloc != self.bucket:
            raise RegistryError(f"{uri} is outside the configured bucket {self.bucket!r}")
        try:
            self.client.download_file(self.bucket, u.path.lstrip("/"), str(dest))
        except Exception as e:  # botocore ClientError and friends
            raise RegistryError(f"could not download {uri}: {e}") from e


# --------------------------------------------------------------------------- repository


@dataclass
class Version:
    model_key: str
    model_name: str
    version: str
    artifact_uri: str
    artifact_sha256: str
    status: str
    algorithm: str = ""
    created_at: datetime | None = None
    status_changed_at: datetime | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # remaining insert columns


class Tx(Protocol):
    """One transaction with every row of one model_name locked."""

    def versions(self) -> list[Version]: ...
    def add(self, fields: dict[str, Any]) -> None: ...
    def set_status(self, model_key: str, status: str, at: datetime) -> None: ...


class Repo(Protocol):
    def transaction(self, model_name: str) -> contextlib.AbstractContextManager[Tx]: ...
    def all_versions(self, model_name: str | None = None) -> list[Version]: ...


@contextlib.contextmanager
def _db_errors() -> Iterator[None]:
    """Turn driver/connection errors into a one-line RegistryError."""
    from sqlalchemy.exc import SQLAlchemyError

    try:
        yield
    except SQLAlchemyError as e:
        raise RegistryError(f"database error: {getattr(e, 'orig', None) or e}") from e


class SqlRepo:
    """model_versions in Postgres. Uses the ORM model; imported lazily so the CLI's helpers
    (and the unit tests) don't need the database stack."""

    def __init__(self, engine: Any = None):
        if engine is None:
            from sqlalchemy import create_engine

            from app.core.config import settings

            engine = create_engine(settings.database_url)
        self.engine = engine

    @staticmethod
    def _to_version(row: Any) -> Version:
        return Version(
            model_key=row.model_key, model_name=row.model_name, version=row.version,
            artifact_uri=row.artifact_uri, artifact_sha256=row.artifact_sha256, status=row.status,
            algorithm=row.algorithm, created_at=row.created_at,
            status_changed_at=row.status_changed_at, notes=row.notes,
        )

    @contextlib.contextmanager
    def transaction(self, model_name: str) -> Iterator[Tx]:
        from sqlalchemy import select, text
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        from app.models.predictions import ModelVersion

        with _db_errors(), Session(self.engine) as session, session.begin():
            # Serialise everything for this model_name. The advisory lock also covers the first
            # register of a new name, where there are no rows for FOR UPDATE to lock.
            session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:n))"), {"n": model_name})
            rows = list(session.scalars(
                select(ModelVersion).where(ModelVersion.model_name == model_name).with_for_update()
            ))

            class _Tx:
                def versions(self_) -> list[Version]:
                    return [self._to_version(r) for r in rows]

                def add(self_, fields: dict[str, Any]) -> None:
                    row = ModelVersion(**fields)
                    session.add(row)
                    try:
                        session.flush()
                    except IntegrityError as e:
                        raise RegistryError(f"{fields['model_key']} is already registered") from e
                    rows.append(row)

                def set_status(self_, model_key: str, status: str, at: datetime) -> None:
                    row = next(r for r in rows if r.model_key == model_key)
                    row.status, row.status_changed_at = status, at
                    # Flush per change: retire the old production row before promoting the new
                    # one, because the one_production index is checked per statement.
                    session.flush()

            yield _Tx()

    def all_versions(self, model_name: str | None = None) -> list[Version]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.models.predictions import ModelVersion

        stmt = select(ModelVersion).order_by(ModelVersion.model_name, ModelVersion.created_at)
        if model_name:
            stmt = stmt.where(ModelVersion.model_name == model_name)
        with _db_errors(), Session(self.engine) as session:
            return [self._to_version(r) for r in session.scalars(stmt)]


# --------------------------------------------------------------------------- registry


def _now() -> datetime:
    return datetime.now(UTC)


def read_metadata(model_dir: Path) -> dict[str, Any]:
    """model_versions columns that come from the artifact directory (see docs/mlops/registry.md)."""

    def load(name: str) -> Any:
        p = model_dir / name
        return json.loads(p.read_text()) if p.is_file() else None

    release, features = load("release.json"), load("features.json")
    if not isinstance(release, dict):
        raise RegistryError(f"{model_dir} has no release.json; is this a model directory?")
    if not features or not features.get("features"):
        raise RegistryError(f"{model_dir}/features.json is missing or has no 'features' list")
    thresholds = {}
    for h, v in release.items():
        if not (h.isdigit() and isinstance(v, dict) and "threshold" in v):
            continue  # metadata such as "basis"
        try:
            thresholds[h] = float(v["threshold"])
        except (TypeError, ValueError) as e:
            raise RegistryError(
                f"{model_dir}/release.json: horizon {h} threshold {v['threshold']!r} is not a number") from e
    manifest = load("manifest.json") or {}
    return {
        "feature_list": list(features["features"]),
        "thresholds": thresholds or None,
        "hyperparameters": load("params.json"),
        "backtest_metrics": load("metrics.json"),
        "training_data_hash": (manifest.get("dataset") or {}).get("data_sha256"),
    }


class Registry:
    def __init__(self, repo: Repo, store: Store, cache_dir: Path, store_for_uri: Any = None):
        self.repo, self.store, self.cache_dir = repo, store, Path(cache_dir)
        # uri -> Store used to download; defaults to the configured store.
        self.store_for_uri = store_for_uri or (lambda uri: self.store)

    def register(self, model_dir: Path, name: str, version: str, algorithm: str = "xgboost",
                 training_data_uri: str | None = None, notes: str | None = None) -> Version:
        check_name("name", name)
        check_name("version", version)
        model_dir = Path(model_dir)
        if not model_dir.is_dir():
            raise RegistryError(f"not a directory: {model_dir}")
        meta = read_metadata(model_dir)
        key = f"{name}/{version}"
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / f"{version}{ARCHIVE_SUFFIX}"
            pack(model_dir, archive)
            sha = sha256_file(archive)
            with self.repo.transaction(name) as tx:
                if any(v.model_key == key for v in tx.versions()):
                    raise RegistryError(f"{key} is already registered (versions are immutable; use a new version)")
                uri = self.store.put(f"{key}{ARCHIVE_SUFFIX}", archive)
                tx.add({
                    "model_key": key, "model_name": name, "version": version, "algorithm": algorithm,
                    "artifact_uri": uri, "artifact_sha256": sha, "training_data_uri": training_data_uri,
                    "notes": notes, "status": SHADOW, "status_changed_at": _now(), **meta,
                })
        return self.get(key)

    def get(self, model_key: str) -> Version:
        name, _ = split_key(model_key)
        for v in self.repo.all_versions(name):
            if v.model_key == model_key:
                return v
        raise RegistryError(f"no such model version: {model_key}")

    def list(self, name: str | None = None) -> list[Version]:
        return self.repo.all_versions(name)

    def _manifest_path(self, v: Version) -> Path:
        return self.cache_dir / f"{v.artifact_sha256}.files.json"

    def _cached_ok(self, v: Version) -> bool:
        """True if the cached copy still matches the per-file hashes recorded when it was
        verified against artifact_sha256."""
        target, manifest = self.cache_dir / v.artifact_sha256, self._manifest_path(v)
        if not (target.is_dir() and manifest.is_file()):
            return False
        try:
            recorded = json.loads(manifest.read_text())
        except ValueError:
            return False
        present = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
        return present.keys() == recorded.keys() and all(
            sha256_file(present[name]) == digest for name, digest in recorded.items())

    def materialize(self, v: Version) -> Path:
        """Return a local directory holding v, verified against artifact_sha256.

        The archive's sha256 is checked on download; the extracted files' hashes are recorded
        and re-checked on every cache hit, so a damaged cache is discarded and fetched again."""
        target = self.cache_dir / v.artifact_sha256
        if self._cached_ok(v):
            return target
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        with tempfile.TemporaryDirectory(dir=self.cache_dir) as tmp:
            archive = Path(tmp) / "artifact.tar.gz"
            self.store_for_uri(v.artifact_uri).get(v.artifact_uri, archive)
            got = sha256_file(archive)
            if got != v.artifact_sha256:
                raise RegistryError(
                    f"checksum mismatch for {v.model_key}: expected {v.artifact_sha256}, got {got}")
            staging = Path(tmp) / "extract"
            staging.mkdir()
            unpack(archive, staging)
            files = {p.relative_to(staging).as_posix(): sha256_file(p)
                     for p in staging.rglob("*") if p.is_file()}
            self._manifest_path(v).write_text(json.dumps(files))
            try:
                staging.rename(target)
            except OSError:
                # A concurrent loader renamed first (FileExistsError on Windows, ENOTEMPTY on
                # POSIX). Its copy is content-identical; anything else is a real failure.
                if not target.is_dir():
                    raise
        if not self._cached_ok(v):
            raise RegistryError(f"cache for {v.model_key} failed verification after extraction")
        return target

    def promote(self, model_key: str) -> tuple[Version, Version | None]:
        """Make model_key the production version; the previous one becomes retired.
        Returns (new, retired)."""
        name, _ = split_key(model_key)
        # Download and verify before opening the transaction, so row locks are not held across
        # network I/O. Inside the lock the same call is a local cache check.
        self.materialize(self.get(model_key))
        with self.repo.transaction(name) as tx:
            rows = tx.versions()
            target = next((v for v in rows if v.model_key == model_key), None)
            if target is None:
                raise RegistryError(f"no such model version: {model_key}")
            if target.status == PRODUCTION:
                raise RegistryError(f"{model_key} is already production")
            self.materialize(target)  # never serve what we cannot verify
            current = next((v for v in rows if v.status == PRODUCTION), None)
            at = _now()
            if current:
                tx.set_status(current.model_key, RETIRED, at)
            tx.set_status(model_key, PRODUCTION, at)
        return self.get(model_key), current

    @staticmethod
    def _rollback_target(rows: list[Version], name: str) -> Version:
        retired = [v for v in rows if v.status == RETIRED]
        if not retired:
            raise RegistryError(f"nothing to roll back to for {name!r}: no retired versions")
        floor = datetime.min.replace(tzinfo=UTC)
        return max(retired, key=lambda v: (v.status_changed_at or floor, v.created_at or floor))

    def rollback(self, name: str) -> tuple[Version, Version | None]:
        """Restore the most recently retired version. The version being replaced goes back to
        shadow (not retired), so repeated rollbacks keep walking back through history instead
        of flip-flopping. Returns (restored, demoted)."""
        check_name("name", name)
        self.materialize(self._rollback_target(self.repo.all_versions(name), name))  # outside the lock
        with self.repo.transaction(name) as tx:
            rows = tx.versions()
            target = self._rollback_target(rows, name)
            self.materialize(target)
            current = next((v for v in rows if v.status == PRODUCTION), None)
            at = _now()
            if current:
                tx.set_status(current.model_key, SHADOW, at)
            tx.set_status(target.model_key, PRODUCTION, at)
        return self.get(target.model_key), current

    def load_production(self, name: str) -> tuple[Version, Path]:
        """The production version of `name` and its verified local directory."""
        for v in self.repo.all_versions(name):
            if v.status == PRODUCTION:
                return v, self.materialize(v)
        raise RegistryError(f"no production version for {name!r}")


# --------------------------------------------------------------------------- wiring + CLI


def build_registry() -> Registry:
    from app.core.config import settings

    backend = settings.registry_backend
    if backend == "local":
        store: Store = LocalStore(resolve_dir(settings.registry_local_dir))
    elif backend == "s3":
        store = S3Store(settings.registry_s3_bucket, settings.registry_s3_prefix,
                        settings.registry_s3_endpoint_url)
    else:
        raise RegistryError(f"REGISTRY_BACKEND must be 'local' or 's3', got {backend!r}")

    def store_for_uri(uri: str) -> Store:
        scheme = urlparse(uri).scheme
        if scheme == "file":
            return LocalStore(resolve_dir(settings.registry_local_dir))
        if scheme == "s3":
            return store if isinstance(store, S3Store) else S3Store(
                urlparse(uri).netloc, settings.registry_s3_prefix, settings.registry_s3_endpoint_url)
        raise RegistryError(f"unsupported artifact_uri scheme: {uri}")

    return Registry(SqlRepo(), store, resolve_dir(settings.registry_cache_dir), store_for_uri)


def _row(v: Version) -> str:
    when = v.status_changed_at.strftime("%Y-%m-%d %H:%M") if v.status_changed_at else "-"
    return f"{v.model_key:<28} {v.status:<11} {when:<17} {v.artifact_sha256[:12]}  {v.artifact_uri}"


def main(argv: list[str] | None = None, registry: Registry | None = None) -> int:
    p = argparse.ArgumentParser(prog="mlops.registry", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", help="upload a model directory and insert it as shadow (candidate)")
    r.add_argument("model_dir", type=Path)
    r.add_argument("--name", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--algorithm", default="xgboost")
    r.add_argument("--training-data-uri")
    r.add_argument("--notes")
    sub.add_parser("promote", help="make MODEL_KEY production, retire the previous one").add_argument("model_key")
    sub.add_parser("rollback", help="restore the most recently retired version").add_argument("name")
    sub.add_parser("list", help="show versions").add_argument("--name")
    sub.add_parser("load", help="print the verified local directory of the production version").add_argument("name")
    args = p.parse_args(argv)

    try:
        reg = registry or build_registry()
        if args.cmd == "register":
            v = reg.register(args.model_dir, args.name, args.version, args.algorithm,
                             args.training_data_uri, args.notes)
            print(f"registered {v.model_key} as {v.status}\n{_row(v)}")
        elif args.cmd == "promote":
            new, old = reg.promote(args.model_key)
            print(f"{new.model_key} is now production" + (f"; retired {old.model_key}" if old else ""))
        elif args.cmd == "rollback":
            restored, demoted = reg.rollback(args.name)
            print(f"{restored.model_key} is production again"
                  + (f"; {demoted.model_key} back to shadow" if demoted else ""))
        elif args.cmd == "list":
            for v in reg.list(args.name):
                print(_row(v))
        elif args.cmd == "load":
            v, path = reg.load_production(args.name)
            print(path)
    except RegistryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


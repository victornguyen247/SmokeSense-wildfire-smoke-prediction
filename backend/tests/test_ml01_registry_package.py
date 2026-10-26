"""ml.tools.package_ml01_for_registry: the ML-01 trees as a registrable model directory."""

from __future__ import annotations

import json
import shutil

import pytest

from ml.datasets.load import SMOKESENSE_V1
from ml.inference import ml01_baselines as ml01
from ml.tools import package_ml01_for_registry as pkg

RELEASE = ml01.DEFAULT_ARTIFACT_DIR
ZIP = pkg.RELEASE_DIR / f"{pkg.RELEASE_TAG}.zip"
CHECKSUM = pkg.RELEASE_DIR / f"{pkg.RELEASE_TAG}.sha256"
HORIZONS = ["1", "3", "6", "12", "24"]

# Like the ML-01 inference tests, these use the release extracted to data/models/ml01_baselines;
# the package also needs the release ZIP + checksum (data/release/) and smokesense_v1.
needs_release = pytest.mark.skipif(
    not (RELEASE / "model_metadata.json").is_file()
    or not ZIP.is_file()
    or not CHECKSUM.is_file(),
    reason="ML-01 release (extracted, ZIP and .sha256) not present",
)
needs_dataset = pytest.mark.skipif(
    not (SMOKESENSE_V1 / "data.parquet").is_file(),
    reason="smokesense_v1 not downloaded (scripts/fetch_data04.sh)",
)


def test_checksum_file_with_windows_line_endings(tmp_path):
    digest = "d7d22870afa66815632893d91700e0735e971e4fceb73603c621cb679847d7d5"
    f = tmp_path / "x.sha256"
    f.write_bytes(f"{digest.upper()}  ml01-baselines-v1.0.0.zip\r\n".encode())
    assert pkg.expected_sha256(f) == digest


def test_dump_is_deterministic_and_rejects_nan():
    assert pkg.dump({"b": 1, "a": [2, 1]}) == '{\n "a": [\n  2,\n  1\n ],\n "b": 1\n}\n'
    assert pkg.clean({"x": float("nan"), "y": 0.12345678}) == {"x": None, "y": 0.123457}


@needs_release
def test_refuses_a_zip_that_does_not_match_the_checksum(tmp_path):
    bad = tmp_path / "bad.sha256"
    bad.write_text("0" * 64 + "  ml01-baselines-v1.0.0.zip\r\n")
    with pytest.raises(pkg.PackageError, match="sha256"):
        pkg.verify_release(RELEASE, ZIP, bad)


@needs_release
def test_refuses_a_release_folder_that_differs_from_the_zip(tmp_path):
    copy = tmp_path / "release"
    shutil.copytree(RELEASE, copy)
    with (copy / "test_results.csv").open("a") as f:
        f.write("tampered\n")
    with pytest.raises(pkg.PackageError, match="differs from the verified ZIP"):
        pkg.verify_release(copy, ZIP, CHECKSUM)


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    out = tmp_path_factory.mktemp("pkg") / "ml01_decision_tree"
    assert pkg.main(["--out", str(out)]) == 0
    first = {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in out.rglob("*")
        if p.is_file()
    }
    assert pkg.main(["--out", str(out)]) == 0  # idempotent: replaces its own folder
    return out, first


@needs_release
@needs_dataset
def test_package_files_are_complete_valid_and_deterministic(package):
    out, first = package
    again = {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in out.rglob("*")
        if p.is_file()
    }
    assert again == first
    assert set(again) == set(pkg.MODEL_FILES + pkg.GENERATED)
    for name in pkg.GENERATED:
        json.loads(again[name])
    for name in pkg.MODEL_FILES:  # copied unchanged
        assert again[name] == (RELEASE / name).read_bytes()


@needs_release
@needs_dataset
def test_package_contents(package):
    out, _ = package
    load = lambda name: json.loads((out / name).read_text())  # noqa: E731
    assert load("features.json")["features"] == ml01.MODEL_FEATURES
    release = load("release.json")
    assert set(release) == {*HORIZONS, "basis"}
    for h in HORIZONS:
        assert set(release[h]) == {"serve", "pooled_skill", "macro_skill", "threshold"}
        assert release[h]["serve"] in {"decision_tree", "persistence"}
        assert release[h]["threshold"] == 35.5
    assert release["basis"]["test_groups"] == ["G-PE-018", "G-PE-004"]
    assert "threshold" not in release["basis"]
    metrics = load("metrics.json")
    assert set(metrics["validation"]) == set(metrics["test"]) == set(HORIZONS)
    assert metrics["test"]["6"]["decision_tree"]["mae"] == pytest.approx(
        7.012, abs=5e-4
    )
    manifest = load("manifest.json")
    data_sha = json.loads((SMOKESENSE_V1 / "manifest.json").read_text())["data_sha256"]
    assert manifest["dataset"]["data_sha256"] == data_sha
    assert manifest["versions"] == {**manifest["versions"], "sklearn_saved_with": "1.7.2",
                                    "sklearn_repo_pin": "1.6.0"}  # fmt: skip


@needs_release
@needs_dataset
def test_registry_read_metadata_accepts_the_package(package):
    registry = pytest.importorskip("mlops.registry")  # OPS-02, PR #68
    out, _ = package
    meta = registry.read_metadata(out)
    assert meta["feature_list"] == ml01.MODEL_FEATURES
    assert meta["thresholds"] == {h: 35.5 for h in HORIZONS}
    data_sha = json.loads((SMOKESENSE_V1 / "manifest.json").read_text())["data_sha256"]
    assert meta["training_data_hash"] == data_sha
    assert meta["hyperparameters"]["selected_hyperparameters"]["6"]["max_depth"] == 5

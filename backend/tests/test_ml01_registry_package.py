"""ml.tools.package_ml01_for_registry: the ML-01 trees as a registrable model directory."""

from __future__ import annotations

import json

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


@needs_release
def test_refuses_a_zip_that_does_not_match_the_checksum(tmp_path):
    bad = tmp_path / "bad.sha256"
    bad.write_text("0" * 64 + "  ml01-baselines-v1.0.0.zip\r\n")
    with pytest.raises(pkg.PackageError, match="sha256"):
        pkg.verify_release(RELEASE, ZIP, bad)


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
def test_package_files_exist_and_are_deterministic(package):
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
def test_registry_read_metadata_accepts_the_package(package):
    registry = pytest.importorskip("mlops.registry")
    out, _ = package
    meta = registry.read_metadata(out)
    assert meta["feature_list"] == ml01.MODEL_FEATURES
    assert meta["thresholds"] == {h: 35.5 for h in HORIZONS}
    data_sha = json.loads((SMOKESENSE_V1 / "manifest.json").read_text())["data_sha256"]
    assert meta["training_data_hash"] == data_sha
    assert meta["hyperparameters"]["selected_hyperparameters"]["6"]["max_depth"] == 5

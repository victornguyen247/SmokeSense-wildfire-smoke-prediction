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


def test_a_failed_write_leaves_the_previous_package(tmp_path, monkeypatch):
    release = tmp_path / "release"
    (release / "models").mkdir(parents=True)
    for name in pkg.MODEL_FILES:
        (release / name).write_bytes(b"tree")
    out = tmp_path / "ml01_decision_tree"
    pkg.write(out, release, {name: "old\n" for name in pkg.GENERATED})
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}

    rename = pkg.Path.rename

    def fail_into_place(self, target):
        if pkg.Path(target).resolve() == out.resolve() and self.name == "package":
            raise OSError("disk full")
        return rename(self, target)

    monkeypatch.setattr(pkg.Path, "rename", fail_into_place)
    with pytest.raises(OSError, match="disk full"):
        pkg.write(out, release, {name: "new\n" for name in pkg.GENERATED})
    after = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert after == before
    assert not out.with_name(out.name + ".old").exists()


def published(release, horizons):
    """CSVs in ML-01's layout for `horizons`, and metrics that match them exactly."""
    model = {"mae": 2.0, "rmse": 3.0, **{k: 0.5 for k in pkg.CLASSIFICATION.values()}}
    metrics = {
        split: {
            h: {
                "rows": 10,
                "positives_35_5": 4,
                "persistence": model,
                "decision_tree": model,
            }
            for h in HORIZONS
        }
        for split in ("validation", "test")
    }
    release.mkdir()
    (release / "validation_results.csv").write_text(
        "Horizon,Persistence MAE,Decision Tree MAE\n"
        + "".join(f"{h},2.0,2.0\n" for h in horizons)
    )
    (release / "test_results.csv").write_text(
        "Horizon,Samples,Persistence MAE,Tree MAE,Persistence RMSE,Tree RMSE,MAE Improvement %\n"
        + "".join(f"{h},10,2.0,2.0,3.0,3.0,0.0\n" for h in horizons)
    )
    (release / "test_classification.csv").write_text(
        "Horizon,Model,Positive Cases,Precision,Recall,F1,AUROC,AUPRC\n"
        + "".join(
            f"{h},{m},4,0.5,0.5,0.5,0.5,0.5\n"
            for h in horizons
            for m in ("Persistence", "Decision Tree")
        )
    )
    return metrics


def test_a_truncated_csv_stops_the_package(tmp_path):
    pkg.check_published(published(tmp_path / "full", HORIZONS), tmp_path / "full")
    metrics = published(tmp_path / "cut", HORIZONS[:-1])
    with pytest.raises(pkg.PackageError, match="24 h .*missing"):
        pkg.check_published(metrics, tmp_path / "cut")

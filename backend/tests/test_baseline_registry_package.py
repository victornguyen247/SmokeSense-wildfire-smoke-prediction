"""ml/tools/package_baseline_for_registry.py: registrable, deterministic baseline packages."""

from __future__ import annotations

import json

import pytest

from ml.datasets.load import SMOKESENSE_V1
from ml.tools import package_baseline_for_registry as pkg
from mlops.registry import read_metadata

HAVE_ARTIFACTS = (
    all(
        (pkg.MODELS / f"baseline_{m}" / "oof_predictions.parquet").is_file()
        for m in pkg.SPEC
    )
    and (SMOKESENSE_V1 / "manifest.json").is_file()
)
needs_artifacts = pytest.mark.skipif(
    not HAVE_ARTIFACTS, reason="DATA-04 artifacts not present"
)


def test_clean_replaces_nan_and_inf():
    out = pkg.clean({"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": 2}})
    assert out == {"a": None, "b": [1.0, None], "c": {"d": 2}}
    assert "NaN" not in pkg.dump(out)


def test_dataset_hash_mismatch_stops(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"data_sha256": "a" * 64}))
    with pytest.raises(pkg.PackageError, match="smokesense_v1 manifest"):
        pkg.check_dataset({"dataset": {"data_sha256": "b" * 64}}, tmp_path)


def test_write_refuses_folder_with_other_files(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    with pytest.raises(pkg.PackageError, match="other files"):
        pkg.write(tmp_path, {"release.json": (None, "{}")})


@needs_artifacts
@pytest.mark.parametrize("model", ["v1", "v2"])
def test_package_is_registrable_and_deterministic(model, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    pkg.write(a, pkg.build(model))
    pkg.write(b, pkg.build(model))
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir())
    assert all((a / n).read_bytes() == (b / n).read_bytes() for n in names)
    assert "oof_predictions.parquet" not in names
    assert {f"fallback_h{h}.json" for h in pkg.HORIZONS} <= set(names)

    meta = read_metadata(a)
    want = json.loads((SMOKESENSE_V1 / "manifest.json").read_text())["data_sha256"]
    assert meta["training_data_hash"] == want
    assert meta["feature_list"] == pkg.SPEC[model]["features"]
    assert set(meta["thresholds"]) == {str(h) for h in pkg.HORIZONS}
    assert "NaN" not in (a / "metrics.json").read_text()  # JSONB rejects NaN
    rel = json.loads((a / "release.json").read_text())
    assert {rel[str(h)]["serve"] for h in pkg.HORIZONS} <= pkg.SERVE_VALUES


@needs_artifacts
def test_v1_serves_persistence_and_records_rule():
    rel = json.loads(pkg.build("v1")["release.json"][1])
    assert {rel[str(h)]["serve"] for h in pkg.HORIZONS} == {"persistence"}
    assert {rel[str(h)]["threshold"] for h in pkg.HORIZONS} == {35.5}
    assert rel["12"]["rule_serve"] == "v1"  # decision #31 alone would ship v1 at 12 h
    assert "threshold" not in rel["basis"]

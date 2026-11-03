"""Package the ML-01 Decision Trees as a model directory the OPS-02 registry accepts.

    python -m ml.tools.package_ml01_for_registry [--out data/models/ml01_decision_tree]

ML-01's release ZIP (ml01-baselines-v1.0.0) has the five trees and Miaoqing's results but no
release.json or features.json, which mlops.registry.read_metadata requires. This writes, into
a git-ignored folder:

    models/decision_tree_{1,3,6,12,24}h.joblib   copied unchanged from the verified release
    features.json   the pipeline's column order (its own engineered features)
    params.json     the hyperparameters chosen on validation (model_metadata.json)
    metrics.json    validation and test metrics per horizon on ML-01's split
    manifest.json   dataset hash, source release and ZIP sha256, scikit-learn versions
    release.json    baseline_v2's schema; the release rule (ml/evaluation/release.py) on
                    ML-01's test split decides serve, threshold UNHEALTHY_SG (provisional)

Nothing is trained and no network is used. The script stops unless the ZIP's sha256 equals
the release's checksum file and every release file it reads is byte-identical to the ZIP
member, and each tree's hash is checked again right before it is unpickled. It also stops if
any published metric is missing or differs from the recomputed one. The generated JSON has
sorted keys and no timestamps: the same inputs give the same bytes, and re-running replaces
the folder (the previous package is kept until the new one is in place).

The package is a shadow-only reference (decision #44): not for serving.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.datasets.load import BACKEND, SMOKESENSE_V1, load_dataset, sha256
from ml.evaluation.metrics import UNHEALTHY_SG, scores
from ml.evaluation.release import release
from ml.feature_columns import FEATURES_V2, TARGET
from ml.inference import ml01_baselines as ml01

RELEASE_TAG = "ml01-baselines-v1.0.0"
HORIZONS = (1, 3, 6, 12, 24)
# ML-01's chronological group split (notebook section 3.4), checked against the data in build().
TRAIN_GROUPS = ["G-PE-006", "G-PE-016", "G-PE-011", "G-PE-003", "G-PE-010",
                "G-PE-020", "G-PE-001", "G-PE-002", "G-PE-015"]  # fmt: skip
VAL_GROUPS = ["G-PE-017", "G-PE-009"]
TEST_GROUPS = ["G-PE-018", "G-PE-004"]
METRICS = ("mae", "rmse", "precision_35_5", "recall_35_5", "f1_35_5", "auroc_35_5",
           "auprc_35_5")  # fmt: skip
RELEASE_DIR = BACKEND / "data" / "release"
OUT = BACKEND / "data" / "models" / "ml01_decision_tree"
REQUIREMENTS = BACKEND / "requirements.txt"
TOLERANCE = 1e-4  # recomputed vs published metrics
MODEL_FILES = [f"models/decision_tree_{h}h.joblib" for h in HORIZONS]
RESULT_FILES = [
    "model_metadata.json",
    "validation_results.csv",
    "test_results.csv",
    "test_classification.csv",
]
CLASSIFICATION = {"Precision": "precision_35_5", "Recall": "recall_35_5", "F1": "f1_35_5",
                  "AUROC": "auroc_35_5", "AUPRC": "auprc_35_5"}  # fmt: skip
GENERATED = [
    "features.json",
    "manifest.json",
    "metrics.json",
    "params.json",
    "release.json",
]
BASIS = {
    "split": "ML-01 chronological group split (first issue time): 9 train / 2 validation / 2 test",
    "train_groups": TRAIN_GROUPS,
    "validation_groups": VAL_GROUPS,
    "test_groups": TEST_GROUPS,
    "rows": "rows with pm25_lag_1h present (ML-01's evaluation rows)",
    "persistence": "pm25_lag_1h, clipped at 0 (ML-01's persistence)",
}


class PackageError(Exception):
    """The inputs are not the verified ML-01 release, or do not reproduce it."""


def dump(obj) -> str:
    """Deterministic JSON: sorted keys, no NaN (JSONB rejects it), trailing newline."""
    return json.dumps(obj, indent=1, sort_keys=True, allow_nan=False) + "\n"


def clean(value):
    """Floats rounded to 6 places, NaN/inf to None, recursively."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return round(float(value), 6) if math.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def expected_sha256(checksum_file: Path) -> str:
    """The hash in a `sha256sum` file (the release's has Windows line endings)."""
    text = checksum_file.read_bytes().decode("ascii", "replace")
    found = re.findall(r"\b[0-9a-f]{64}\b", text.lower())
    if len(found) != 1:
        raise PackageError(f"{checksum_file} does not hold exactly one sha256")
    return found[0]


def verify_release(
    release_dir: Path, zip_path: Path, checksum_file: Path
) -> tuple[str, dict[str, str]]:
    """The ZIP's sha256 (checked against the checksum file) and its trees' sha256s; every
    release file must match the ZIP."""
    if not zip_path.is_file() or not checksum_file.is_file():
        raise PackageError(
            f"need {zip_path.name} and {checksum_file.name} to verify the release"
        )
    want, got = expected_sha256(checksum_file), sha256(zip_path)
    if got != want:
        raise PackageError(f"{zip_path.name} sha256 {got} != checksum file {want}")
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        if names != set(MODEL_FILES + RESULT_FILES):
            raise PackageError(f"unexpected ZIP contents: {sorted(names)}")
        for name in MODEL_FILES + RESULT_FILES:
            path = release_dir / name
            if not path.is_file() or path.read_bytes() != archive.read(name):
                raise PackageError(
                    f"{path} is missing or differs from the verified ZIP"
                )
        trees = {
            name: hashlib.sha256(archive.read(name)).hexdigest() for name in MODEL_FILES
        }
    return got, trees


def load_trees(release_dir: Path, trees: dict[str, str]) -> dict:
    """{horizon: fitted pipeline}, each file re-hashed right before joblib unpickles it."""
    models = {}
    for h, name in zip(HORIZONS, MODEL_FILES):
        path = release_dir / name
        if sha256(path) != trees[name]:
            raise PackageError(f"{path} changed after the release was verified")
        models[h] = joblib.load(path)
    return models


def ml01_split(df: pd.DataFrame) -> dict[str, list[str]]:
    """Groups ordered by first issue time, as ML-01 orders them: 9 train / 2 val / rest test."""
    order = df.groupby("group_id")["issue_time"].min().sort_values().index.tolist()
    return {"train": order[:9], "val": order[9:11], "test": order[11:]}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def evaluation_rows(df: pd.DataFrame, groups: list[str], models: dict) -> pd.DataFrame:
    """ML-01's rows for these groups with persistence and decision_tree predictions."""
    rows = df[df["group_id"].isin(groups) & df["pm25_lag_1h"].notna()].copy()
    rows["persistence"] = np.nan
    rows["decision_tree"] = np.nan
    for h in HORIZONS:
        at = rows["horizon_hours"] == h
        rows.loc[at, "persistence"] = ml01.predict(rows[at], h, "persistence")
        # ml01.predict's tree branch, on the verified model instead of its cached load
        ml01.validate_input(rows[at], h)
        x = ml01.add_engineered_features(rows[at])[ml01.MODEL_FEATURES]
        pred = np.asarray(models[h].predict(x), dtype=float)
        if not np.isfinite(pred).all():
            raise PackageError(f"{h} h tree returned invalid predictions")
        rows.loc[at, "decision_tree"] = np.maximum(pred, 0)
    return rows


def split_metrics(rows: pd.DataFrame, threshold: float) -> dict:
    """{horizon: {"rows", "positives_35_5", model: {metric: value}}}."""
    out = {}
    for h in HORIZONS:
        at = rows[rows["horizon_hours"] == h]
        y = at[TARGET].to_numpy(float)
        out[str(h)] = {
            "rows": int(len(at)),
            "positives_35_5": int((y >= threshold).sum()),
        }
        for model in ("persistence", "decision_tree"):
            s = scores(y, at[model].to_numpy(float))
            out[str(h)][model] = {k: s[k] for k in METRICS}
    return out


def check_published(metrics: dict, release_dir: Path) -> None:
    """Every number ML-01 published for persistence and the tree, at every horizon, must be
    present and equal the recomputed one."""
    diffs = []

    def check(where: str, got: float, row: dict | None, column: str) -> None:
        want = (row or {}).get(column) or ""
        if not want.strip():
            diffs.append(f"{where}: missing")
        elif not math.isclose(got, float(want), abs_tol=TOLERANCE):
            diffs.append(f"{where}: {got:.6f} != {float(want):.6f}")

    val = {r["Horizon"]: r for r in read_csv(release_dir / "validation_results.csv")}
    test = {r["Horizon"]: r for r in read_csv(release_dir / "test_results.csv")}
    cls = {
        (r["Horizon"], r["Model"]): r
        for r in read_csv(release_dir / "test_classification.csv")
    }
    for h in map(str, HORIZONS):
        v, t = metrics["validation"][h], metrics["test"][h]
        for label, model in (
            ("Persistence", "persistence"),
            ("Decision Tree", "decision_tree"),
        ):
            check(
                f"validation {h} h {label} MAE",
                v[model]["mae"],
                val.get(h),
                f"{label} MAE",
            )
        check(f"test {h} h Samples", t["rows"], test.get(h), "Samples")
        for label, model in (("Persistence", "persistence"), ("Tree", "decision_tree")):
            for metric in ("MAE", "RMSE"):
                check(f"test {h} h {label} {metric}", t[model][metric.lower()],
                      test.get(h), f"{label} {metric}")  # fmt: skip
        gain = 100 * (1 - t["decision_tree"]["mae"] / t["persistence"]["mae"])
        check(f"test {h} h MAE Improvement %", gain, test.get(h), "MAE Improvement %")
        for label, model in (
            ("Persistence", "persistence"),
            ("Decision Tree", "decision_tree"),
        ):
            row = cls.get((h, label))
            check(
                f"test {h} h {label} Positive Cases",
                t["positives_35_5"],
                row,
                "Positive Cases",
            )
            for column, key in CLASSIFICATION.items():
                check(f"test {h} h {label} {column}", t[model][key], row, column)
    if diffs:
        raise PackageError(
            "recomputed metrics differ from ML-01's CSVs: " + "; ".join(diffs)
        )


def check_pipelines(models: dict, selected: dict) -> list[str]:
    """The fitted pipelines' column order; their tree settings must match model_metadata.json."""
    orders = set()
    for h, model in models.items():
        orders.add(tuple(model.feature_names_in_))
        tree = model.named_steps["regressor"].get_params()
        for key, value in selected[str(h)].items():
            if tree[key] != value:
                raise PackageError(
                    f"{h} h tree has {key}={tree[key]}, metadata says {value}"
                )
    if len(orders) != 1 or list(next(iter(orders))) != ml01.MODEL_FEATURES:
        raise PackageError(
            f"pipeline columns {sorted(orders)} != {ml01.MODEL_FEATURES}"
        )
    return list(ml01.MODEL_FEATURES)


def sklearn_pin() -> str | None:
    if not REQUIREMENTS.is_file():
        raise PackageError(
            f"{REQUIREMENTS} not found (manifest.json records its scikit-learn pin)"
        )
    found = re.search(r"^scikit-learn==(\S+)", REQUIREMENTS.read_text(), re.M)
    return found.group(1) if found else None


def release_json(test_rows: pd.DataFrame, threshold: float) -> dict:
    """The #31 rule on ML-01's test split, with `threshold` at every horizon."""
    rel = release(
        test_rows, "decision_tree", model_name="decision_tree", horizons=HORIZONS
    )
    for h in rel:
        rel[h]["threshold"] = threshold
    # No "threshold" key in basis: mlops.registry reads one from every value that has it.
    rel["basis"] = {**BASIS, "rule": "ml/evaluation/release.py (decision #31) on the test split",
                    "exceedance_cutoff": f"{threshold} µg/m³, provisional (ML-01)"}  # fmt: skip
    return rel


def build(
    release_dir: Path, zip_path: Path, checksum_file: Path, dataset: Path
) -> dict[str, str]:
    """{file name: JSON text} of the generated files."""
    zip_sha, trees = verify_release(release_dir, zip_path, checksum_file)
    pin = sklearn_pin()
    meta = json.loads((release_dir / "model_metadata.json").read_text())
    df, data_manifest = load_dataset(dataset)
    if data_manifest["data_sha256"] != meta["dataset_sha256"]:
        raise PackageError("the dataset is not the one ML-01 was trained on")
    split = ml01_split(df)
    want = {"train": TRAIN_GROUPS, "val": VAL_GROUPS, "test": TEST_GROUPS}
    if split != want:
        raise PackageError(f"ML-01's split did not reproduce: {split}")

    models = load_trees(release_dir, trees)
    features = check_pipelines(models, meta["selected_hyperparameters"])
    # One prediction pass over validation + test, split afterwards.
    rows = evaluation_rows(df, split["val"] + split["test"], models)
    test_rows = rows[rows["group_id"].isin(split["test"])]
    threshold = UNHEALTHY_SG  # the cut-off scores() uses for precision/recall/F1
    metrics = {
        "validation": split_metrics(
            rows[rows["group_id"].isin(split["val"])], threshold
        ),
        "test": split_metrics(test_rows, threshold),
    }
    check_published(metrics, release_dir)
    rel = release_json(test_rows, threshold)

    files = {
        "features.json": {
            "features": features,
            "engineered": list(ml01.ENGINEERED_FEATURES),
            "note": (
                "Column order of ML-01's fitted pipelines (SimpleImputer(median) + "
                "DecisionTreeRegressor); build inputs with ml.inference.ml01_baselines, not "
                "ml.features. pm25_change_1_3 equals FEATURES_V2's trend_1_3; pm25_change_3_6 "
                "(lag 3 h - lag 6 h) and pm25_short_avg (NaN-skipping mean of lags 1/3/6 h) are "
                "not in ml.feature_columns."
            ),
            "not_in_feature_columns": [f for f in features if f not in FEATURES_V2],
        },
        "params.json": {
            "model_type": meta["model_type"],
            "pipeline": [
                "SimpleImputer(strategy='median')",
                "DecisionTreeRegressor(random_state=42)",
            ],
            "selected_hyperparameters": meta["selected_hyperparameters"],
            "selection": f"chosen on validation groups {', '.join(VAL_GROUPS)} (ML-01)",
        },
        "metrics.json": {
            "basis": BASIS,
            "threshold": threshold,
            "source": (
                "ml.evaluation.metrics.scores on the verified release's trees; equal to ML-01's "
                f"validation_results.csv, test_results.csv and test_classification.csv within {TOLERANCE}"
            ),
            **metrics,
        },
        "manifest.json": {
            "model": "ml01_decision_tree",
            "status": "shadow-only reference (decision #44); not for serving",
            "dataset": {
                "name": data_manifest.get("name", meta["dataset_name"]),
                "version": data_manifest.get("version", meta["dataset_version"]),
                "data_sha256": data_manifest["data_sha256"],
            },
            "source": {
                "release_tag": RELEASE_TAG,
                "zip_sha256": zip_sha,
                "task": meta["task"],
                "author": meta["author"],
                "model_files_sha256": trees,
            },
            "versions": {
                "sklearn_saved_with": meta["sklearn_version"],
                "sklearn_repo_pin": pin,
                "note": "Loading under the pinned version warns (InconsistentVersionWarning); "
                "predictions reproduce ML-01's published metrics.",
            },
            "generated_by": "ml/tools/package_ml01_for_registry.py",
            "files": sorted(MODEL_FILES + GENERATED),
        },
        "release.json": rel,
    }
    used = {rel[h]["threshold"] for h in map(str, HORIZONS)} | {threshold, UNHEALTHY_SG}
    if used != {UNHEALTHY_SG}:
        raise PackageError(
            f"release.json, metrics.json and scores() thresholds differ: {used}"
        )
    return {name: dump(clean(obj)) for name, obj in files.items()}


def write(out: Path, release_dir: Path, generated: dict[str, str]) -> None:
    """Replace `out` with the package; refuses to delete a folder holding anything else."""
    out = out.resolve()
    if out == release_dir.resolve():
        raise PackageError("--out must not be the release folder")
    expected = set(MODEL_FILES + GENERATED)
    if out.exists():
        present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
        if not present <= expected:
            raise PackageError(
                f"{out} holds other files {sorted(present - expected)}; not replacing it"
            )
    old = out.with_name(out.name + ".old")
    if old.exists():
        raise PackageError(
            f"{old} is left from an interrupted run; restore or remove it"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        staging = Path(tmp) / "package"
        (staging / "models").mkdir(parents=True)
        for name in MODEL_FILES:
            shutil.copyfile(release_dir / name, staging / name)
        for name, text in generated.items():
            (staging / name).write_text(text)
        # Swap by rename: the previous package stays whole until the new one is in place.
        replacing = out.exists()
        if replacing:
            out.rename(old)
        try:
            staging.rename(out)
        except BaseException:
            if replacing:
                old.rename(out)
            raise
    if replacing:
        shutil.rmtree(old)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--release-dir",
        type=Path,
        default=ml01.DEFAULT_ARTIFACT_DIR,
        help="the extracted ML-01 release (default: data/models/ml01_baselines)",
    )
    ap.add_argument("--zip", type=Path, default=RELEASE_DIR / f"{RELEASE_TAG}.zip")
    ap.add_argument(
        "--checksum", type=Path, default=RELEASE_DIR / f"{RELEASE_TAG}.sha256"
    )
    ap.add_argument("--dataset", type=Path, default=SMOKESENSE_V1)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    try:
        generated = build(args.release_dir, args.zip, args.checksum, args.dataset)
        write(args.out, args.release_dir, generated)
    except PackageError as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    rel = json.loads(generated["release.json"])
    for h in map(str, HORIZONS):
        r = rel[h]
        print(
            f"h{h:>2}: serve {r['serve']}, pooled {r['pooled_skill']:+.4f}, macro {r['macro_skill']:+.4f}"
        )
    digest = hashlib.sha256(
        "".join(generated[n] for n in sorted(generated)).encode()
    ).hexdigest()
    print(f"wrote {args.out} (generated JSON sha256 {digest[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

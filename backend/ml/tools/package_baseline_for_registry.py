"""Package baseline_v1 or baseline_v2 as a model directory the OPS-02 registry accepts.

    python -m ml.tools.package_baseline_for_registry v2   # -> data/models/packaged/baseline_v2
    python -m ml.tools.package_baseline_for_registry v1   # -> data/models/packaged/baseline_v1

The DATA-04 folders (PR #39) are not registrable as they are: their metrics.json holds NaN,
which JSONB rejects, and baseline_v1 has no release.json. This writes, into a git-ignored
folder, only what serving needs (docs/ml/serving-contract.md §6), loadable by
ml.inference.predict_v2:

    v2  model_h*.json, fallback_h*.json, release.json, thresholds.json, features.json and
        params.json copied unchanged; metrics.json with NaN as null; manifest.json
    v1  fallback_h*.json = v1's model_h*.json unchanged (predict_v2 serves them when
        persistence is missing); features.json and params.json unchanged; metrics.json with
        NaN as null; manifest.json; a generated release.json that serves persistence at
        every horizon (decision #48)

oof_predictions.parquet and climatology.json are left out: nothing at inference reads them.
Nothing is trained and no network is used. The script stops unless the model's dataset hash
equals the smokesense_v1 manifest and the release skills recomputed from the out-of-fold
predictions match release.json (v2) or metrics.json (v1). The output has no timestamps:
the same inputs give the same bytes, and re-running replaces the folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

from ml.datasets.load import BACKEND, SMOKESENSE_V1, sha256
from ml.evaluation.metrics import UNHEALTHY_SG
from ml.evaluation.release import release
from ml.feature_columns import FEATURES, FEATURES_V2

HORIZONS = (1, 3, 6, 12, 24)
MODELS = BACKEND / "data" / "models"
OUT = MODELS / "packaged"
PERSISTENCE_THRESHOLD = (
    UNHEALTHY_SG  # where persistence is served (as baseline_v2's 1 h)
)
SERVE_VALUES = {"v2", "persistence"}  # what ml.inference.predict_v2 can serve
TOLERANCE = 1e-4  # release.json skills are rounded to 4 places
SPEC = {
    "v2": {
        "features": FEATURES_V2,
        "oof_column": "v2",
        # source file -> packaged file
        "copy": {
            **{f"model_h{h}.json": f"model_h{h}.json" for h in HORIZONS},
            **{f"fallback_h{h}.json": f"fallback_h{h}.json" for h in HORIZONS},
            **{
                n: n
                for n in (
                    "release.json",
                    "thresholds.json",
                    "features.json",
                    "params.json",
                )
            },
        },
    },
    "v1": {
        "features": FEATURES,
        "oof_column": "xgb_d4",
        "copy": {
            **{f"model_h{h}.json": f"fallback_h{h}.json" for h in HORIZONS},
            "features.json": "features.json",
            "params.json": "params.json",
        },
    },
}


class PackageError(Exception):
    """The source folder is not the DATA-04 model it claims to be."""


def dump(obj) -> str:
    """Deterministic JSON, no NaN (JSONB rejects it), trailing newline."""
    return json.dumps(obj, indent=1, allow_nan=False) + "\n"


def clean(value):
    """NaN and inf to None, recursively."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def read(path: Path):
    if not path.is_file():
        raise PackageError(f"missing {path}")
    return json.loads(path.read_text())


def check_dataset(manifest: dict, dataset: Path) -> str:
    """The dataset sha256 the model was trained on; must be smokesense_v1's."""
    want = read(dataset / "manifest.json")["data_sha256"]
    got = (manifest.get("dataset") or {}).get("data_sha256")
    if got != want:
        raise PackageError(
            f"model dataset sha256 {got} != smokesense_v1 manifest {want}"
        )
    if (dataset / "data.parquet").is_file() and sha256(
        dataset / "data.parquet"
    ) != want:
        raise PackageError(f"{dataset / 'data.parquet'} does not match its manifest")
    return want


def check_skills(got: dict, want: dict, where: str) -> None:
    for h in map(str, HORIZONS):
        for key in ("pooled_skill", "macro_skill"):
            if key in want[h] and not math.isclose(
                got[h][key], want[h][key], abs_tol=TOLERANCE
            ):
                raise PackageError(
                    f"{where} {h} h {key}: recomputed {got[h][key]} != {want[h][key]}"
                )


def v2_release(src: Path, rel: dict, oof: pd.DataFrame) -> dict:
    """release.json unchanged, after checking it against the out-of-fold predictions."""
    check_skills(release(oof, "v2", model_name="v2"), rel, "release.json")
    for h in map(str, HORIZONS):
        if rel[h]["serve"] not in SERVE_VALUES:
            raise PackageError(
                f"{src}/release.json serves {rel[h]['serve']!r} at {h} h"
            )
    return rel


def v1_release(src: Path, metrics: dict, oof: pd.DataFrame) -> dict:
    """Persistence at every horizon (decision #48), with v1's own #31 skills recorded."""
    by_h = metrics["persistence_rows"]["xgb_d4"]["by_horizon_hours"]
    rule = release(oof, "xgb_d4", model_name="v1")
    check_skills(
        rule, {h: {"pooled_skill": by_h[h]["skill"]} for h in by_h}, "metrics.json"
    )
    out = {
        h: {
            "serve": "persistence",
            "rule_serve": rule[h]["serve"],
            "pooled_skill": rule[h]["pooled_skill"],
            "macro_skill": rule[h]["macro_skill"],
            "threshold": PERSISTENCE_THRESHOLD,
        }
        for h in map(str, HORIZONS)
    }
    # No "threshold" key in basis: mlops.registry reads one from every value that has it.
    out["basis"] = {
        "generated_by": "ml/tools/package_baseline_for_registry.py",
        "rule": "ml/evaluation/release.py (decision #31) on baseline_v1's 13-fold "
        "out-of-fold xgb_d4 predictions; rule_serve is its verdict",
        "decision": "#48: serve persistence at every horizon. The card says v1 is not "
        "ready to replace persistence, and predict_v2 and forecasts.source have no "
        "value for a v1-served horizon. The v1 direct model runs only as the fallback "
        "when persistence is missing.",
    }
    return out


def build(model: str, models: Path = MODELS, dataset: Path = SMOKESENSE_V1) -> dict:
    """{packaged file name: (source path or None, generated text or None)}."""
    spec = SPEC[model]
    src = models / f"baseline_{model}"
    manifest = read(src / "manifest.json")
    data_sha = check_dataset(manifest, dataset)
    features = read(src / "features.json")
    if features.get("features") != spec["features"]:
        raise PackageError(
            f"{src}/features.json does not list the baseline_{model} features"
        )
    for name in spec["copy"]:
        if not (src / name).is_file():
            raise PackageError(f"missing {src / name}")
    metrics = read(src / "metrics.json")
    oof = pd.read_parquet(src / "oof_predictions.parquet")
    if model == "v2":
        rel = v2_release(src, read(src / "release.json"), oof)
        generated = {}
    else:
        rel = v1_release(src, metrics, oof)
        generated = {"release.json": dump(rel)}
    generated["metrics.json"] = dump(clean(metrics))

    files = sorted([*spec["copy"].values(), *generated, "manifest.json"])
    generated["manifest.json"] = dump(
        {
            **{k: v for k, v in manifest.items() if k != "files"},
            "files": files,
            "package": {
                "generated_by": "ml/tools/package_baseline_for_registry.py",
                "source": f"data/models/baseline_{model}",
                "training_data_hash": data_sha,
                "serve": {h: rel[h]["serve"] for h in map(str, HORIZONS)},
                "copied": {
                    out: {"from": name, "sha256": sha256(src / name)}
                    for name, out in sorted(spec["copy"].items())
                },
                "rewritten": {"metrics.json": "NaN as null"},
                "source_files": manifest.get("files"),
            },
        }
    )
    plan = {out: (src / name, None) for name, out in spec["copy"].items()}
    plan.update({name: (None, text) for name, text in generated.items()})
    return plan


def write(out: Path, plan: dict) -> None:
    """Replace `out` with the package; refuses to delete a folder holding anything else."""
    out = out.resolve()
    if out.exists():
        present = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
        if not present <= set(plan):
            raise PackageError(
                f"{out} holds other files {sorted(present - set(plan))}; not replacing it"
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        staging = Path(tmp) / "package"
        staging.mkdir()
        for name, (source, text) in plan.items():
            if source is not None:
                shutil.copyfile(source, staging / name)
            else:
                (staging / name).write_text(text)
        shutil.rmtree(out, ignore_errors=True)
        staging.rename(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("model", choices=sorted(SPEC))
    ap.add_argument("--models", type=Path, default=MODELS)
    ap.add_argument("--dataset", type=Path, default=SMOKESENSE_V1)
    ap.add_argument(
        "--out", type=Path, help="default: data/models/packaged/baseline_<model>"
    )
    args = ap.parse_args(argv)
    out = args.out or OUT / f"baseline_{args.model}"
    try:
        plan = build(args.model, args.models, args.dataset)
        write(out, plan)
    except PackageError as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    rel = json.loads((out / "release.json").read_text())
    for h in map(str, HORIZONS):
        r = rel[h]
        print(
            f"h{h:>2}: serve {r['serve']}, threshold {r['threshold']}, "
            f"pooled {r['pooled_skill']:+.4f}, macro {r['macro_skill']:+.4f}"
        )
    digest = hashlib.sha256()
    for name in sorted(plan):
        digest.update(name.encode() + b"\0" + (out / name).read_bytes())
    print(f"wrote {out} ({len(plan)} files, content sha256 {digest.hexdigest()[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

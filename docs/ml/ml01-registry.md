# ML-01 Decision Tree in the model registry

`backend/ml/tools/package_ml01_for_registry.py` (decision #44) turns the verified `ml01-baselines-v1.0.0` release into a model directory that `mlops.registry` accepts. Nothing is retrained and no network is used.

- **Checks:** it stops unless the ZIP's SHA-256 equals the `.sha256` file, every release file it reads is byte-identical to the ZIP member (only then are the pickles loaded), and the recomputed metrics equal ML-01's published CSVs within 1e-4.
- **Output:** the five `models/decision_tree_{1,3,6,12,24}h.joblib` copied unchanged, plus `features.json`, `params.json`, `metrics.json`, `manifest.json` and a `release.json` in baseline_v2's schema. The #31 rule on ML-01's test split (G-PE-018, G-PE-004) serves persistence at every horizon; threshold 35.5, provisional. The JSON has sorted keys and no timestamps, so a re-run gives the same bytes.

## Run

Inputs: the extracted release in `data/models/ml01_baselines/`, `data/release/ml01-baselines-v1.0.0.{zip,sha256}` and `smokesense_v1`.

```bash
cd backend
python -m ml.tools.package_ml01_for_registry      # -> data/models/ml01_decision_tree/ (git-ignored)
```

## Register (shadow only)

It is a reference baseline: never `promote` it.

```bash
python -m mlops.registry register data/models/ml01_decision_tree --name ml01_decision_tree \
    --version v1.0.0 --algorithm decision_tree --notes "ML-01 Baseline B reference; not for serving"
```

The trees were saved with scikit-learn 1.7.2 and the repo pins 1.6.0. Loading them warns (`InconsistentVersionWarning`), but the predictions still reproduce ML-01's numbers.

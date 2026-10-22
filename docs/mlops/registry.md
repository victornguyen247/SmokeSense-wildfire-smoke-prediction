# Model registry (OPS-02)

Store, version, promote and roll back models without MLflow. One CLI over the existing `model_versions` table (migration 0001, `thresholds` from 0004). No new migration.

```
python -m mlops.registry <register|promote|rollback|list|load> ...      # run from backend/
```

## Concepts

| | |
|---|---|
| Version | One model directory (`release.json`, `features.json`, per-horizon boosters, ...) stored as a single deterministic `.tar.gz`. `model_key = <name>/<version>`, e.g. `baseline/v2`. |
| Checksum | `model_versions.artifact_sha256` is the sha256 of the archive. It is checked on every load, and again before `promote` / `rollback` switch anything. A mismatch is an error; nothing is served or changed. |
| Immutable | A version is never overwritten. Fix a bad model by registering a new version. |
| Names | `--name` and `--version` use letters, digits, `.`, `_`, `-` only (no `/`, spaces or `..`). |

### Statuses

The issue talks about *candidate* and *active*; the table already has its own names and a unique index (`one_production`) that allows **at most one `production` row per `model_name`**. The CLI uses the table's names:

| Issue wording | `status` | Meaning |
|---|---|---|
| candidate | `shadow` | Registered, not serving |
| active | `production` | The version inference loads. The DB guarantees there is at most one. |
| (retired) | `retired` | Was production, replaced by a promote |

```
register ──► shadow ──promote──► production ──promote of another──► retired
                ▲                    │
                └──── rollback ──────┘   (the version rolled back from returns to shadow)
```

* `promote X` makes `X` production and retires the current production row in the same transaction.
* `rollback NAME` makes the **most recently retired** version production again. The version it replaces goes back to `shadow` (not `retired`), so running `rollback` again keeps walking back through history instead of flipping between two versions, and the bad version can still be inspected or re-promoted.
* Both lock the model's rows (`SELECT ... FOR UPDATE`), so two concurrent calls cannot both succeed.

## Backends

One switch, `REGISTRY_BACKEND`, picks where `register` writes. `load` follows each row's `artifact_uri`, so versions stay loadable whichever backend wrote them.

| Variable | Default | |
|---|---|---|
| `REGISTRY_BACKEND` | `local` | `local` or `s3` |
| `REGISTRY_LOCAL_DIR` | `data/registry` | local archives; relative paths are relative to `backend/`, wherever the CLI runs (git-ignored) |
| `REGISTRY_CACHE_DIR` | `data/registry_cache` | verified, extracted models, one folder per sha256 |
| `REGISTRY_S3_BUCKET` | `smoke-sense` | |
| `REGISTRY_S3_PREFIX` | `models` | objects are `models/<name>/<version>.tar.gz` |
| `REGISTRY_S3_ENDPOINT_URL` | empty | Cloudflare R2: `https://<account-id>.r2.cloudflarestorage.com` |

**Credentials are never in code or settings.** boto3 reads the standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables (for R2, the Access Key ID / Secret Access Key of an R2 API token).

## Cloudflare R2 setup (bucket `smoke-sense`)

R2 has no IAM policies; least privilege is the **API token's scope**.

1. Cloudflare dashboard → **R2** → create bucket `smoke-sense` (if it does not exist).
2. **R2 → Manage R2 API Tokens → Create API token**
   * Permission: **Object Read & Write**
   * Specify bucket: **`smoke-sense` only** (not "all buckets")
   * Optional: set a TTL, and restrict by client IP if the CI/runner IPs are fixed.
   * Do **not** use *Admin* tokens: the registry never creates, lists or deletes buckets.
3. Copy the Access Key ID and Secret Access Key (shown once) into your secret store, never into git. Note the account endpoint `https://<account-id>.r2.cloudflarestorage.com` from the token page.
4. Export for the shell or container that runs the CLI:

```bash
export REGISTRY_BACKEND=s3
export REGISTRY_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
export AWS_ACCESS_KEY_ID=...        # from the token
export AWS_SECRET_ACCESS_KEY=...
```

Use two tokens if you want read-only consumers: the serving/inference host only needs **Object Read only** on `smoke-sense`; only whoever registers models needs Read & Write.

The equivalent policy on plain AWS S3 (not needed for R2):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"],
     "Resource": "arn:aws:s3:::smoke-sense/models/*"}
  ]
}
```

## Registering baseline_v2

From `backend/`, with the database reachable (`make up` / `POSTGRES_*` in `.env`) and migrations applied (`make migrate`).

```bash
# 1. Register. Reads thresholds, features, params, metrics and the dataset hash from the directory.
python -m mlops.registry register data/models/baseline_v2 --name baseline --version v2 \
    --notes "ML-02 release, see docs/models/baseline_v2.md"

# 2. Check it is there as `shadow`.
python -m mlops.registry list --name baseline

# 3. Make it the serving version.
python -m mlops.registry promote baseline/v2

# 4. Something wrong? One command back to the previous production version.
python -m mlops.registry rollback baseline
```

What `register` copies from the directory into the row:

| Column | Source |
|---|---|
| `feature_list` | `features.json` → `features` (required) |
| `thresholds` | `release.json`, each horizon's `threshold` |
| `hyperparameters` | `params.json` |
| `backtest_metrics` | `metrics.json` |
| `training_data_hash` | `manifest.json` → `dataset.data_sha256` |
| `algorithm`, `training_data_uri`, `notes` | `--algorithm` (default `xgboost`), `--training-data-uri`, `--notes` |

`release.json` and `features.json` must exist, otherwise `register` stops before uploading anything.

## Loading (inference adapter, ML-04)

```python
from mlops.registry import build_registry

version, model_dir = build_registry().load_production("baseline")
# version.model_key == "baseline/v2"; model_dir is a verified local folder:
# predict_v2.predict(frame, horizon=6, model_dir=model_dir)
```

`load_production` downloads the archive if it is not cached, verifies its sha256, extracts it (regular files only; absolute paths and `..` are rejected), and returns the folder. The extracted files' hashes are recorded, and every later load re-checks them; a damaged cache is discarded and fetched again. `promote` and `rollback` download and verify *before* taking the database lock. The CLI equivalent prints that path: `python -m mlops.registry load baseline`.

## Failure modes

| Message | Cause / fix |
|---|---|
| `already registered` | Versions are immutable. Register a new version. |
| `checksum mismatch` | The stored object differs from what was registered. Do not use it; re-register from the source directory. |
| `nothing to roll back to` | No `retired` version exists for that name. |
| `no production version` | Nothing has been promoted yet. |
| `could not download` | Wrong endpoint/bucket/credentials, or the object was deleted. |

## Tests

`pytest tests/test_registry.py` needs no database. `tests/test_registry_db.py` exercises the Postgres code (including the `one_production` index) and is skipped unless `TEST_DATABASE_URL` points at a migrated database, e.g. a throwaway Neon branch.

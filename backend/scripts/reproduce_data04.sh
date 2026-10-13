#!/usr/bin/env bash
# Reproduce DATA-04 end to end from an already-ingested DB and check it against the
# canonical artifacts:
#   dataset build -> sha256 check -> train baseline v1 -> train baseline v2 -> metrics comparison
#
#   cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5433 scripts/reproduce_data04.sh
#
# Everything is written to data/repro/<timestamp>/ (gitignored); the canonical
# data/datasets/smokesense_v1/ and data/models/baseline_v{1,2}/ are only read. Exits non-zero
# on any failure or mismatch. Set PYTHON to override the interpreter (default .venv/bin/python).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
OUT="${REPRO_OUT:-data/repro/$(date +%Y%m%dT%H%M%S)}"
start=$(date +%s)
step() { echo; echo "=== $1 ($(( $(date +%s) - start ))s)"; }

step "1/5 build dataset -> $OUT/dataset"
"$PY" -m dataset_build.build_v1 --out "$OUT/dataset" | tail -1

step "2/5 dataset sha256 vs data/datasets/smokesense_v1/manifest.json"
"$PY" - "$OUT" <<'PY'
import json, sys
want = json.load(open("data/datasets/smokesense_v1/manifest.json"))["data_sha256"]
got = json.load(open(f"{sys.argv[1]}/dataset/manifest.json"))["data_sha256"]
print("match" if got == want else f"MISMATCH {got} != {want}")
sys.exit(0 if got == want else 1)
PY

step "3/5 train baseline v1"
"$PY" -m ml.training.train_baseline_v1 --data "$OUT/dataset" --out "$OUT/baseline_v1" | tail -1

step "4/5 train baseline v2"
"$PY" -m ml.training.train_baseline_v2 --data "$OUT/dataset" --v1 "$OUT/baseline_v1" --out "$OUT/baseline_v2" | tail -1

step "5/5 compare with canonical artifacts"
"$PY" scripts/compare_repro.py "$OUT"

echo; echo "total: $(( $(date +%s) - start ))s"

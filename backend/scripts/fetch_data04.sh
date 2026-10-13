#!/usr/bin/env bash
# Download the DATA-04 release (dataset + baseline models) and put the files where the code
# expects them:
#   backend/data/datasets/smokesense_v1/   (data.parquet, manifest.json)
#   backend/data/models/baseline_v1/, baseline_v2/
#
#   backend/scripts/fetch_data04.sh                 # dataset + models
#   backend/scripts/fetch_data04.sh --with-db       # also the local-DB dump (saved to data/release/, not restored)
#   backend/scripts/fetch_data04.sh --force         # overwrite existing local folders
#
# Needs the GitHub CLI (gh auth login). Steps: download with `gh release download`, check every
# file against SHA256SUMS.txt, unzip, then check data.parquet against the sha256 in its
# manifest.json. Exits non-zero on any failure. Override with DATA04_TAG, DATA04_REPO and
# DATA04_ROOT (default backend/data).
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${DATA04_TAG:-data04-v1.0.0}"
REPO="${DATA04_REPO:-victornguyen247/SmokeSense-wildfire-smoke-prediction}"
ROOT="${DATA04_ROOT:-data}"
WITH_DB=0 FORCE=0
for arg in "$@"; do
  case "$arg" in
    --with-db) WITH_DB=1 ;;
    --force) FORCE=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

for d in "$ROOT/datasets/smokesense_v1" "$ROOT/models/baseline_v1" "$ROOT/models/baseline_v2"; do
  if [ -e "$d" ] && [ "$FORCE" -ne 1 ]; then
    echo "$d already exists; rerun with --force to overwrite it" >&2; exit 1
  fi
done

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
files=(smokesense_v1.zip baseline_v1.zip baseline_v2.zip SHA256SUMS.txt)
patterns=(); for f in "${files[@]}"; do patterns+=(-p "$f"); done
[ "$WITH_DB" -eq 1 ] && patterns+=(-p "*.dump")

echo "downloading $TAG from $REPO"
gh release download "$TAG" -R "$REPO" -D "$TMP" "${patterns[@]}"

echo "checking SHA256SUMS.txt"
( cd "$TMP" && for f in *; do [ "$f" = SHA256SUMS.txt ] && continue
    grep -E "  $f\$" SHA256SUMS.txt > "$f.sum" || { echo "$f is not listed in SHA256SUMS.txt" >&2; exit 1; }
    if command -v sha256sum >/dev/null; then sha256sum -c "$f.sum"; else shasum -a 256 -c "$f.sum"; fi
  done )

mkdir -p "$ROOT/datasets" "$ROOT/models"
rm -rf "$ROOT/datasets/smokesense_v1" "$ROOT/models/baseline_v1" "$ROOT/models/baseline_v2"
unzip -q -o "$TMP/smokesense_v1.zip" -d "$ROOT/datasets/"
unzip -q -o "$TMP/baseline_v1.zip" -d "$ROOT/models/"
unzip -q -o "$TMP/baseline_v2.zip" -d "$ROOT/models/"
if [ "$WITH_DB" -eq 1 ]; then
  mkdir -p "$ROOT/release"; mv "$TMP"/*.dump "$ROOT/release/"
  echo "DB dump saved to $ROOT/release/ (restore: pg_restore -d <db> --no-owner <file>)"
fi

echo "checking data.parquet against manifest.json"
want="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['data_sha256'])" "$ROOT/datasets/smokesense_v1/manifest.json")"
got="$(sha256 "$ROOT/datasets/smokesense_v1/data.parquet" | cut -d' ' -f1)"
if [ "$got" != "$want" ]; then echo "data.parquet sha256 $got != manifest $want" >&2; exit 1; fi
echo "OK: smokesense_v1 ($got) and baseline_v1/v2 are in $ROOT/"

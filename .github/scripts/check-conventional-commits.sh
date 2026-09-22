#!/usr/bin/env bash
# Enforces the Conventional Commit format described in CONTRIBUTING.md.
#
# Checks every non-merge commit in the PR plus the PR title (the PR title becomes
# the commit subject when a PR is squash-merged, so both have to be valid).
#
# Env: BASE_SHA, HEAD_SHA, PR_TITLE (PR_TITLE is read from the environment, never
# interpolated into the script, so a crafted title cannot execute anything).
set -euo pipefail

TYPES='feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert|Feat|Fix|Chore|Docs|Refactor|Test|Perf|Build|Ci|Style|Revert'
PATTERN="^(${TYPES})(\([a-z0-9._/-]+\))?!?: .+"
MAX_SUBJECT=1000

failed=0

check() {
  local label="$1" subject="$2"
  if [[ ! "$subject" =~ $PATTERN ]]; then
    echo "::error::${label} is not a Conventional Commit: \"${subject}\""
    failed=1
    return
  fi
  if (( ${#subject} > MAX_SUBJECT )); then
    echo "::error::${label} subject is ${#subject} chars, keep it under ${MAX_SUBJECT}: \"${subject}\""
    failed=1
    return
  fi
  echo "ok: ${label} — ${subject}"
}

check "PR title" "${PR_TITLE}"

while IFS= read -r subject; do
  [[ -z "$subject" ]] && continue
  check "commit" "$subject"
done < <(git log --no-merges --pretty=%s "${BASE_SHA}..${HEAD_SHA}")

if (( failed )); then
  cat >&2 <<'MSG'

Expected format:  type: short, present-tense description
Allowed types:    feat, fix, chore, docs, refactor, test, perf, build, ci, style, revert
Examples:         feat: add PM2.5 prediction endpoint
                  fix(ingest): prevent duplicate FIRMS detections

Fix local commits with:  git rebase -i <base>   (reword the offending subjects)
See CONTRIBUTING.md section 2 for the full convention.
MSG
  exit 1
fi

echo "All commit subjects and the PR title follow Conventional Commits."

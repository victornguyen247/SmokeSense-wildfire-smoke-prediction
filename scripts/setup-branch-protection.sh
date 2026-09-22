#!/usr/bin/env bash
# Applies the branch protection rules agreed in CONTRIBUTING.md to `dev` and `prod`.
#
# Rules per branch:
#   - PRs only, no direct pushes
#   - 1 approving review, stale approvals dismissed on new commits
#   - CI must be green (all three required checks) and the branch up to date
#   - Conversations resolved before merge
#   - No force pushes, no branch deletion
#   - Rules apply to admins too
#
# Usage:  ./scripts/setup-branch-protection.sh [owner/repo]
# Needs:  gh CLI authenticated with admin rights on the repo (`gh auth login`,
#         scope `repo`). No token is stored in this repo.
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
CHECKS='["Conventional Commits","Backend (lint + test)","Frontend (lint + build)","Docker Compose (db + redis)"]'

protect() {
  local branch="$1"
  echo "Protecting ${REPO}@${branch} ..."
  gh api -X PUT "repos/${REPO}/branches/${branch}/protection" \
    -H "Accept: application/vnd.github+json" \
    --input - <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ${CHECKS}
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": false
}
JSON
  echo "  done."
}

for branch in dev prod; do
  if gh api "repos/${REPO}/branches/${branch}" >/dev/null 2>&1; then
    protect "$branch"
  else
    echo "  skipped: branch '${branch}' does not exist on ${REPO}" >&2
  fi
done

echo
echo "Current settings:"
for branch in dev prod; do
  gh api "repos/${REPO}/branches/${branch}/protection" \
    -q "\"${branch}: reviews=\" + (.required_pull_request_reviews.required_approving_review_count|tostring) + \" strict=\" + (.required_status_checks.strict|tostring) + \" checks=\" + (.required_status_checks.contexts|join(\",\"))" \
    2>/dev/null || true
done

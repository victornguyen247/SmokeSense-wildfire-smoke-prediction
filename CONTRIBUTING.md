# Contributing to SmokeSense

This document defines how our team works together on the codebase. The goal is to keep our work **consistent, reviewable, and easy for every teammate to understand** — including the person who joins the file three weeks from now.

Treat this as a **living guide**. If a rule slows us down without adding value, raise it and we change it together.

---

## 1. Team philosophy

Our engineering decisions should follow these principles:

- Prefer **clarity over cleverness**.
- Prefer **simple solutions first**; do not over-engineer prematurely.
- Optimize for **readability and maintainability**.
- Keep each function, file, and component **focused on one responsibility**.
- Extract reusable patterns **only after repetition is real**.

A good rule of thumb:

> First make it work clearly, then extract once repetition is real.

Because SmokeSense spans data engineering, ML, backend, frontend, and DevOps, one more principle matters here: **respect the layer boundaries** described in [docs/architecture.md](docs/architecture.md). Most bugs in a project like this come from code reaching across a boundary it shouldn't.

---

## 2. Git workflow

### Branch strategy

- **`prod`** — release branch. Only updated after testing is complete. Never commit directly.
- **`dev`** — main development branch. All feature work merges here first.
- Developers **branch from `dev`** and open pull requests back into `dev`.
- Any exception (for example, an urgent fix straight to `prod`) is discussed with the team beforehand.

```
prod    ← stable, tested releases only
 └── dev            ← integration branch, everyone merges here
      ├── feat/pm25-prediction-endpoint
      ├── fix/firms-timestamp-parsing
      └── chore/add-ci-workflow
```

### Branch naming

Branches follow this format, with the description in **kebab-case**:

```
type/short-description
```

Examples:

```
feat/city-history-endpoint
fix/wind-alignment-bearing
chore/update-dependencies
docs/architecture-overview
```

Common branch types:

| Type | Use for |
|---|---|
| `feat` | a new feature |
| `fix` | a bug fix |
| `chore` | dependencies, config, tooling, housekeeping |
| `docs` | documentation only |
| `refactor` | restructuring without changing behavior |
| `test` | adding or fixing tests only |

### Commit messages

Use the Conventional Commits format: a `type:` prefix and a short, present-tense description.

```
feat: add PM2.5 prediction endpoint
fix: prevent duplicate FIRMS detections on ingest
chore: pin xgboost and geopandas versions
docs: document the ML data-split rule
```

Keep the subject line under ~72 characters. Add a body below a blank line when the change needs explanation (what and why, not how).

Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `style`, `revert`. An optional scope is allowed: `fix(ingest): ...`.

**This is enforced by CI.** The `Conventional Commits` job checks every commit in the PR *and* the PR title (the title becomes the commit subject when a PR is squash-merged). If it fails, reword with `git rebase -i <base>` and force-push your branch.

---

## 3. Pull requests

**Every change goes through a pull request.** No direct commits to `dev` or `prod`.

### A PR must include

- **What changed** and **why** — a short description a teammate can understand without reading every line.
- **Testing instructions** — how the reviewer can verify it works (commands to run, endpoint to hit, screenshot for UI).
- **Linked scope** — reference the task/issue it addresses if we're tracking one.

### Merge requirements

A PR can merge into `dev` when **both** are true:

1. **At least one approval** from another teammate.
2. **CI is green** — all required checks pass. (See [Continuous integration](#5-continuous-integration).)

Both are enforced by branch protection on `dev` and `prod`: direct pushes are rejected, a new commit dismisses stale approvals, the branch must be up to date with its base, and conversations must be resolved. The rules apply to admins too.

Opening a PR fills in the [PR template](.github/pull_request_template.md) — keep the checklists and tick them as you go.

### PR size

PR size isn't hard-capped, but keep it **understandable in one sitting**. A 60-file PR that touches four layers is nearly impossible to review well. If a change is getting large, split it: land the data model, then the service, then the endpoint, then the UI.

### Keeping your branch current

Before asking for review, update your branch from `dev` so you resolve conflicts, not your reviewer:

```bash
git checkout dev
git pull
git checkout your-branch
git merge dev      # or: git rebase dev
```

---

## 4. Code review

Reviewing is a normal part of everyone's week, not an interruption. Aim to review open PRs within a day so nobody is blocked.

### Reviewers evaluate

- **Correctness** — does it do what the description says?
- **Readability** — will a teammate understand this in a month?
- **Layer placement** — is the code in the right layer? (routes thin, logic in services, ML in `ml/` — see [docs/architecture.md](docs/architecture.md).)
- **Duplication** — does this repeat something that already exists?
- **Tests** — are the testing instructions real and do they pass?

### Review questions worth asking

- Does a route contain business logic that belongs in a service?
- Does anything in `ml/` import from the web layer? (It must not.)
- Are PM2.5 / AQI thresholds read from the shared source, or hardcoded again?
- Did any random (non-time-based) data split sneak into model code?
- Would a new teammate understand where this lives and why?

Reviews are about the code, not the person. Ask questions, suggest, and approve generously once the bar is met.

---

## 5. Continuous integration

CI lives in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) and runs on every PR into `dev` or `prod`, and on pushes to those branches. All four jobs are required to merge:

| Check | What it does |
|---|---|
| `Conventional Commits` | Every commit subject and the PR title match the commit convention |
| `Backend (lint + test)` | `ruff check .` and `pytest` in `backend/` |
| `Frontend (lint + build)` | `npm run lint` and `npm run build` in `frontend/` |
| `Docker Compose (db + redis)` | Brings up Postgres+PostGIS and Redis and verifies PostGIS is enabled |

Dependencies are cached (pip and npm) so feedback stays fast, and a new push cancels the previous run on the same PR.

**Secrets** live in GitHub Actions secrets (repo → Settings → Secrets and variables → Actions), never in the workflow file or the repo. CI needs no API keys today; if a job ever does, reference it as `${{ secrets.NAME }}` and add a placeholder to `.env.example`.

Keeping CI green is a shared responsibility. If your change breaks it, fixing it is part of the change.

### Branch protection

The rules on `dev` and `prod` are scripted, not clicked, so they can be reviewed and re-applied:

```bash
gh auth login                        # needs admin rights on the repo
make protect                         # ./scripts/setup-branch-protection.sh
```

Re-run it whenever a required check is added or renamed — the check names in the script must match the job `name:` values in the workflow exactly, or the rule silently never matches.

---

## 6. Environment and secrets

- Never commit real secrets. `.env` is git-ignored; commit only `.env.example`.
- API keys (FIRMS, AirNow, PurpleAir) go in your local `backend/.env`. See [docs/data-sources.md](docs/data-sources.md) for where to get them.
- If you add a new config value, add it to `.env.example` with a placeholder in the same PR so teammates know it exists.

---

## 7. When you are unsure

Ask:

- Which layer should this belong to?
- Is this reusable, or am I duplicating something that exists?
- Am I splitting data by time, not randomly?
- Would another teammate understand this without me explaining it?
- Does this belong in a service, a route, or the ML code?

When in doubt, open a draft PR early and ask. A five-minute question beats a two-day wrong direction.

---

## Conclusion

These guidelines exist to help us build **consistent, maintainable software the whole team can improve together**. The goal is not perfection — it's a codebase that six people can move through confidently.

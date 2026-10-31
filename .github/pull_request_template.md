## What changed

<!-- A short description a teammate can understand without reading every line. -->

## Why

<!-- The problem this solves, or the task it unblocks. Link the issue: Closes #123 -->

## How to test

<!-- Commands to run, endpoint to hit, screenshot for UI. Be specific enough that a reviewer can verify it. -->

```bash
# e.g. make up && curl localhost:8000/health
```

## Author checklist

- [ ] Branch follows `type/short-description` and commits follow Conventional Commits
- [ ] Targets `dev` (or `prod` only for a discussed release/hotfix)
- [ ] Branch is up to date with `dev`
- [ ] Lint and tests pass locally (`make lint`, `make test`, `npm run lint` in `frontend/`)
- [ ] New config values added to the matching `.env.example` — no real secrets committed
- [ ] Docs updated if behavior, setup, or architecture changed

## Reviewer checklist

- [ ] **Correctness** — it does what the description says
- [ ] **Readability** — a teammate will understand this in a month
- [ ] **Layer placement** — routes thin, logic in services, ML in `ml/` (see [docs/architecture.md](../docs/architecture.md)); nothing in `ml/` imports the web layer
- [ ] **Duplication** — does not repeat something that already exists
- [ ] **Thresholds** — PM2.5 / AQI values read from the shared source, not hardcoded again
- [ ] **Data splits** — model code splits by time, never randomly
- [ ] **Tests** — the testing instructions are real and they pass

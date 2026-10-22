# Git workflow (always applies)

- **Never** run `git commit`, `git push`, `gh pr create`, `git checkout/switch`, `git stash`, `git reset`, or rebase/merge without the user's explicit OK in this conversation. Stage nothing by default. The user reviews files before every commit.
- When asked to commit: show `git status` and a proposed message first.
- Branches: `type/short-kebab-description` (`feat|fix|chore|docs|refactor|test`), cut from `dev`; PR into `dev`. Never commit to `dev` or `prod`.
- Commits and PR titles: Conventional Commits, `type(scope): subject`, ≤72 chars, present tense. Allowed types: feat fix chore docs refactor test perf build ci style revert. CI enforces it on every commit and the PR title.
- PR body follows `.github/pull_request_template.md` (what/why, how to test, linked task).
- Keep PRs reviewable in one sitting; split data model → service → endpoint → UI.
- Do not touch unrelated uncommitted changes in the working tree; never use `--no-verify` or force-push without being told.

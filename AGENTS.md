# Agent Instructions

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues for `jackson-simionato/sombreado-service`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default triage label vocabulary: `bug`, `enhancement`, `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context backend repo with a root `CONTEXT.md` and root `docs/adr/`. The public browser API is consumed by `sombreado-floripa`, so API-contract work should cross-reference the frontend contract when relevant. See `docs/agents/domain.md`.

## Engineering standards for coding agents

Coding agents must follow `docs/engineering-standards.md`.

### Branches and commits

- Branch from `develop` unless the user explicitly chooses a different base.
- Use branch names like `feat/12-short-slug`, `fix/18-short-slug`, `docs/21-short-slug`, `chore/24-short-slug`, or `refactor/30-short-slug`.
- Prefer small, coherent commits over one mixed changeset.
- Use lightweight Conventional Commit subjects such as `feat(routes): add route candidate hints`.
- Stage explicit paths. Do not use `git add .` when unrelated changes may exist.

### Completion checks

Before claiming implementation work is complete, run:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

Use focused tests first when useful, but the full commands above are the default completion gate.

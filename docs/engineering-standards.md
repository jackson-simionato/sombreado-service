# Engineering Standards

These standards keep changes small, reviewable, and easy to finish consistently. They apply to humans and coding agents working in this repository.

## Branches

Branch from `develop` unless the task explicitly targets another base.

Use:

```text
<type>/<issue-number>-<short-slug>
```

Preferred types:

- `feat` for user-facing or public API behavior.
- `fix` for bug fixes.
- `docs` for documentation-only changes.
- `chore` for tooling, dependencies, CI, or repo hygiene.
- `refactor` for behavior-preserving internal changes.

Examples:

- `feat/3-route-candidate-departure-hints`
- `feat/12-onboard-advisory-contract`
- `fix/18-validation-error-envelope`
- `docs/21-browser-api-contract-notes`
- `chore/24-ruff-pre-commit`

## Commits

Use lightweight Conventional Commit subjects:

```text
<type>(optional-scope): <imperative summary>
```

Examples:

- `feat(routes): add route candidate direction hints`
- `test(routes): cover hint deduplication order`
- `fix(config): validate route search limit bounds`
- `docs(contract): clarify browser route candidate response`
- `chore(ci): check ruff formatting in pull requests`

Keep commits coherent:

- One behavior change per commit.
- Keep docs-only changes separate when they are not required for the code to make sense.
- Keep mechanical formatting separate from behavior changes.
- Keep refactors separate from behavior changes unless the refactor is the smallest safe path to the behavior change.
- Stage explicit paths instead of using `git add .` when unrelated changes may exist.

Split commits when reviewers would ask different questions about different parts of the change. Good split points are schema/contract, service behavior, route wiring, tests, docs, and tooling.

## Local Workflow

Install dependencies:

```bash
uv sync
```

Install pre-commit hooks:

```bash
uv run pre-commit install
```

Before completing a change, run:

```bash
uv run ruff format .
uv run ruff check .
uv run python -m pytest -q
```

For changes with a narrow test surface, run focused tests first, then the full completion gate above.

## Formatting And Linting

Ruff is the only Python formatter, import sorter, and linter for this repository.

Use this order for local cleanup:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run ruff check .
```

Do not add Black, isort, Flake8, or overlapping formatters unless the team first documents a specific gap Ruff does not cover.

## Pre-Commit

The pre-commit configuration runs:

- `ruff --fix`
- `ruff-format`
- basic YAML, trailing-whitespace, and end-of-file checks

Run all hooks manually with:

```bash
uv run pre-commit run --all-files
```

Pre-commit is a local fast feedback tool. CI remains the authoritative gate.

## Pull Requests

PRs should be easy to review without reconstructing intent from chat.

Required:

- Link the GitHub issue when one exists.
- Summarize behavior changes, not just file changes.
- Include verification commands run locally.
- Keep unrelated cleanup out of the PR.
- Update `README.md`, `CONTEXT.md`, ADRs, or plan docs when public API behavior or domain language changes.
- Call out browser API contract impact when the change affects `sombreado-floripa`.

Suggested PR body:

```markdown
## Summary

-

## Verification

- [ ] `uv run ruff format .`
- [ ] `uv run ruff check .`
- [ ] `uv run python -m pytest -q`

## Notes

-
```

## CI

CI must run non-mutating checks:

```bash
uv run ruff format --check .
uv run ruff check .
uv run python -m pytest -q
docker build -t sombreado-service:${GITHUB_SHA} .
```

Do not add heavier gates such as type checking or coverage thresholds until the repository is ready to maintain them consistently.

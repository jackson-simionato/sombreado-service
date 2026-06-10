# Agent Instructions

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues for `jackson-simionato/sombreado-service`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default triage label vocabulary: `bug`, `enhancement`, `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context backend repo with a root `CONTEXT.md` and root `docs/adr/`. The public browser API is consumed by `sombreado-floripa`, so API-contract work should cross-reference the frontend contract when relevant. See `docs/agents/domain.md`.

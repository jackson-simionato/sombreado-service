# Production Promote via environment approval

## Status

Accepted.

## Decision

Release to production uses **Production Promote**: a manual `workflow_dispatch` that waits for GitHub Environment `production` approval, then creates a `develop`→`main` PR, waits for CI, and auto-merges it. Humans do not use that PR as a review gate. `main` stays the production tip; existing CI on `main` still triggers the **Render Deployment** Deploy Hook. Branch protection on `main` blocks direct pushes and requires CI; it does not require human PR review for promote.

### Why

A manual `develop`→`main` review PR is git ceremony, not a production decision. We want the Azure-style shape (approve that production may advance → agent merges) on GitHub: the human gate is Environment approval; the PR is an audit receipt.

### Considered options

- Keep human-reviewed `develop`→`main` PRs as the release gate — rejected: duplicates work already done on `develop` and conflates merge approval with release approval.
- Fast-forward push `develop`→`main` after Environment approval — rejected: we want an explicit PR in history for audit/linking, even without human review.
- Deploy straight from `develop` (or drop `main` as promote target) — rejected: **Render Deployment** and current CI already key off `main`.
- Required human review on the promote PR as well as Environment approval — rejected: reintroduces the original ceremony.

### Out of scope

Dedicated hotfix-to-`main` policy; implement only if production emergencies need a bypass of `develop`.

## Consequences

- Operators promote with Actions → **Run workflow** on `Production Promote`, then approve the `production` Environment deployment — not by opening a release PR by hand.
- Pipeline Secret `PROMOTE_GITHUB_TOKEN` (PAT/fine-grained: Contents + Pull requests) is required so the promote PR and merge trigger CI. `GITHUB_TOKEN` alone does not start new workflow runs, so it cannot satisfy “CI on the PR, then CI+Deploy Hook on `main`”.
- `main` is branch-protected: no direct pushes, PR required, CI status required, no required human review (so the agent can merge after checks).
- Repo auto-merge may be enabled as convenience; the workflow waits for checks and merges explicitly.
- Promote is a no-op when `develop` has no commits ahead of `main` (tips may still differ because prior promotes add merge commits on `main`). Do not require `main` to be a strict ancestor of `develop`.
- Workflow: `.github/workflows/promote.yml`. Glossary term: **Production Promote** in `CONTEXT.md`.

# Domain Docs

This is a single-context backend repo.

## Before Exploring

Read:

- `CONTEXT.md` at the repo root for the Sombreado Service glossary.
- Relevant ADRs under `docs/adr/`.
- `docs/plans/` when the task refers to active plan work.

If a file is missing, proceed silently. Do not create domain docs upfront; `/grill-with-docs` creates them lazily when terms or decisions are settled.

## Frontend Contract

Sombreado Service serves the `sombreado-floripa` browser frontend. For public browser API work, cross-reference the frontend contract in the sibling repo when available:

- `../sombreado-floripa/docs/api-contract.md`
- `../sombreado-floripa/docs/plans/05-api-integration.md`

Backend implementation still belongs in this repo. Do not implement frontend behavior here.

## Vocabulary

Use the glossary terms in `CONTEXT.md` when naming issues, PRDs, tests, hypotheses, and implementation notes. Do not drift to terms the glossary marks as `_Avoid_`.

If a required concept is missing from the glossary, note it for `/grill-with-docs` rather than inventing competing language.

## ADR Conflicts

If a proposed issue, PRD, or implementation path contradicts an ADR, surface the contradiction explicitly and explain why reopening the decision may be warranted.

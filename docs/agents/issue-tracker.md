# Issue Tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in `jackson-simionato/sombreado-service`. Use the `gh` CLI for issue operations from inside this repository.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`
- **Read an issue**: `gh issue view <number> --comments`
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments`
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply or remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close an issue**: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` does this automatically when run inside the clone.

## Publishing

When a skill says "publish to the issue tracker", create a GitHub issue in this repo.

When a skill says "fetch the relevant ticket", run `gh issue view <number> --comments`.

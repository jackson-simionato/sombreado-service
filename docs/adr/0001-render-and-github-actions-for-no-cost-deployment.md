# Render and GitHub Actions for No-Cost Deployment

We will use GitHub Actions for CI/CD on the public repository and Render Free for the first runtime target. GitHub Actions will run lint, tests, and Docker image build validation, then trigger Render deployment from `main` only after CI passes; it will not push images to a registry yet. This keeps the no-cost workflow portable enough to migrate later, while accepting Render Free cold starts as an appropriate hobby-app trade-off.

GitHub Actions may hold pipeline secrets such as a Render deploy hook. Runtime secrets belong with the running service. The passenger API datastore is `SQLITE_DATABASE_PATH` (Generation Store). Legacy `DATABASE_URL` / PostGIS reader-role settings are not part of the passenger runtime path.

**Superseded runtime target:** production hosting is the Oracle Always Free VM topology in ADR 0004. GitHub Actions remains the CI/CD driver; the post-CI deploy step syncs a release to the VM instead of triggering Render.

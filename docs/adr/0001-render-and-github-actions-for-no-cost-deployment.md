# Render and GitHub Actions for No-Cost Deployment

We will use GitHub Actions for CI/CD on the public repository and Render Free for the first runtime target. GitHub Actions will run lint, tests, and Docker image build validation, then trigger Render deployment from `main` only after CI passes; it will not push images to a registry yet. This keeps the no-cost workflow portable enough to migrate later, while accepting Render Free cold starts as an appropriate hobby-app trade-off.

GitHub Actions may hold pipeline secrets such as a Render deploy hook. Runtime secrets belong with the running service.

**Historical note:** ADR 0004 temporarily superseded the Render Free *runtime target* with an Oracle Always Free VM. Production hosting is again Render Free + Neon under ADR 0005 (Deploy Hook after CI; scrape on Actions). The passenger API datastore is Neon `DATABASE_URL`, not `SQLITE_DATABASE_PATH`.

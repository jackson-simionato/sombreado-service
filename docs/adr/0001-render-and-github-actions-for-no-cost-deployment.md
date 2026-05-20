# Render and GitHub Actions for No-Cost Deployment

We will use GitHub Actions for CI/CD on the public repository and Render Free for the first runtime target. GitHub Actions will run lint, tests, and Docker image build validation, then trigger Render deployment from `main` only after CI passes; it will not push images to a registry yet. This keeps the no-cost workflow portable enough to migrate later, while accepting Render Free cold starts as an appropriate hobby-app trade-off.

GitHub Actions may hold pipeline secrets such as a Render deploy hook. Render remains the home for runtime secrets such as `DATABASE_URL`, because the running service needs those values and CI should not connect to the scraper database.

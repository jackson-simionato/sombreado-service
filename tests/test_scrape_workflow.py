"""Actions scrape schedule contract (#72)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRAPE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scrape.yml"
RENDER_BLUEPRINT = REPO_ROOT / "render.yaml"


def test_scrape_workflow_schedules_full_scrape_against_neon_pipeline_secret():
    workflow = SCRAPE_WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "cron:" in workflow
    assert "timezone:" in workflow
    assert "America/Sao_Paulo" in workflow
    assert "workflow_dispatch:" in workflow

    assert "secrets.DATABASE_URL" in workflow
    assert "uv sync --frozen" in workflow
    assert "sombreado-scrape scrape" in workflow
    assert "--force" in workflow

    assert "timeout-minutes: 20" in workflow
    assert "concurrency:" in workflow
    assert "sombreado-scrape" in workflow
    assert "cancel-in-progress: false" in workflow

    # Non-zero scrape exit must fail the job (Actions notifies repo watchers).
    assert "continue-on-error:" not in workflow


def test_scrape_is_not_scheduled_on_render():
    """Scrape stays on Actions; a Render Blueprint must not invoke the scrape CLI."""
    if not RENDER_BLUEPRINT.exists():
        return
    blueprint = RENDER_BLUEPRINT.read_text(encoding="utf-8")
    assert "sombreado-scrape" not in blueprint

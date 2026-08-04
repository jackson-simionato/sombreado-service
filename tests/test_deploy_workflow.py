"""Actions → Render Deploy Hook contract (#68 / ADR 0005)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_deploys_via_render_deploy_hook_after_ci_on_main():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "needs: ci" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "secrets.RENDER_DEPLOY_HOOK_URL" in workflow
    assert "curl -fsS --connect-timeout 10 --max-time 30" in workflow
    assert "&ref=${RELEASE_SHA}" in workflow
    assert "?ref=${RELEASE_SHA}" in workflow
    assert "RELEASE_SHA" in workflow

    assert "concurrency:" in workflow
    assert "sombreado-render-deploy" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "ALLOW_SKIP_DEPLOY" in workflow
    assert "exit 1" in workflow

    # Oracle VM SSH/rsync activate is not the production deploy happy path.
    assert "VM_SSH_KNOWN_HOSTS" not in workflow
    assert "sombreado-vm-deploy" not in workflow
    assert "sombreado-deploy-release" not in workflow
    assert "rsync" not in workflow

"""Contracts for Oracle VM deploy + systemd runtime units (#42)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-release.sh"
SYSTEMD_DIR = REPO_ROOT / "deploy" / "systemd"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _seed_release_tree(release_dir: Path) -> None:
    """Minimal release contents the deploy script expects after rsync."""
    release_dir.mkdir(parents=True)
    (release_dir / "pyproject.toml").write_text("[project]\nname='sombreado-service'\n", encoding="utf-8")
    (release_dir / "uv.lock").write_text("# lock\n", encoding="utf-8")
    shutil.copytree(SYSTEMD_DIR, release_dir / "deploy" / "systemd")
    env_example = REPO_ROOT / "deploy" / "env.example"
    if env_example.exists():
        shutil.copy(env_example, release_dir / "deploy" / "env.example")


def test_deploy_release_script_exists_and_is_executable():
    assert DEPLOY_SCRIPT.is_file()
    assert os.access(DEPLOY_SCRIPT, os.X_OK)


def test_deploy_flips_symlink_restarts_api_and_preserves_data_dir(tmp_path: Path):
    root = tmp_path / "opt" / "sombreado"
    data_root = tmp_path / "var" / "lib" / "sombreado"
    unit_dir = tmp_path / "etc" / "systemd" / "system"
    env_file = tmp_path / "etc" / "sombreado" / "env"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "systemctl.log"

    release_sha = "abc123def456"
    release_dir = root / "releases" / release_sha
    _seed_release_tree(release_dir)

    data_root.mkdir(parents=True)
    sentinel = data_root / "routes.sqlite"
    sentinel.write_text("durable-db", encoding="utf-8")
    env_file.parent.mkdir(parents=True)
    env_file.write_text("SQLITE_DATABASE_PATH=/var/lib/sombreado/routes.sqlite\n", encoding="utf-8")

    _write_executable(
        bin_dir / "systemctl",
        f"#!/bin/sh\necho \"$@\" >> '{log}'\n",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/bin/sh\nmkdir -p .venv/bin\ntouch .venv/bin/uvicorn .venv/bin/sombreado-scrape\n",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "SOMBREADO_ROOT": str(root),
            "SOMBREADO_DATA_ROOT": str(data_root),
            "SOMBREADO_UNIT_DIR": str(unit_dir),
            "SOMBREADO_ENV_FILE": str(env_file),
            "RELEASE_SHA": release_sha,
            "SYSTEMCTL": str(bin_dir / "systemctl"),
            "UV": str(bin_dir / "uv"),
        }
    )

    result = subprocess.run(
        [str(DEPLOY_SCRIPT)],
        cwd=str(release_dir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    current = root / "current"
    assert current.is_symlink()
    assert current.resolve() == release_dir.resolve()
    assert sentinel.read_text(encoding="utf-8") == "durable-db"
    assert data_root.is_dir()
    assert not any(path.name == "routes.sqlite" for path in root.rglob("routes.sqlite") if path != sentinel)

    unit_names = {
        "sombreado-api.service",
        "sombreado-scrape.service",
        "sombreado-scrape.timer",
        "sombreado-backup.service",
        "sombreado-backup.timer",
    }
    assert unit_names <= {path.name for path in unit_dir.iterdir()}

    systemctl_log = log.read_text(encoding="utf-8")
    assert "daemon-reload" in systemctl_log
    assert "enable --now sombreado-api.service" in systemctl_log
    assert "enable --now sombreado-scrape.timer" in systemctl_log
    assert "enable --now sombreado-backup.timer" in systemctl_log
    assert "restart sombreado-api.service" in systemctl_log


def test_deploy_refuses_to_delete_existing_data_directory():
    """Regression guard: deploy may prune old releases, never the durable data root."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "SOMBREADO_DATA_ROOT" in script
    assert 'rm -rf "${SOMBREADO_DATA_ROOT}' not in script
    assert "rm -rf ${SOMBREADO_DATA_ROOT}" not in script
    assert "mkdir -p" in script
    # Durable path must be created in place, not replaced via rm+mkdir.
    assert "never delete" in script.lower() or "never deleted" in script.lower()


def test_systemd_units_point_at_release_symlink_and_durable_sqlite():
    api = (SYSTEMD_DIR / "sombreado-api.service").read_text(encoding="utf-8")
    scrape = (SYSTEMD_DIR / "sombreado-scrape.service").read_text(encoding="utf-8")
    backup = (SYSTEMD_DIR / "sombreado-backup.service").read_text(encoding="utf-8")
    scrape_timer = (SYSTEMD_DIR / "sombreado-scrape.timer").read_text(encoding="utf-8")
    backup_timer = (SYSTEMD_DIR / "sombreado-backup.timer").read_text(encoding="utf-8")

    for unit in (api, scrape, backup):
        assert "EnvironmentFile=/etc/sombreado/env" in unit
        assert "EnvironmentFile=-/etc/sombreado/env" not in unit
        assert "WorkingDirectory=/opt/sombreado/current" in unit
        assert "ReadWritePaths=/var/lib/sombreado" in unit

    assert "uvicorn sombreado.api.main:app" in api
    assert "WantedBy=multi-user.target" in api
    assert "Restart=on-failure" in api

    assert "sombreado-scrape scrape" in scrape
    assert "Type=oneshot" in scrape
    assert "TimeoutStartSec=20min" in scrape

    assert "sombreado-scrape backup" in backup
    assert "Type=oneshot" in backup

    assert "OnCalendar=" in scrape_timer
    assert "Unit=sombreado-scrape.service" in scrape_timer
    assert "OnCalendar=" in backup_timer
    assert "Unit=sombreado-backup.service" in backup_timer


def test_env_example_keeps_sqlite_outside_release_tree():
    env_example = (REPO_ROOT / "deploy" / "env.example").read_text(encoding="utf-8")
    assert "SQLITE_DATABASE_PATH=/var/lib/sombreado/routes.sqlite" in env_example
    assert "/opt/sombreado" not in env_example.split("SQLITE_DATABASE_PATH", 1)[1].splitlines()[0]

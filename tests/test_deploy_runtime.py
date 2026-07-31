"""Contracts for Oracle VM deploy + systemd runtime units (#42)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-release.sh"
ACTIVATOR_SCRIPT = DEPLOY_DIR / "sombreado-deploy-release"
BOOTSTRAP_SCRIPT = DEPLOY_DIR / "bootstrap-vm.sh"
SYSTEMD_DIR = DEPLOY_DIR / "systemd"


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
    env_example = DEPLOY_DIR / "env.example"
    if env_example.exists():
        shutil.copy(env_example, release_dir / "deploy" / "env.example")


def test_deploy_scripts_exist_and_are_executable():
    for path in (DEPLOY_SCRIPT, ACTIVATOR_SCRIPT, BOOTSTRAP_SCRIPT):
        assert path.is_file()
        assert os.access(path, os.X_OK)


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

    # Older release pruned after KEEP_RELEASES=1; data root sentinel must survive.
    old_release = root / "releases" / "0000000old"
    old_release.mkdir(parents=True)
    (old_release / "marker").write_text("old", encoding="utf-8")

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
    _write_executable(bin_dir / "curl", "#!/bin/sh\nexit 0\n")

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
            "CURL": str(bin_dir / "curl"),
            "KEEP_RELEASES": "1",
            "HEALTH_TIMEOUT_SECONDS": "5",
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
    assert not old_release.exists()
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


def test_deploy_fails_when_health_check_never_succeeds(tmp_path: Path):
    root = tmp_path / "opt" / "sombreado"
    data_root = tmp_path / "var" / "lib" / "sombreado"
    unit_dir = tmp_path / "etc" / "systemd" / "system"
    env_file = tmp_path / "etc" / "sombreado" / "env"
    bin_dir = tmp_path / "bin"

    release_sha = "deadbeef01"
    release_dir = root / "releases" / release_sha
    _seed_release_tree(release_dir)
    data_root.mkdir(parents=True)
    env_file.parent.mkdir(parents=True)
    env_file.write_text("SQLITE_DATABASE_PATH=/var/lib/sombreado/routes.sqlite\n", encoding="utf-8")

    _write_executable(bin_dir / "systemctl", "#!/bin/sh\nexit 0\n")
    _write_executable(
        bin_dir / "uv",
        "#!/bin/sh\nmkdir -p .venv/bin\ntouch .venv/bin/uvicorn .venv/bin/sombreado-scrape\n",
    )
    _write_executable(bin_dir / "curl", "#!/bin/sh\nexit 1\n")

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
            "CURL": str(bin_dir / "curl"),
            "HEALTH_TIMEOUT_SECONDS": "1",
        }
    )

    result = subprocess.run(
        [str(DEPLOY_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "API health check failed" in result.stderr


def test_activator_rejects_invalid_sha_and_execs_root_owned_script(tmp_path: Path):
    lib = tmp_path / "lib"
    sbin_log = tmp_path / "deploy.log"
    lib.mkdir()
    _write_executable(
        lib / "deploy-release.sh",
        f"#!/bin/sh\necho \"sha=$RELEASE_SHA\" > '{sbin_log}'\n",
    )

    env = os.environ.copy()
    env["SOMBREADO_DEPLOY_LIB"] = str(lib)

    bad = subprocess.run(
        [str(ACTIVATOR_SCRIPT), "../evil"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "invalid RELEASE_SHA" in bad.stderr

    good = subprocess.run(
        [str(ACTIVATOR_SCRIPT), "abc1234"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert good.returncode == 0, good.stdout + good.stderr
    assert sbin_log.read_text(encoding="utf-8").strip() == "sha=abc1234"


def test_bootstrap_installs_fixed_activator_and_safe_sudoers(tmp_path: Path):
    root = tmp_path / "opt" / "sombreado"
    data_root = tmp_path / "var" / "lib" / "sombreado"
    env_dir = tmp_path / "etc" / "sombreado"
    sbin = tmp_path / "usr" / "local" / "sbin"
    lib = tmp_path / "usr" / "local" / "lib" / "sombreado"
    sudoers = tmp_path / "etc" / "sudoers.d" / "sombreado-deploy"
    deploy_user = os.environ.get("USER") or "jackson"

    env = os.environ.copy()
    env.update(
        {
            "REQUIRE_ROOT": "0",
            "SOMBREADO_MANAGE_USER": "0",
            "SOMBREADO_ROOT": str(root),
            "SOMBREADO_DATA_ROOT": str(data_root),
            "SOMBREADO_ENV_DIR": str(env_dir),
            "SOMBREADO_SBIN": str(sbin),
            "SOMBREADO_DEPLOY_LIB": str(lib),
            "SUDOERS_FILE": str(sudoers),
            "DEPLOY_USER": deploy_user,
        }
    )

    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    activator = sbin / "sombreado-deploy-release"
    installed_deploy = lib / "deploy-release.sh"
    assert activator.is_file() and os.access(activator, os.X_OK)
    assert installed_deploy.is_file() and os.access(installed_deploy, os.X_OK)

    sudoers_text = sudoers.read_text(encoding="utf-8")
    assert str(activator) in sudoers_text
    assert "NOPASSWD:" in sudoers_text
    assert "/opt/sombreado/releases/" not in sudoers_text
    assert sudoers.stat().st_mode & 0o777 == 0o440

    releases_mode = (root / "releases").stat().st_mode & 0o7777
    assert releases_mode == 0o2775

    env_file = env_dir / "env"
    assert env_file.is_file()
    assert env_file.stat().st_mode & 0o777 == 0o640

    # Re-run keeps existing env content.
    env_file.write_text("CUSTOM=1\n", encoding="utf-8")
    again = subprocess.run([str(BOOTSTRAP_SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert again.returncode == 0, again.stdout + again.stderr
    assert env_file.read_text(encoding="utf-8") == "CUSTOM=1\n"


def test_deploy_does_not_rm_data_root_path():
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'rm -rf "${SOMBREADO_DATA_ROOT}' not in script
    assert "rm -rf ${SOMBREADO_DATA_ROOT}" not in script


def test_systemd_units_point_at_release_symlink_and_harden_filesystem():
    api = (SYSTEMD_DIR / "sombreado-api.service").read_text(encoding="utf-8")
    scrape = (SYSTEMD_DIR / "sombreado-scrape.service").read_text(encoding="utf-8")
    backup = (SYSTEMD_DIR / "sombreado-backup.service").read_text(encoding="utf-8")
    scrape_timer = (SYSTEMD_DIR / "sombreado-scrape.timer").read_text(encoding="utf-8")
    backup_timer = (SYSTEMD_DIR / "sombreado-backup.timer").read_text(encoding="utf-8")

    for unit in (api, scrape, backup):
        assert "EnvironmentFile=/etc/sombreado/env" in unit
        assert "EnvironmentFile=-/etc/sombreado/env" not in unit
        assert "WorkingDirectory=/opt/sombreado/current" in unit
        assert "ProtectSystem=strict" in unit
        assert "PrivateTmp=yes" in unit
        assert "NoNewPrivileges=yes" in unit
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
    env_example = (DEPLOY_DIR / "env.example").read_text(encoding="utf-8")
    assert "SQLITE_DATABASE_PATH=/var/lib/sombreado/routes.sqlite" in env_example
    assert "/opt/sombreado" not in env_example.split("SQLITE_DATABASE_PATH", 1)[1].splitlines()[0]


def test_ci_pins_known_hosts_and_uses_fixed_activator():
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "VM_SSH_KNOWN_HOSTS" in workflow
    assert "ssh-keyscan" not in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "/usr/local/sbin/sombreado-deploy-release" in workflow
    assert "/opt/sombreado/releases/${RELEASE_SHA}/deploy/deploy-release.sh" not in workflow

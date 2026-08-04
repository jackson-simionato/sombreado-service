# Oracle VM systemd runtime and Actions deploy

We run production on one Oracle Always Free VM: systemd `sombreado-api` (start on boot, restart on failure), daily scrape and backup timers invoking `sombreado-scrape`, and a durable SQLite **Generation Store** under `/var/lib/sombreado/` outside the release tree. App releases live under `/opt/sombreado/releases/<sha>` with a `current` symlink. After CI passes on `main`, GitHub Actions rsyncs a release and activates it through the fixed root-owned path `/usr/local/sbin/sombreado-deploy-release` (symlink flip, restart, readiness health check). Runtime secrets stay on the VM (`/etc/sombreado/env`); Actions holds deploy SSH credentials plus a pinned host key (`VM_SSH_KNOWN_HOSTS`). Missing VM secrets fail the deploy job on `main` unless `ALLOW_SKIP_DEPLOY=1` is set explicitly. Deploy jobs use a concurrency group so overlapping activates cannot race.

This supersedes the Render Free *runtime target* in ADR 0001 while keeping GitHub Actions as the CI/CD driver. Scrape mutual exclusion remains the DB scrape lease; timers do not replace it. Deployments must never delete or recreate the data directory. Sudoers must not authorize executables under the group-writable release tree.

## Consequences

- Operators own OS updates, firewall, TLS termination, and Always Free reclamation risk.
- First host bootstrap uses `deploy/bootstrap-vm.sh` (installs root-owned activator, deploy script, and systemd unit templates under `/usr/local`, and prefers `uv` at `/usr/local/bin/uv`); each release is activated via that fixed path. Unit files are never installed from the deployer-writable release tree, and activate rejects unit templates that are not root-owned or that are group/world-writable. Activate rejects symlink release trees, requires the release path under `/opt/sombreado/releases/`, and runs `uv sync` as `sombreado` (not root) using the world-executable uv binary. The shared releases directory uses sticky+setgid (`03775`) so group members cannot replace others' top-level entries.
- Activate rollback on health failure is **code-only** (restore previous `current` symlink). It does not downgrade Alembic schema on the durable store; treat breaking migrations as expand/contract.
- Cutover of the browser `NEXT_PUBLIC_API_URL` (or DNS) remains a separate production step.

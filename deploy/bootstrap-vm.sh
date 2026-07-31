#!/usr/bin/env bash
# One-time Oracle VM host preparation. Safe to re-run; never deletes the data dir.
#
#   sudo DEPLOY_USER=ubuntu ./deploy/bootstrap-vm.sh
#
# DEPLOY_USER (optional): SSH login used by GitHub Actions. Grants write to
# /opt/sombreado/releases and passwordless sudo for deploy-release.sh only.

set -euo pipefail

SOMBREADO_ROOT="${SOMBREADO_ROOT:-/opt/sombreado}"
SOMBREADO_DATA_ROOT="${SOMBREADO_DATA_ROOT:-/var/lib/sombreado}"
SOMBREADO_ENV_DIR="${SOMBREADO_ENV_DIR:-/etc/sombreado}"
DEPLOY_USER="${DEPLOY_USER:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi

if ! id -u sombreado >/dev/null 2>&1; then
  useradd --system --home "${SOMBREADO_ROOT}" --shell /usr/sbin/nologin sombreado
fi

mkdir -p \
  "${SOMBREADO_ROOT}/releases" \
  "${SOMBREADO_DATA_ROOT}" \
  "${SOMBREADO_DATA_ROOT}/backup-work" \
  "${SOMBREADO_DATA_ROOT}/backup-aside" \
  "${SOMBREADO_ENV_DIR}"

chown sombreado:sombreado "${SOMBREADO_ROOT}" "${SOMBREADO_DATA_ROOT}"
chmod 0755 "${SOMBREADO_ROOT}"
chmod 0750 "${SOMBREADO_DATA_ROOT}" "${SOMBREADO_ENV_DIR}"

# Releases are group-writable so the Actions SSH user can rsync without being root.
chown sombreado:sombreado "${SOMBREADO_ROOT}/releases"
chmod 2775 "${SOMBREADO_ROOT}/releases"

if [[ -n "${DEPLOY_USER}" ]]; then
  if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    echo "DEPLOY_USER=${DEPLOY_USER} does not exist" >&2
    exit 1
  fi
  usermod -aG sombreado "${DEPLOY_USER}"
  SUDOERS_FILE="/etc/sudoers.d/sombreado-deploy"
  cat >"${SUDOERS_FILE}" <<EOF
# Managed by deploy/bootstrap-vm.sh — deploy user may activate releases only.
${DEPLOY_USER} ALL=(root) NOPASSWD: /opt/sombreado/releases/*/deploy/deploy-release.sh
EOF
  chmod 0440 "${SUDOERS_FILE}"
  echo "granted ${DEPLOY_USER} group sombreado + sudoers for deploy-release.sh"
fi

if [[ ! -f "${SOMBREADO_ENV_DIR}/env" ]]; then
  if [[ -f "${SCRIPT_DIR}/env.example" ]]; then
    install -m 0640 -o root -g sombreado "${SCRIPT_DIR}/env.example" "${SOMBREADO_ENV_DIR}/env"
    echo "wrote ${SOMBREADO_ENV_DIR}/env from env.example — edit runtime secrets before first deploy"
  else
    echo "missing env.example; create ${SOMBREADO_ENV_DIR}/env manually" >&2
    exit 1
  fi
else
  echo "keeping existing ${SOMBREADO_ENV_DIR}/env"
fi

echo "bootstrap complete: root=${SOMBREADO_ROOT} data=${SOMBREADO_DATA_ROOT}"
echo "ensure uv is on root PATH (curl -LsSf https://astral.sh/uv/install.sh | sh)"
echo "on Oracle A1 (aarch64), confirm dependency wheels install via: uv sync --frozen --no-dev"

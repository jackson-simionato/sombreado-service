#!/usr/bin/env bash
# One-time Oracle VM host preparation. Safe to re-run; never deletes the data dir.
#
#   sudo DEPLOY_USER=ubuntu ./deploy/bootstrap-vm.sh
#
# DEPLOY_USER (optional): SSH login used by GitHub Actions. Grants write to
# /opt/sombreado/releases and passwordless sudo for the fixed-path activator only.
#
# Re-run after changing deploy/deploy-release.sh or deploy/sombreado-deploy-release
# so root-owned copies under /usr/local are refreshed.

set -euo pipefail

SOMBREADO_ROOT="${SOMBREADO_ROOT:-/opt/sombreado}"
SOMBREADO_DATA_ROOT="${SOMBREADO_DATA_ROOT:-/var/lib/sombreado}"
SOMBREADO_ENV_DIR="${SOMBREADO_ENV_DIR:-/etc/sombreado}"
SOMBREADO_SBIN="${SOMBREADO_SBIN:-/usr/local/sbin}"
SOMBREADO_DEPLOY_LIB="${SOMBREADO_DEPLOY_LIB:-/usr/local/lib/sombreado}"
SUDOERS_FILE="${SUDOERS_FILE:-/etc/sudoers.d/sombreado-deploy}"
DEPLOY_USER="${DEPLOY_USER:-}"
REQUIRE_ROOT="${REQUIRE_ROOT:-1}"
SOMBREADO_MANAGE_USER="${SOMBREADO_MANAGE_USER:-1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTIVATOR_NAME="sombreado-deploy-release"
ACTIVATOR_PATH="${SOMBREADO_SBIN}/${ACTIVATOR_NAME}"

if [[ "${REQUIRE_ROOT}" == "1" && "${EUID}" -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi

if [[ "${SOMBREADO_MANAGE_USER}" == "1" ]]; then
  if ! id -u sombreado >/dev/null 2>&1; then
    useradd --system --home "${SOMBREADO_ROOT}" --shell /usr/sbin/nologin sombreado
  fi
fi

mkdir -p \
  "${SOMBREADO_ROOT}/releases" \
  "${SOMBREADO_DATA_ROOT}" \
  "${SOMBREADO_DATA_ROOT}/backup-work" \
  "${SOMBREADO_DATA_ROOT}/backup-aside" \
  "${SOMBREADO_ENV_DIR}" \
  "${SOMBREADO_SBIN}" \
  "${SOMBREADO_DEPLOY_LIB}"

# Install root-owned activator + deploy implementation (never sudo user-writable release paths).
install -m 0755 "${SCRIPT_DIR}/${ACTIVATOR_NAME}" "${ACTIVATOR_PATH}"
install -m 0755 "${SCRIPT_DIR}/deploy-release.sh" "${SOMBREADO_DEPLOY_LIB}/deploy-release.sh"
if [[ "$(id -u)" -eq 0 ]]; then
  chown root:root "${ACTIVATOR_PATH}" "${SOMBREADO_DEPLOY_LIB}/deploy-release.sh"
fi

chown sombreado:sombreado "${SOMBREADO_ROOT}" "${SOMBREADO_DATA_ROOT}" 2>/dev/null || true
chmod 0755 "${SOMBREADO_ROOT}"
chmod 0750 "${SOMBREADO_DATA_ROOT}" "${SOMBREADO_ENV_DIR}"

# Releases are group-writable so the Actions SSH user can rsync without being root.
chown sombreado:sombreado "${SOMBREADO_ROOT}/releases" 2>/dev/null || true
chmod 2775 "${SOMBREADO_ROOT}/releases"

if [[ -n "${DEPLOY_USER}" ]]; then
  if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    echo "DEPLOY_USER=${DEPLOY_USER} does not exist" >&2
    exit 1
  fi
  if [[ "$(id -u)" -eq 0 ]]; then
    usermod -aG sombreado "${DEPLOY_USER}"
  fi
  mkdir -p "$(dirname "${SUDOERS_FILE}")"
  sudoers_tmp="${SUDOERS_FILE}.tmp"
  cat >"${sudoers_tmp}" <<EOF
# Managed by deploy/bootstrap-vm.sh — activate releases via fixed root-owned path only.
${DEPLOY_USER} ALL=(root) NOPASSWD: ${ACTIVATOR_PATH}
EOF
  chmod 0440 "${sudoers_tmp}"
  mv -f "${sudoers_tmp}" "${SUDOERS_FILE}"
  echo "granted ${DEPLOY_USER} group sombreado + sudoers for ${ACTIVATOR_PATH}"
fi

if [[ ! -f "${SOMBREADO_ENV_DIR}/env" ]]; then
  if [[ -f "${SCRIPT_DIR}/env.example" ]]; then
    install -m 0640 "${SCRIPT_DIR}/env.example" "${SOMBREADO_ENV_DIR}/env"
    if [[ "$(id -u)" -eq 0 ]]; then
      chown root:sombreado "${SOMBREADO_ENV_DIR}/env"
    fi
    echo "wrote ${SOMBREADO_ENV_DIR}/env from env.example — edit runtime secrets before first deploy"
  else
    echo "missing env.example; create ${SOMBREADO_ENV_DIR}/env manually" >&2
    exit 1
  fi
else
  echo "keeping existing ${SOMBREADO_ENV_DIR}/env"
fi

echo "bootstrap complete: root=${SOMBREADO_ROOT} data=${SOMBREADO_DATA_ROOT} activator=${ACTIVATOR_PATH}"
echo "ensure uv is on root PATH (curl -LsSf https://astral.sh/uv/install.sh | sh)"
echo "on Oracle A1 (aarch64), confirm dependency wheels install via: uv sync --frozen --no-dev"

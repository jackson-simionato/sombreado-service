#!/usr/bin/env bash
# PARKED / historical (ADR 0004 superseded by ADR 0005). Not the production deploy path.
# One-time Oracle VM host preparation. Safe to re-run; never deletes the data dir.
#
#   sudo DEPLOY_USER=ubuntu ./deploy/bootstrap-vm.sh
#
# DEPLOY_USER (optional): SSH login used by GitHub Actions. Grants write to
# /opt/sombreado/releases and passwordless sudo for the fixed-path activator only.
#
# Re-run after changing deploy/deploy-release.sh, deploy/sombreado-deploy-release,
# or deploy/systemd/* so root-owned copies under /usr/local are refreshed.

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

# Install root-owned activator, deploy implementation, and systemd unit templates.
# Never install privileged units from the deployer-writable release tree.
install -m 0755 "${SCRIPT_DIR}/${ACTIVATOR_NAME}" "${ACTIVATOR_PATH}"
install -m 0755 "${SCRIPT_DIR}/deploy-release.sh" "${SOMBREADO_DEPLOY_LIB}/deploy-release.sh"
mkdir -p "${SOMBREADO_DEPLOY_LIB}/systemd"
install -m 0644 \
  "${SCRIPT_DIR}/systemd/sombreado-api.service" \
  "${SCRIPT_DIR}/systemd/sombreado-scrape.service" \
  "${SCRIPT_DIR}/systemd/sombreado-scrape.timer" \
  "${SCRIPT_DIR}/systemd/sombreado-backup.service" \
  "${SCRIPT_DIR}/systemd/sombreado-backup.timer" \
  "${SOMBREADO_DEPLOY_LIB}/systemd/"
if [[ "$(id -u)" -eq 0 ]]; then
  chown root:root \
    "${ACTIVATOR_PATH}" \
    "${SOMBREADO_DEPLOY_LIB}/deploy-release.sh" \
    "${SOMBREADO_DEPLOY_LIB}/systemd" \
    "${SOMBREADO_DEPLOY_LIB}/systemd/"*
fi

chown sombreado:sombreado "${SOMBREADO_ROOT}" "${SOMBREADO_DATA_ROOT}" 2>/dev/null || true
chmod 0755 "${SOMBREADO_ROOT}"
chmod 0750 "${SOMBREADO_DATA_ROOT}" "${SOMBREADO_ENV_DIR}"

# Releases are group-writable so the Actions SSH user can rsync without being root.
chown sombreado:sombreado "${SOMBREADO_ROOT}/releases" 2>/dev/null || true
# setgid + sticky + group-write: deploy group can create releases, but cannot
# unlink/replace top-level entries owned by others (including live current target).
chmod 3775 "${SOMBREADO_ROOT}/releases"

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

# Prefer a world-traversable uv binary. Deploy syncs as root then chowns .venv,
# so /root/.local/bin/uv works for activate, but /usr/local/bin/uv is clearer for ops.
if [[ "$(id -u)" -eq 0 ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv_src="$(command -v uv)"
    if [[ "${uv_src}" != /usr/local/bin/uv ]]; then
      install -m 0755 "${uv_src}" /usr/local/bin/uv
      echo "installed uv -> /usr/local/bin/uv (from ${uv_src})"
    fi
  else
    echo "WARNING: uv not on PATH; install to /usr/local/bin/uv before the first deploy" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "  install -m 0755 \"\${HOME}/.local/bin/uv\" /usr/local/bin/uv" >&2
  fi
fi

echo "bootstrap complete: root=${SOMBREADO_ROOT} data=${SOMBREADO_DATA_ROOT} activator=${ACTIVATOR_PATH}"
echo "on Oracle A1 (aarch64), confirm dependency wheels install via: uv sync --frozen --no-dev"

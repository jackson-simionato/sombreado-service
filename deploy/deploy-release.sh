#!/usr/bin/env bash
# Activate a synced release on the Oracle VM.
#
# Expected layout (defaults):
#   /opt/sombreado/releases/<sha>/   # code already rsynced here
#   /opt/sombreado/current -> releases/<sha>
#   /var/lib/sombreado/              # durable SQLite + backup work dirs (never deleted)
#   /etc/sombreado/env               # runtime secrets (EnvironmentFile)
#   /usr/local/lib/sombreado/systemd # root-owned unit templates (from bootstrap)
#
# Production entry point (root-owned, via sudoers):
#   sudo /usr/local/sbin/sombreado-deploy-release <sha>
#
# Overrides for tests / non-standard roots:
#   SOMBREADO_ROOT SOMBREADO_DATA_ROOT SOMBREADO_UNIT_DIR SOMBREADO_ENV_FILE
#   SOMBREADO_DEPLOY_LIB SOMBREADO_UNIT_SOURCE SOMBREADO_ENFORCE_UNIT_OWNERSHIP
#   SYSTEMCTL UV KEEP_RELEASES HEALTH_URL HEALTH_TIMEOUT_SECONDS
#   ROLLBACK_HEALTH_TIMEOUT_SECONDS CURL

set -euo pipefail

SOMBREADO_ROOT="${SOMBREADO_ROOT:-/opt/sombreado}"
SOMBREADO_DATA_ROOT="${SOMBREADO_DATA_ROOT:-/var/lib/sombreado}"
SOMBREADO_UNIT_DIR="${SOMBREADO_UNIT_DIR:-/etc/systemd/system}"
SOMBREADO_ENV_FILE="${SOMBREADO_ENV_FILE:-/etc/sombreado/env}"
SOMBREADO_DEPLOY_LIB="${SOMBREADO_DEPLOY_LIB:-/usr/local/lib/sombreado}"
SOMBREADO_UNIT_SOURCE="${SOMBREADO_UNIT_SOURCE:-${SOMBREADO_DEPLOY_LIB}/systemd}"
SOMBREADO_ENFORCE_UNIT_OWNERSHIP="${SOMBREADO_ENFORCE_UNIT_OWNERSHIP:-1}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
UV="${UV:-uv}"
CURL="${CURL:-curl}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health/live}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-60}"
ROLLBACK_HEALTH_TIMEOUT_SECONDS="${ROLLBACK_HEALTH_TIMEOUT_SECONDS:-30}"

UNIT_NAMES=(
  sombreado-api.service
  sombreado-scrape.service
  sombreado-scrape.timer
  sombreado-backup.service
  sombreado-backup.timer
)

assert_trusted_unit_path() {
  local path="$1"
  local owner mode
  owner="$(stat -c '%u' "${path}")"
  mode="$(stat -c '%a' "${path}")"
  if [[ "${owner}" != "0" ]]; then
    echo "unit path not root-owned: ${path} (uid=${owner})" >&2
    return 1
  fi
  # Reject group/world write bits (octal & 022).
  if (( (8#${mode} & 8#022) != 0 )); then
    echo "unit path is group/world-writable: ${path} (mode=${mode})" >&2
    return 1
  fi
}

if [[ -z "${RELEASE_SHA:-}" ]]; then
  echo "RELEASE_SHA is required" >&2
  exit 1
fi

RELEASE_DIR="${SOMBREADO_ROOT}/releases/${RELEASE_SHA}"
if [[ ! -d "${RELEASE_DIR}" ]]; then
  echo "release directory missing: ${RELEASE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOMBREADO_ENV_FILE}" ]]; then
  echo "runtime env missing: ${SOMBREADO_ENV_FILE} (copy deploy/env.example)" >&2
  exit 1
fi

if [[ ! -d "${SOMBREADO_UNIT_SOURCE}" ]]; then
  echo "root-owned unit source missing: ${SOMBREADO_UNIT_SOURCE} (re-run bootstrap-vm.sh)" >&2
  exit 1
fi

if [[ "${SOMBREADO_ENFORCE_UNIT_OWNERSHIP}" == "1" ]]; then
  assert_trusted_unit_path "${SOMBREADO_UNIT_SOURCE}"
fi

unit_paths=()
for name in "${UNIT_NAMES[@]}"; do
  path="${SOMBREADO_UNIT_SOURCE}/${name}"
  if [[ ! -f "${path}" ]]; then
    echo "missing root-owned unit: ${path}" >&2
    exit 1
  fi
  if [[ "${SOMBREADO_ENFORCE_UNIT_OWNERSHIP}" == "1" ]]; then
    assert_trusted_unit_path "${path}"
  fi
  unit_paths+=("${path}")
done

# Durable data directory: create if absent; never delete or recreate.
mkdir -p \
  "${SOMBREADO_DATA_ROOT}" \
  "${SOMBREADO_DATA_ROOT}/backup-work" \
  "${SOMBREADO_DATA_ROOT}/backup-aside"

echo "syncing Python environment in ${RELEASE_DIR}"
UV_BIN="$(command -v "${UV}" || true)"
if [[ -z "${UV_BIN}" ]]; then
  echo "uv not found on PATH (set UV=/path/to/uv or install to /usr/local/bin/uv)" >&2
  exit 1
fi
# Sync as the activator user (root in production). Do not sudo -u sombreado uv:
# a root-only install under /root/.local/bin is not executable by sombreado.
(
  cd "${RELEASE_DIR}"
  "${UV_BIN}" sync --frozen --no-dev
)
if id -u sombreado >/dev/null 2>&1; then
  chown -R sombreado:sombreado "${RELEASE_DIR}"
fi

echo "installing systemd units from root-owned ${SOMBREADO_UNIT_SOURCE}"
mkdir -p "${SOMBREADO_UNIT_DIR}"
install -m 0644 "${unit_paths[@]}" "${SOMBREADO_UNIT_DIR}/"

PREVIOUS_CURRENT=""
if [[ -L "${SOMBREADO_ROOT}/current" || -e "${SOMBREADO_ROOT}/current" ]]; then
  PREVIOUS_CURRENT="$(readlink -f "${SOMBREADO_ROOT}/current" || true)"
fi

echo "flipping current symlink -> ${RELEASE_DIR}"
mkdir -p "${SOMBREADO_ROOT}"
ln -sfn "${RELEASE_DIR}" "${SOMBREADO_ROOT}/current.new"
mv -Tf "${SOMBREADO_ROOT}/current.new" "${SOMBREADO_ROOT}/current"
if [[ "$(id -u)" -eq 0 ]] && id -u sombreado >/dev/null 2>&1; then
  chown -h sombreado:sombreado "${SOMBREADO_ROOT}/current" || true
  chown -R sombreado:sombreado "${RELEASE_DIR}"
fi

echo "reloading systemd and enabling runtime units"
"${SYSTEMCTL}" daemon-reload
"${SYSTEMCTL}" enable --now sombreado-api.service
"${SYSTEMCTL}" enable --now sombreado-scrape.timer
"${SYSTEMCTL}" enable --now sombreado-backup.timer
"${SYSTEMCTL}" restart sombreado-api.service

wait_for_health() {
  local timeout_seconds="$1"
  local label="$2"
  local deadline=$((SECONDS + timeout_seconds))
  echo "waiting for API health (${label}) at ${HEALTH_URL}"
  until "${CURL}" -fsS --max-time 2 "${HEALTH_URL}" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "API health check failed after ${timeout_seconds}s (${label}): ${HEALTH_URL}" >&2
      return 1
    fi
    sleep 1
  done
  echo "API health ok (${label})"
  return 0
}

if ! wait_for_health "${HEALTH_TIMEOUT_SECONDS}" "new release"; then
  if [[ -n "${PREVIOUS_CURRENT}" && "${PREVIOUS_CURRENT}" != "$(readlink -f "${RELEASE_DIR}")" && -d "${PREVIOUS_CURRENT}" ]]; then
    echo "restoring previous current -> ${PREVIOUS_CURRENT}" >&2
    ln -sfn "${PREVIOUS_CURRENT}" "${SOMBREADO_ROOT}/current.new"
    mv -Tf "${SOMBREADO_ROOT}/current.new" "${SOMBREADO_ROOT}/current"
    if [[ "$(id -u)" -eq 0 ]] && id -u sombreado >/dev/null 2>&1; then
      chown -h sombreado:sombreado "${SOMBREADO_ROOT}/current" || true
    fi
    "${SYSTEMCTL}" restart sombreado-api.service
    if wait_for_health "${ROLLBACK_HEALTH_TIMEOUT_SECONDS}" "restored previous release"; then
      echo "rolled back to previous release; new release failed health" >&2
    else
      echo "previous release also failed health after rollback restart" >&2
    fi
  else
    echo "no previous current to restore" >&2
  fi
  exit 1
fi

# Prune old releases; never touch SOMBREADO_DATA_ROOT.
if [[ "${KEEP_RELEASES}" =~ ^[0-9]+$ ]] && [[ "${KEEP_RELEASES}" -gt 0 ]]; then
  mapfile -t old_releases < <(
    find "${SOMBREADO_ROOT}/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
      | sort -nr \
      | awk 'NR > '"${KEEP_RELEASES}"' { print $2 }'
  )
  for old in "${old_releases[@]:-}"; do
    if [[ -n "${old}" && "${old}" != "${RELEASE_DIR}" ]]; then
      echo "pruning old release ${old}"
      rm -rf "${old}"
    fi
  done
fi

echo "deployed release ${RELEASE_SHA} (data root preserved at ${SOMBREADO_DATA_ROOT})"

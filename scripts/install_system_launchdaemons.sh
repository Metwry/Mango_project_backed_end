#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash scripts/install_system_launchdaemons.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLIST_DIR="${PROJECT_ROOT}/deploy/launchd"
APP_USER="${APP_USER:-wry}"

if [[ ! -d "${PLIST_DIR}" ]]; then
  echo "Plist directory not found: ${PLIST_DIR}" >&2
  exit 1
fi

declare -A FILE_TO_LABEL=(
  ["cc.mango.redis.plist"]="cc.mango.redis"
  ["cc.mango.postgresql16.plist"]="cc.mango.postgresql16"
  ["cc.mango.backend.web.plist"]="cc.mango.backend.web"
  ["cc.mango.backend.celery.plist"]="cc.mango.backend.celery.worker"
  ["cc.mango.backend.celery.beat.plist"]="cc.mango.backend.celery.beat"
)

disable_user_launch_agents() {
  local uid
  uid="$(id -u "${APP_USER}")"

  # Prevent user-level services from competing with system-level daemons.
  launchctl disable "gui/${uid}/homebrew.mxcl.redis" >/dev/null 2>&1 || true
  launchctl disable "gui/${uid}/homebrew.mxcl.postgresql@16" >/dev/null 2>&1 || true
  launchctl disable "gui/${uid}/cc.mango.backend.web" >/dev/null 2>&1 || true
  launchctl disable "gui/${uid}/cc.mango.backend.celery.worker" >/dev/null 2>&1 || true
  launchctl disable "gui/${uid}/cc.mango.backend.celery.beat" >/dev/null 2>&1 || true

  launchctl bootout "gui/${uid}/homebrew.mxcl.redis" >/dev/null 2>&1 || true
  launchctl bootout "gui/${uid}/homebrew.mxcl.postgresql@16" >/dev/null 2>&1 || true
  launchctl bootout "gui/${uid}/cc.mango.backend.web" >/dev/null 2>&1 || true
  launchctl bootout "gui/${uid}/cc.mango.backend.celery.worker" >/dev/null 2>&1 || true
  launchctl bootout "gui/${uid}/cc.mango.backend.celery.beat" >/dev/null 2>&1 || true
}

install_system_plists() {
  local plist
  local src
  local dst

  for plist in "${!FILE_TO_LABEL[@]}"; do
    src="${PLIST_DIR}/${plist}"
    dst="/Library/LaunchDaemons/${plist}"
    if [[ ! -f "${src}" ]]; then
      echo "Missing source plist: ${src}" >&2
      exit 1
    fi
    install -m 644 "${src}" "${dst}"
    chown root:wheel "${dst}"
  done
}

bootstrap_system_jobs() {
  local plist
  local label
  local dst

  for plist in "${!FILE_TO_LABEL[@]}"; do
    label="${FILE_TO_LABEL[$plist]}"
    dst="/Library/LaunchDaemons/${plist}"
    launchctl bootout "system/${label}" >/dev/null 2>&1 || true
    launchctl enable "system/${label}" >/dev/null 2>&1 || true
    launchctl bootstrap system "${dst}"
    launchctl kickstart -k "system/${label}"
  done
}

disable_user_launch_agents
install_system_plists
bootstrap_system_jobs

echo "Installed and started system LaunchDaemons:"
for label in "${FILE_TO_LABEL[@]}"; do
  launchctl print "system/${label}" | awk '/state =|pid =|last exit code/ {print}'
done

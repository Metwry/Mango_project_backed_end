#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONDA_BASE="${CONDA_BASE:-/opt/anaconda3}"
ENV_NAME="${ENV_NAME:-Back_end_project}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8000}"
# On macOS launchd, prefork workers may hit objc fork-safety crashes.
WEB_WORKERS="${WEB_WORKERS:-1}"
WEB_TIMEOUT="${WEB_TIMEOUT:-120}"

if [[ ! -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
  echo "conda.sh not found under ${CONDA_BASE}/etc/profile.d/conda.sh" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

mkdir -p "${PROJECT_ROOT}/tmp_celery_logs"
cd "${PROJECT_ROOT}"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

exec python -m gunicorn mango_project.wsgi:application \
  --bind "${WEB_HOST}:${WEB_PORT}" \
  --workers "${WEB_WORKERS}" \
  --timeout "${WEB_TIMEOUT}" \
  --access-logfile - \
  --error-logfile -

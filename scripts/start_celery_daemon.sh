#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONDA_BASE="${CONDA_BASE:-/opt/anaconda3}"
ENV_NAME="${ENV_NAME:-Back_end_project}"

export PATH="${CONDA_BASE}/bin:${CONDA_BASE}/condabin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "${PROJECT_ROOT}"
mkdir -p "${PROJECT_ROOT}/tmp_celery_logs" "${PROJECT_ROOT}/tmp_celery_state"

exec "${PROJECT_ROOT}/scripts/start_celery.sh" \
  --project-root "${PROJECT_ROOT}" \
  --env-name "${ENV_NAME}" \
  --targets all \
  --with-beat \
  --pool solo

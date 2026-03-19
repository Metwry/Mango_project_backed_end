#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONDA_BASE="${CONDA_BASE:-/opt/anaconda3}"
ENV_NAME="${ENV_NAME:-Back_end_project}"
STATE_DIR="${PROJECT_ROOT}/resource/tmp_celery_state"

if [[ ! -f "${CONDA_BASE}/etc/profile.d/conda.sh" ]]; then
  echo "conda.sh not found under ${CONDA_BASE}/etc/profile.d/conda.sh" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

cd "${PROJECT_ROOT}"
mkdir -p "${STATE_DIR}" "${PROJECT_ROOT}/resource/tmp_celery_logs"

exec python -m celery -A mango_project beat \
  -l info \
  --schedule "${STATE_DIR}/celerybeat-schedule"

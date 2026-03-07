#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_NAME="Back_end_project"
LOG_DIR="tmp_stress_logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --env-name)
      ENV_NAME="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

"${SCRIPT_DIR}/start_celery_stack.sh" \
  --project-root "${PROJECT_ROOT}" \
  --env-name "${ENV_NAME}" \
  --targets "all" \
  --with-beat \
  --log-dir "${LOG_DIR}" \
  --fake-provider \
  --market-sync-every-seconds 5 \
  --snapshot-capture-every-seconds 7 \
  --snapshot-agg-h4-every-seconds 13 \
  --snapshot-agg-d1-every-seconds 17 \
  --snapshot-agg-mon1-every-seconds 19 \
  --snapshot-cleanup-every-seconds 23

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

"${SCRIPT_DIR}/start_celery_stack.sh" \
  --project-root "${PROJECT_ROOT}" \
  --targets "all" \
  --with-beat \
  --fake-provider \
  --market-sync-every-seconds 5 \
  --snapshot-capture-every-seconds 7 \
  --snapshot-agg-h4-every-seconds 13 \
  --snapshot-agg-d1-every-seconds 17 \
  --snapshot-agg-mon1-every-seconds 19 \
  --snapshot-cleanup-every-seconds 23


#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: start_worker.sh <worker-name> <queue-list>" >&2
  exit 1
fi

WORKER_NAME="$1"
QUEUE_LIST="$2"

/app/resource/scripts/docker/wait_for_services.sh
exec celery -A mango_project worker -n "${WORKER_NAME}@%h" -Q "${QUEUE_LIST}" -l info -P "${CELERY_WORKER_POOL:-threads}" --concurrency "${CELERY_WORKER_CONCURRENCY:-4}"

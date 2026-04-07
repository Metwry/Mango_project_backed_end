#!/usr/bin/env bash
set -euo pipefail

/app/resource/scripts/docker/wait_for_services.sh
mkdir -p /app/resource/tmp_celery_state
exec celery -A mango_project beat -l info --schedule /app/resource/tmp_celery_state/celerybeat-schedule

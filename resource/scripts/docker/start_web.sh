#!/usr/bin/env bash
set -euo pipefail

/app/resource/scripts/docker/wait_for_services.sh
python manage.py migrate --noinput
exec gunicorn mango_project.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120

#!/usr/bin/env bash
set -euo pipefail

wait_for_tcp() {
  local host="$1"
  local port="$2"
  local name="$3"

  echo "waiting for ${name} (${host}:${port})"
  until nc -z "$host" "$port" >/dev/null 2>&1; do
    sleep 2
  done
}

wait_for_tcp "${DB_HOST:-postgres}" "${DB_PORT:-5432}" "postgres"
wait_for_tcp "redis" "6379" "redis"
wait_for_tcp "rabbitmq" "5672" "rabbitmq"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="tmp_celery_logs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
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

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
PID_FILE="${PROJECT_ROOT}/${LOG_DIR}/stack_pids.csv"

stop_pid() {
  local pid="$1"
  local label="$2"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "Stopped ${label} (PID=${pid})"
  else
    echo "Already stopped ${label} (PID=${pid})"
  fi
}

if [[ -f "${PID_FILE}" ]]; then
  tail -n +2 "${PID_FILE}" | while IFS=',' read -r name pid log; do
    [[ -z "${pid:-}" ]] && continue
    stop_pid "${pid}" "${name}"
  done
  rm -f "${PID_FILE}"
fi

if command -v pgrep >/dev/null 2>&1; then
  while IFS= read -r line; do
    pid="${line%% *}"
    cmd="${line#* }"
    [[ -z "${pid}" ]] && continue
    kill "${pid}" 2>/dev/null || true
    echo "Stopped fallback PID=${pid} CMD=${cmd}"
  done < <(pgrep -af "mango_project.*celery|celery.*mango_project" || true)
fi

echo "Done."

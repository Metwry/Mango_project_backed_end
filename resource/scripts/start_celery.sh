#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_NAME="Back_end_project"
TARGETS="all"
WITH_BEAT="0"
POOL="threads"
CONCURRENCY="4"
LOG_DIR="resource/tmp_celery_logs"
STATE_DIR="resource/tmp_celery_state"
FOLLOW_LOGS="0"
TAIL_LINES="50"
FAKE_PROVIDER="0"

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
    --targets)
      TARGETS="$2"
      shift 2
      ;;
    --with-beat)
      WITH_BEAT="1"
      shift
      ;;
    --pool)
      POOL="$2"
      shift 2
      ;;
    --concurrency)
      CONCURRENCY="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --follow-logs)
      FOLLOW_LOGS="1"
      shift
      ;;
    --tail-lines)
      TAIL_LINES="$2"
      shift 2
      ;;
    --fake-provider)
      FAKE_PROVIDER="1"
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
RESOLVED_LOG_DIR="${PROJECT_ROOT}/${LOG_DIR}"
mkdir -p "${RESOLVED_LOG_DIR}"
RESOLVED_STATE_DIR="${PROJECT_ROOT}/${STATE_DIR}"
mkdir -p "${RESOLVED_STATE_DIR}"

normalize_targets() {
  local input="$1"
  local item
  local lowered
  local -a raw_targets
  IFS=',' read -r -a raw_targets <<< "$input"
  for item in "${raw_targets[@]}"; do
    lowered="$(echo "$item" | tr '[:upper:]' '[:lower:]' | xargs)"
    [[ -z "$lowered" ]] && continue
    case "$lowered" in
      all)
        echo "market_sync"
        echo "snapshot_capture"
        echo "snapshot_aggregate"
        echo "snapshot_cleanup"
        ;;
      market|market_sync)
        echo "market_sync"
        ;;
      snapshot)
        echo "snapshot_capture"
        echo "snapshot_aggregate"
        echo "snapshot_cleanup"
        ;;
      snapshot_capture|snapshot_aggregate|snapshot_cleanup)
        echo "$lowered"
        ;;
      *)
        echo "Unknown target: $lowered" >&2
        exit 1
        ;;
    esac
  done | awk '!seen[$0]++'
}

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found in PATH" >&2
  exit 1
fi

CONDA_BASE="$(conda info --base)"
if [[ -z "${CONDA_BASE}" ]]; then
  echo "Unable to resolve conda base path" >&2
  exit 1
fi

# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"
PYTHON_BIN="$(python -c 'import sys; print(sys.executable)')"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Resolved python is not executable: ${PYTHON_BIN}" >&2
  exit 1
fi

declare -A COMMANDS=(
  ["market_sync"]="-A mango_project worker -n market_sync@%h -Q market_sync -l info -P ${POOL} --concurrency ${CONCURRENCY}"
  ["snapshot_capture"]="-A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P ${POOL} --concurrency ${CONCURRENCY}"
  ["snapshot_aggregate"]="-A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P ${POOL} --concurrency ${CONCURRENCY}"
  ["snapshot_cleanup"]="-A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P ${POOL} --concurrency ${CONCURRENCY}"
)

start_proc() {
  local name="$1"
  local command="$2"
  local logfile="$3"
  (
    cd "$PROJECT_ROOT" || exit 1
    [[ "$FAKE_PROVIDER" == "1" ]] && export MARKET_QUOTE_PROVIDER="fake"
    exec "${PYTHON_BIN}" -m celery ${command} >"${logfile}" 2>&1
  ) &
  echo "$!"
}

mapfile -t TARGET_WORKERS < <(normalize_targets "$TARGETS")
if [[ ${#TARGET_WORKERS[@]} -eq 0 ]]; then
  echo "No worker targets resolved." >&2
  exit 1
fi

PID_FILE="${RESOLVED_LOG_DIR}/stack_pids.csv"
echo "name,pid,log" > "${PID_FILE}"

if [[ "$WITH_BEAT" == "1" ]]; then
  beat_log="${RESOLVED_LOG_DIR}/beat.log"
  beat_schedule="${RESOLVED_STATE_DIR}/celerybeat-schedule"
  beat_pid="$(start_proc "beat" "-A mango_project beat -l info --schedule ${beat_schedule}" "${beat_log}")"
  echo "beat,${beat_pid},${beat_log}" >> "${PID_FILE}"
fi

for worker in "${TARGET_WORKERS[@]}"; do
  log="${RESOLVED_LOG_DIR}/${worker}.log"
  pid="$(start_proc "${worker}" "${COMMANDS[$worker]}" "${log}")"
  echo "${worker},${pid},${log}" >> "${PID_FILE}"
done

echo "Started celery stack."
echo "ProjectRoot: ${PROJECT_ROOT}"
echo "Python: ${PYTHON_BIN}"
echo "LogDir: ${RESOLVED_LOG_DIR}"
echo "StateDir: ${RESOLVED_STATE_DIR}"
echo "PID file: ${PID_FILE}"

if [[ "$FOLLOW_LOGS" == "1" ]]; then
  tail -n "${TAIL_LINES}" -f "${RESOLVED_LOG_DIR}"/*.log
fi

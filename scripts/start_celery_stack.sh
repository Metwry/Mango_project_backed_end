#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_NAME="Back_end_project"
TARGETS="all"
WITH_BEAT="0"
POOL="solo"
LOG_DIR="tmp_celery_logs"
FAKE_PROVIDER="0"
MARKET_SYNC_EVERY_SECONDS="0"
SNAPSHOT_CAPTURE_EVERY_SECONDS="0"
SNAPSHOT_AGG_H4_EVERY_SECONDS="0"
SNAPSHOT_AGG_D1_EVERY_SECONDS="0"
SNAPSHOT_AGG_MON1_EVERY_SECONDS="0"
SNAPSHOT_CLEANUP_EVERY_SECONDS="0"

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
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --fake-provider)
      FAKE_PROVIDER="1"
      shift
      ;;
    --market-sync-every-seconds)
      MARKET_SYNC_EVERY_SECONDS="$2"
      shift 2
      ;;
    --snapshot-capture-every-seconds)
      SNAPSHOT_CAPTURE_EVERY_SECONDS="$2"
      shift 2
      ;;
    --snapshot-agg-h4-every-seconds)
      SNAPSHOT_AGG_H4_EVERY_SECONDS="$2"
      shift 2
      ;;
    --snapshot-agg-d1-every-seconds)
      SNAPSHOT_AGG_D1_EVERY_SECONDS="$2"
      shift 2
      ;;
    --snapshot-agg-mon1-every-seconds)
      SNAPSHOT_AGG_MON1_EVERY_SECONDS="$2"
      shift 2
      ;;
    --snapshot-cleanup-every-seconds)
      SNAPSHOT_CLEANUP_EVERY_SECONDS="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found in PATH" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
RESOLVED_LOG_DIR="${PROJECT_ROOT}/${LOG_DIR}"
mkdir -p "${RESOLVED_LOG_DIR}"

IFS=',' read -r -a RAW_TARGETS <<< "$TARGETS"
TARGET_WORKERS=()
for raw in "${RAW_TARGETS[@]}"; do
  t="$(echo "$raw" | tr '[:upper:]' '[:lower:]' | xargs)"
  [[ -z "$t" ]] && continue
  case "$t" in
    all)
      TARGET_WORKERS+=("market_sync" "snapshot_capture" "snapshot_aggregate" "snapshot_cleanup")
      ;;
    market|market_sync)
      TARGET_WORKERS+=("market_sync")
      ;;
    snapshot)
      TARGET_WORKERS+=("snapshot_capture" "snapshot_aggregate" "snapshot_cleanup")
      ;;
    snapshot_capture|snapshot_aggregate|snapshot_cleanup)
      TARGET_WORKERS+=("$t")
      ;;
    *)
      echo "Unknown target: $t" >&2
      exit 1
      ;;
  esac
done

if [[ ${#TARGET_WORKERS[@]} -eq 0 ]]; then
  echo "No worker targets resolved." >&2
  exit 1
fi

declare -A COMMANDS=(
  ["market_sync"]="celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P ${POOL}"
  ["snapshot_capture"]="celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P ${POOL}"
  ["snapshot_aggregate"]="celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P ${POOL}"
  ["snapshot_cleanup"]="celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P ${POOL}"
)

start_proc() {
  local name="$1"
  local command="$2"
  local logfile="$3"
  (
    cd "$PROJECT_ROOT" || exit 1
    if [[ "$FAKE_PROVIDER" == "1" ]]; then
      export MARKET_QUOTE_PROVIDER="fake"
    fi
    [[ "$MARKET_SYNC_EVERY_SECONDS" != "0" ]] && export MARKET_SYNC_TEST_EVERY_SECONDS="$MARKET_SYNC_EVERY_SECONDS"
    [[ "$SNAPSHOT_CAPTURE_EVERY_SECONDS" != "0" ]] && export SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS="$SNAPSHOT_CAPTURE_EVERY_SECONDS"
    [[ "$SNAPSHOT_AGG_H4_EVERY_SECONDS" != "0" ]] && export SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS="$SNAPSHOT_AGG_H4_EVERY_SECONDS"
    [[ "$SNAPSHOT_AGG_D1_EVERY_SECONDS" != "0" ]] && export SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS="$SNAPSHOT_AGG_D1_EVERY_SECONDS"
    [[ "$SNAPSHOT_AGG_MON1_EVERY_SECONDS" != "0" ]] && export SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS="$SNAPSHOT_AGG_MON1_EVERY_SECONDS"
    [[ "$SNAPSHOT_CLEANUP_EVERY_SECONDS" != "0" ]] && export SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS="$SNAPSHOT_CLEANUP_EVERY_SECONDS"
    conda run --no-capture-output -n "$ENV_NAME" bash -lc "$command" >"$logfile" 2>&1
  ) &
  echo "$!"
}

PID_FILE="${RESOLVED_LOG_DIR}/stack_pids.csv"
echo "name,pid,log" > "$PID_FILE"

if [[ "$WITH_BEAT" == "1" ]]; then
  beat_log="${RESOLVED_LOG_DIR}/beat.log"
  beat_pid="$(start_proc "beat" "celery -A mango_project beat -l info" "$beat_log")"
  echo "beat,${beat_pid},${beat_log}" >> "$PID_FILE"
fi

for worker in "${TARGET_WORKERS[@]}"; do
  log="${RESOLVED_LOG_DIR}/${worker}.log"
  pid="$(start_proc "$worker" "${COMMANDS[$worker]}" "$log")"
  echo "${worker},${pid},${log}" >> "$PID_FILE"
done

echo "Started celery stack."
echo "ProjectRoot: ${PROJECT_ROOT}"
echo "Conda Env: ${ENV_NAME}"
echo "LogDir: ${RESOLVED_LOG_DIR}"
echo "PID file: ${PID_FILE}"
echo "Tail logs:"
echo "  tail -f ${RESOLVED_LOG_DIR}/market_sync.log"

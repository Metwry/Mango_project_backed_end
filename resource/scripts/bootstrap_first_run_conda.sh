#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_NAME="Back_end_project"
START_DATE=""
END_DATE=""
SYNC_MARKETS="cn hk us fx crypto"
CALENDAR_MARKETS="US CN HK"
CALENDAR_OUT_DIR=""
SKIP_MIGRATE="0"
SKIP_SYMBOLS="0"
SKIP_CALENDAR="0"
WITH_LOGO_SYNC="0"
SYMBOLS_INSERT_ONLY="0"
LOGO_MARKETS="us hk crypto"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-name)
      ENV_NAME="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --start-date)
      START_DATE="$2"
      shift 2
      ;;
    --end-date)
      END_DATE="$2"
      shift 2
      ;;
    --sync-markets)
      SYNC_MARKETS="$2"
      shift 2
      ;;
    --calendar-markets)
      CALENDAR_MARKETS="$2"
      shift 2
      ;;
    --calendar-out-dir)
      CALENDAR_OUT_DIR="$2"
      shift 2
      ;;
    --skip-migrate)
      SKIP_MIGRATE="1"
      shift
      ;;
    --skip-symbols)
      SKIP_SYMBOLS="1"
      shift
      ;;
    --skip-calendar)
      SKIP_CALENDAR="1"
      shift
      ;;
    --with-logo-sync)
      WITH_LOGO_SYNC="1"
      shift
      ;;
    --symbols-insert-only)
      SYMBOLS_INSERT_ONLY="1"
      shift
      ;;
    --logo-markets)
      LOGO_MARKETS="$2"
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
cd "$PROJECT_ROOT"

if [[ -z "$START_DATE" ]]; then
  START_DATE="$(date +%Y)-01-01"
fi
if [[ -z "$END_DATE" ]]; then
  END_DATE="$(( $(date +%Y) + 1 ))-12-31"
fi

echo "Bootstrap project first run"
echo "ProjectRoot: $PROJECT_ROOT"
echo "Conda Env: $ENV_NAME"
echo "Calendar Range: $START_DATE -> $END_DATE"

if [[ "$SKIP_MIGRATE" == "0" ]]; then
  echo
  echo "[1/4] Running migrations..."
  conda run -n "$ENV_NAME" python manage.py migrate
fi

if [[ "$SKIP_SYMBOLS" == "0" ]]; then
  echo
  echo "[2/4] Syncing symbols..."
  sync_symbols_args=(manage.py sync_symbols --markets)
  for market in $SYNC_MARKETS; do
    sync_symbols_args+=("$market")
  done
  if [[ "$SYMBOLS_INSERT_ONLY" == "1" ]]; then
    sync_symbols_args+=(--insert-only)
  fi
  conda run -n "$ENV_NAME" python "${sync_symbols_args[@]}"
fi

if [[ "$SKIP_CALENDAR" == "0" ]]; then
  echo
  echo "[3/4] Building market calendar CSV..."
  if [[ -n "$CALENDAR_OUT_DIR" ]]; then
    conda run -n "$ENV_NAME" python manage.py build_market_calendar_csv --start "$START_DATE" --end "$END_DATE" --markets $CALENDAR_MARKETS --out-dir "$CALENDAR_OUT_DIR"
  else
    conda run -n "$ENV_NAME" python manage.py build_market_calendar_csv --start "$START_DATE" --end "$END_DATE" --markets $CALENDAR_MARKETS
  fi
fi

if [[ "$WITH_LOGO_SYNC" == "1" ]]; then
  echo
  echo "[4/4] Syncing logo metadata..."
  sync_logo_args=(manage.py sync_logo_data --markets)
  for market in $LOGO_MARKETS; do
    sync_logo_args+=("$market")
  done
  conda run -n "$ENV_NAME" python "${sync_logo_args[@]}"
else
  echo
  echo "[4/4] Skip logo sync (use --with-logo-sync to enable)"
fi

echo
echo "First-run bootstrap completed."

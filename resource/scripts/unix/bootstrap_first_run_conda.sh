#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_NAME="Back_end_project"
SYNC_MARKETS="cn hk us fx crypto"
SKIP_MIGRATE="0"
SKIP_SYMBOLS="0"
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
    --sync-markets)
      SYNC_MARKETS="$2"
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

echo "Bootstrap project first run"
echo "ProjectRoot: $PROJECT_ROOT"
echo "Conda Env: $ENV_NAME"

if [[ "$SKIP_MIGRATE" == "0" ]]; then
  echo
  echo "[1/3] Running migrations..."
  conda run -n "$ENV_NAME" python manage.py migrate
fi

if [[ "$SKIP_SYMBOLS" == "0" ]]; then
  echo
  echo "[2/3] Syncing symbols..."
  sync_symbols_args=(manage.py sync_symbols --markets)
  for market in $SYNC_MARKETS; do
    sync_symbols_args+=("$market")
  done
  if [[ "$SYMBOLS_INSERT_ONLY" == "1" ]]; then
    sync_symbols_args+=(--insert-only)
  fi
  conda run -n "$ENV_NAME" python "${sync_symbols_args[@]}"
fi

if [[ "$WITH_LOGO_SYNC" == "1" ]]; then
  echo
  echo "[3/3] Syncing logo metadata..."
  sync_logo_args=(manage.py sync_logo_data --markets)
  for market in $LOGO_MARKETS; do
    sync_logo_args+=("$market")
  done
  conda run -n "$ENV_NAME" python "${sync_logo_args[@]}"
else
  echo
  echo "[3/3] Skip logo sync (use --with-logo-sync to enable)"
fi

echo
echo "First-run bootstrap completed."

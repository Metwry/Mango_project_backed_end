#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ENV_NAME="Back_end_project"
UPGRADE_PIP="0"

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
    --upgrade-pip)
      UPGRADE_PIP="1"
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      echo "Usage: $0 [--env-name Back_end_project] [--project-root /path/to/project] [--upgrade-pip]" >&2
      exit 1
      ;;
  esac
done

if ! command -v conda >/dev/null 2>&1; then
  echo "conda command not found in PATH" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
REQUIREMENTS_PATH="${PROJECT_ROOT}/requirements.txt"

if [[ ! -f "$REQUIREMENTS_PATH" ]]; then
  echo "requirements.txt not found: $REQUIREMENTS_PATH" >&2
  exit 1
fi

if [[ "$UPGRADE_PIP" == "1" ]]; then
  conda run -n "$ENV_NAME" python -m pip install --upgrade pip
fi

conda run -n "$ENV_NAME" python -m pip install -r "$REQUIREMENTS_PATH"
echo "Done. Installed requirements into conda env: $ENV_NAME"

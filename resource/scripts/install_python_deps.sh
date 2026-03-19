#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
VENV_DIR="${VENV_DIR:-.venv}"
CREATE_VENV="${CREATE_VENV:-1}"
UPGRADE_PIP="${UPGRADE_PIP:-1}"

cd "$PROJECT_ROOT"

if [[ ! -f requirements.txt ]]; then
  echo "requirements.txt not found: $PROJECT_ROOT/requirements.txt"
  exit 1
fi

if [[ "$CREATE_VENV" == "1" && ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment: $PROJECT_ROOT/$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

if [[ -x "$VENV_DIR/bin/pip" ]]; then
  PIP_CMD="$VENV_DIR/bin/pip"
else
  PIP_CMD="pip3"
fi

if [[ "$UPGRADE_PIP" == "1" ]]; then
  "$PIP_CMD" install --upgrade pip
fi

"$PIP_CMD" install -r requirements.txt

echo "Done."
if [[ -f "$VENV_DIR/bin/activate" ]]; then
  echo "Tip: source $VENV_DIR/bin/activate"
fi

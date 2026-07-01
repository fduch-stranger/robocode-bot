#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/env.sh"
load_repo_env "$ROOT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --no-cache-dir --upgrade pip
.venv/bin/python -m pip install --no-cache-dir -r requirements.txt

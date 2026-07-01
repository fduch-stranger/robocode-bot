#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/env.sh"
load_repo_env "$ROOT_DIR"
RUNTIME_PYTHON_BIN="$(robocode_python_bin "$ROOT_DIR")"

exec "$RUNTIME_PYTHON_BIN" "$ROOT_DIR/tools/run_ab.py" "$@"

#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$BOT_DIR/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR/bots${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT_DIR/.venv/bin/python" "$BOT_DIR/circle-strafer.py"

#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$BOT_DIR/../../.venv/bin/python" "$BOT_DIR/circle-strafer.py"

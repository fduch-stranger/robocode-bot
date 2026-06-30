#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"

cd "$ROOT_DIR"
mkdir -p "$DIST_DIR"

for bot_dir in bots/sweep-pressure bots/circle-strafer bots/chase-lock; do
  bot_name="$(basename "$bot_dir")"
  archive="$DIST_DIR/${bot_name}.zip"
  rm -f "$archive"
  (cd bots && zip -qr "$archive" "$bot_name" bot_utils \
    -x "$bot_name/__pycache__" "$bot_name/__pycache__/*" "$bot_name/**/*.pyc" \
    -x "bot_utils/__pycache__" "bot_utils/__pycache__/*" "bot_utils/**/*.pyc")
  echo "Wrote $archive"
done

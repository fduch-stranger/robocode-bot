#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/env.sh"
load_repo_env "$ROOT_DIR"
source "$ROOT_DIR/scripts/lib/bots.sh"
DIST_DIR="$ROOT_DIR/dist"

cd "$ROOT_DIR"
mkdir -p "$DIST_DIR"

bot_dirs=()
while IFS= read -r bot; do
  bot_dirs+=("$bot")
done < <(discover_bot_dirs "$ROOT_DIR")

for bot_dir in "${bot_dirs[@]}"; do
  bot_name="$(basename "$bot_dir")"
  archive="$DIST_DIR/${bot_name}.zip"
  rm -f "$archive"
  (cd bots && zip -qr "$archive" "$bot_name" bot_core \
    -x "$bot_name/.DS_Store" "$bot_name/**/.DS_Store" "bot_core/.DS_Store" "bot_core/**/.DS_Store" \
    -x "$bot_name/__pycache__" "$bot_name/__pycache__/*" "$bot_name/**/*.pyc" \
    -x "bot_core/__pycache__" "bot_core/__pycache__/*" "bot_core/**/*.pyc")
  echo "Wrote $archive"
done

#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_ROOT=""
PYTHONPATH_ROOT=""
search_dir="$BOT_DIR"
while [[ "$search_dir" != "/" ]]; do
  if [[ -d "$search_dir/bots/bot_core" ]]; then
    CONFIG_ROOT="$search_dir"
    PYTHONPATH_ROOT="$search_dir/bots"
    break
  fi
  if [[ -d "$search_dir/bot_core" ]]; then
    CONFIG_ROOT="$search_dir"
    PYTHONPATH_ROOT="$search_dir"
    break
  fi
  search_dir="$(dirname "$search_dir")"
done
if [[ -z "$PYTHONPATH_ROOT" ]]; then
  echo "Could not locate bot_core from $BOT_DIR" >&2
  exit 1
fi
source "$PYTHONPATH_ROOT/bot_core/launcher_env.sh"
load_repo_env_if_available "$CONFIG_ROOT"
if [[ -n "${ROBOCODE_TELEMETRY_DIR:-}" && "$ROBOCODE_TELEMETRY_DIR" != /* ]]; then
  export ROBOCODE_TELEMETRY_DIR="$CONFIG_ROOT/$ROBOCODE_TELEMETRY_DIR"
fi
export PYTHONPATH="$PYTHONPATH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ -z "${ROBOCODE_SUPPRESS_GUI_TELEMETRY:-}" && -f "$CONFIG_ROOT/.telemetry-enabled" && ! -f "$CONFIG_ROOT/.telemetry-cli-suppressed" ]]; then
  export ROBOCODE_TELEMETRY=1
  export ROBOCODE_TELEMETRY_ROOT="$CONFIG_ROOT"
  export ROBOCODE_TELEMETRY_DIR="${ROBOCODE_TELEMETRY_DIR:-$CONFIG_ROOT/battle-results/telemetry/live}"
  export ROBOCODE_TELEMETRY_AUTOSTART="${ROBOCODE_TELEMETRY_AUTOSTART:-1}"
fi
exec "$(robocode_python_bin "$CONFIG_ROOT")" "$BOT_DIR/basic-gf-surfer-port.py"

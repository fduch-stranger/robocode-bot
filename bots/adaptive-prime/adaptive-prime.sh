#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$BOT_DIR/../.." && pwd)"
PACKAGE_ROOT="$(cd "$BOT_DIR/.." && pwd)"
if [[ -d "$ROOT_DIR/bots/bot_core" ]]; then
  CONFIG_ROOT="$ROOT_DIR"
  PYTHONPATH_ROOT="$ROOT_DIR/bots"
else
  CONFIG_ROOT="$PACKAGE_ROOT"
  PYTHONPATH_ROOT="$PACKAGE_ROOT"
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
exec "$(robocode_python_bin "$CONFIG_ROOT")" "$BOT_DIR/adaptive-prime.py"

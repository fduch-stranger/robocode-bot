#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/env.sh"
load_repo_env "$ROOT_DIR"
RUNTIME_PYTHON_BIN="$(robocode_python_bin "$ROOT_DIR")"
action="${1:-start}"
telemetry_dir="${ROBOCODE_TELEMETRY_DIR:-$ROOT_DIR/battle-results/telemetry/live}"
host="${ROBOCODE_TELEMETRY_HOST:-127.0.0.1}"
port="${ROBOCODE_TELEMETRY_PORT:-8765}"
switch_file="$ROOT_DIR/.telemetry-enabled"

usage() {
  cat <<EOF
Usage: scripts/telemetry-ui.sh [start|list|stop|stop-all|enable|disable|status] [--dir DIR] [--host HOST] [--port PORT] [--no-open]

start     Enable GUI telemetry and run the browser telemetry UI in the foreground.
list      List discovered telemetry viewers and whether their processes are running.
stop      Stop a background telemetry viewer for the selected telemetry directory.
stop-all  Stop every discovered telemetry viewer.
enable    Enable telemetry for bots launched by the Robocode GUI.
disable   Disable telemetry for bots launched by the Robocode GUI.
status    Print telemetry switch and viewer information.
EOF
}

open_browser=1
if [[ $# -gt 0 ]]; then
  shift
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      telemetry_dir="$2"
      shift 2
      ;;
    --host)
      host="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --no-open)
      open_browser=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$telemetry_dir" != /* ]]; then
  telemetry_dir="$ROOT_DIR/$telemetry_dir"
fi

viewer_pid() {
  local dir="$1"
  local lock_file="$dir/telemetry-viewer.lock"
  if [[ -f "$lock_file" ]]; then
    tr -d '[:space:]' < "$lock_file"
  fi
}

viewer_url() {
  local dir="$1"
  local url_file="$dir/telemetry-viewer.url"
  if [[ -f "$url_file" ]]; then
    tr -d '[:space:]' < "$url_file"
  fi
}

candidate_viewer_urls() {
  {
    printf 'http://%s:%s/\n' "$host" "$port"
    if [[ -f "$telemetry_dir/telemetry-viewer.url" ]]; then
      viewer_url "$telemetry_dir"
    fi
    if [[ -d "$ROOT_DIR/battle-results" ]]; then
      find "$ROOT_DIR/battle-results" -name telemetry-viewer.url -type f -exec cat {} \; 2>/dev/null
    fi
  } | awk 'NF {print}' | sort -u
}

url_telemetry_dir() {
  local url="$1"
  [[ -n "$url" ]] || return 1
  "$RUNTIME_PYTHON_BIN" - "$url" <<'PY' 2>/dev/null
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1].rstrip("/") + "/api/health", timeout=1.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception:
    raise SystemExit(1)
if payload.get("ok") and payload.get("dir"):
    print(payload["dir"])
else:
    raise SystemExit(1)
PY
}

pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_matches_viewer() {
  local pid="$1"
  local dir="$2"
  local command
  pid_running "$pid" || return 1
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == *"tools/telemetry_viewer/server.py"* && "$command" == *"$dir"* ]]
}

viewer_healthy() {
  local url="$1"
  local dir="$2"
  [[ -n "$url" ]] || return 1
  "$RUNTIME_PYTHON_BIN" - "$url" "$dir" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request
from pathlib import Path

with urllib.request.urlopen(sys.argv[1].rstrip("/") + "/api/health", timeout=1.5) as response:
    payload = json.loads(response.read().decode("utf-8"))
expected_dir = str(Path(sys.argv[2]).expanduser().resolve())
if payload.get("dir") != expected_dir:
    raise SystemExit(1)
PY
}

request_shutdown() {
  local url="$1"
  local dir="$2"
  [[ -n "$url" ]] || return 1
  viewer_healthy "$url" "$dir" || return 1
  "$RUNTIME_PYTHON_BIN" - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

urllib.request.urlopen(sys.argv[1].rstrip("/") + "/api/shutdown", timeout=3).read()
PY
}

discover_viewer_dirs() {
  {
    if [[ -f "$telemetry_dir/telemetry-viewer.lock" || -f "$telemetry_dir/telemetry-viewer.url" ]]; then
      echo "$telemetry_dir"
    fi
    if [[ -d "$ROOT_DIR/battle-results" ]]; then
      find "$ROOT_DIR/battle-results" \( -name telemetry-viewer.lock -o -name telemetry-viewer.url \) -type f -exec dirname {} \; 2>/dev/null
    fi
    while IFS= read -r candidate_url; do
      url_telemetry_dir "$candidate_url" || true
    done < <(candidate_viewer_urls)
  } | sort -u
}

healthy_url_for_dir() {
  local dir="$1"
  local candidate_url
  while IFS= read -r candidate_url; do
    if viewer_healthy "$candidate_url" "$dir"; then
      printf '%s\n' "$candidate_url"
      return 0
    fi
  done < <(candidate_viewer_urls)
  return 1
}

describe_viewer() {
  local dir="$1"
  local pid url state health
  pid="$(viewer_pid "$dir")"
  url="$(healthy_url_for_dir "$dir" || viewer_url "$dir")"
  state="stopped"
  health="unknown"
  if pid_matches_viewer "$pid" "$dir"; then
    state="running"
  fi
  if viewer_healthy "$url" "$dir"; then
    health="healthy"
    state="running"
  elif [[ -n "$url" ]]; then
    health="unreachable"
  fi
  printf '%-9s health=%-11s pid=%-8s url=%-24s dir=%s\n' "$state" "$health" "${pid:-"-"}" "${url:-"-"}" "$dir"
}

list_viewers() {
  local found=0
  while IFS= read -r dir; do
    [[ -n "$dir" ]] || continue
    describe_viewer "$dir"
    found=1
  done < <(discover_viewer_dirs)
  if [[ "$found" -eq 0 ]]; then
    echo "No telemetry viewers discovered."
  fi
}

stop_viewer() {
  local dir="$1"
  local lock_file="$dir/telemetry-viewer.lock"
  local url_file="$dir/telemetry-viewer.url"
  local pid url stopped
  pid="$(viewer_pid "$dir")"
  url="$(healthy_url_for_dir "$dir" || viewer_url "$dir")"
  stopped=0

  if request_shutdown "$url" "$dir"; then
    stopped=1
    for _ in {1..20}; do
      if ! viewer_healthy "$url" "$dir" && ! pid_matches_viewer "$pid" "$dir"; then
        break
      fi
      sleep 0.1
    done
  fi

  if [[ "$stopped" -eq 0 && -n "$pid" ]] && pid_matches_viewer "$pid" "$dir" && kill "$pid" 2>/dev/null; then
    stopped=1
  fi

  rm -f "$lock_file"
  if [[ "$stopped" -eq 1 ]]; then
    rm -f "$url_file"
    echo "Stopped telemetry viewer for $dir."
  elif [[ -n "$pid" || -n "$url" ]]; then
    if ! viewer_healthy "$url" "$dir"; then
      rm -f "$url_file"
    fi
    echo "Telemetry viewer already stopped for $dir."
  else
    echo "No telemetry viewer found for $dir."
  fi
}

case "$action" in
  start)
    mkdir -p "$telemetry_dir"
    touch "$switch_file"
    echo "Telemetry enabled for GUI-launched bots."
    echo "Telemetry dir: $telemetry_dir"
    args=(--dir "$telemetry_dir" --host "$host" --port "$port" --fallback-port)
    if [[ "$open_browser" -eq 1 ]]; then
      args+=(--open)
    fi
    exec "$RUNTIME_PYTHON_BIN" "$ROOT_DIR/tools/telemetry_viewer/server.py" "${args[@]}"
    ;;
  list)
    list_viewers
    ;;
  stop)
    stop_viewer "$telemetry_dir"
    ;;
  stop-all)
    found=0
    while IFS= read -r dir; do
      [[ -n "$dir" ]] || continue
      stop_viewer "$dir"
      found=1
    done < <(discover_viewer_dirs)
    if [[ "$found" -eq 0 ]]; then
      echo "No telemetry viewers discovered."
    fi
    ;;
  enable)
    mkdir -p "$telemetry_dir"
    touch "$switch_file"
    echo "Telemetry enabled for GUI-launched bots."
    echo "Start the viewer with: scripts/telemetry-ui.sh start"
    ;;
  disable)
    rm -f "$switch_file"
    echo "Telemetry disabled for GUI-launched bots."
    ;;
  status)
    if [[ -f "$switch_file" ]]; then
      echo "GUI telemetry: enabled"
    else
      echo "GUI telemetry: disabled"
    fi
    echo "Telemetry dir: $telemetry_dir"
    if [[ -f "$telemetry_dir/telemetry-viewer.url" ]]; then
      printf 'Viewer URL: '
      cat "$telemetry_dir/telemetry-viewer.url"
    fi
    echo
    echo "Known telemetry viewers:"
    list_viewers
    ;;
  --help|-h)
    usage
    ;;
  *)
    echo "Unknown action: $action" >&2
    usage >&2
    exit 1
    ;;
esac

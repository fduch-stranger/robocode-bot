#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/env.sh"
load_repo_env "$ROOT_DIR"
source "$ROOT_DIR/scripts/lib/bots.sh"
RUNTIME_PYTHON_BIN="$(robocode_python_bin "$ROOT_DIR")"
MVN_REPO="$ROOT_DIR/.m2/repository"
TELEMETRY_SUPPRESSION_FILE="$ROOT_DIR/.telemetry-cli-suppressed"
created_telemetry_suppression=0
run_id="$(date +%Y%m%d-%H%M%S)"
run_dir="$ROOT_DIR/battle-results/runs/$run_id"
rounds=3
results_file=""
runner_log_file=""
process_log_file=""
debug=0
debug_log_dir=""
telemetry=0
telemetry_dir=""
telemetry_viewer=0
telemetry_open=0
record=0
record_file=""
intent_diagnostics=0
intents_file=""
tick_sample=0
bot_inputs=()
legacy_inputs=()

cd "$ROOT_DIR"

cleanup() {
  if [[ "$created_telemetry_suppression" -eq 1 ]]; then
    rm -f "$TELEMETRY_SUPPRESSION_FILE"
  fi
}
trap cleanup EXIT

prepare_legacy_bot_shim() {
  local source_dir="$1"
  local shim_root="$2"
  local bot_name
  local shim_dir
  local json_file
  local script_file
  local shim_script

  bot_name="$(basename "$source_dir")"
  shim_dir="$shim_root/$bot_name"
  mkdir -p "$shim_dir"

  json_file="$(find "$source_dir" -maxdepth 1 -name '*.json' -print -quit)"
  script_file="$(find "$source_dir" -maxdepth 1 -name '*.sh' -print -quit)"
  if [[ -z "$json_file" || -z "$script_file" ]]; then
    echo "Legacy bot '$source_dir' must contain one .json and one .sh file." >&2
    exit 1
  fi

  cp "$json_file" "$shim_dir/$(basename "$json_file")"
  shim_script="$shim_dir/$(basename "$script_file")"
  cat > "$shim_script" <<EOF
#!/usr/bin/env bash
set -euo pipefail
java_tool_options="-Djava.awt.headless=true"
if /usr/bin/env java --enable-final-field-mutation=ALL-UNNAMED -version >/dev/null 2>&1; then
  java_tool_options="--enable-final-field-mutation=ALL-UNNAMED \$java_tool_options"
fi
export JAVA_TOOL_OPTIONS="\$java_tool_options\${JAVA_TOOL_OPTIONS:+ \$JAVA_TOOL_OPTIONS}"
cd "$source_dir"
exec /usr/bin/env bash "$script_file"
EOF
  chmod +x "$shim_script"

  printf '%s\n' "$shim_dir"
}

if [[ ! -x .venv/bin/python && -z "${ROBOCODE_PYTHON_BIN:-}" ]]; then
  scripts/setup.sh
  RUNTIME_PYTHON_BIN="$(robocode_python_bin "$ROOT_DIR")"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rounds)
      if [[ $# -lt 2 || ! "$2" =~ ^[1-9][0-9]*$ ]]; then
        echo "--rounds requires a positive integer." >&2
        exit 1
      fi
      rounds="$2"
      shift 2
      ;;
    --results)
      if [[ $# -lt 2 ]]; then
        echo "--results requires a file path." >&2
        exit 1
      fi
      results_file="$2"
      shift 2
      ;;
    --run-dir)
      if [[ $# -lt 2 ]]; then
        echo "--run-dir requires a directory path." >&2
        exit 1
      fi
      run_dir="$2"
      shift 2
      ;;
    --runner-log)
      if [[ $# -lt 2 ]]; then
        echo "--runner-log requires a file path." >&2
        exit 1
      fi
      runner_log_file="$2"
      shift 2
      ;;
    --process-log)
      if [[ $# -lt 2 ]]; then
        echo "--process-log requires a file path." >&2
        exit 1
      fi
      process_log_file="$2"
      shift 2
      ;;
    --debug)
      debug=1
      shift
      ;;
    --debug-log-dir)
      if [[ $# -lt 2 ]]; then
        echo "--debug-log-dir requires a directory path." >&2
        exit 1
      fi
      debug_log_dir="$2"
      shift 2
      ;;
    --telemetry)
      telemetry=1
      shift
      ;;
    --telemetry-viewer)
      telemetry=1
      telemetry_viewer=1
      shift
      ;;
    --telemetry-dir)
      if [[ $# -lt 2 ]]; then
        echo "--telemetry-dir requires a directory path." >&2
        exit 1
      fi
      telemetry=1
      telemetry_dir="$2"
      shift 2
      ;;
    --telemetry-open)
      telemetry=1
      telemetry_viewer=1
      telemetry_open=1
      shift
      ;;
    --record)
      record=1
      shift
      ;;
    --record-file)
      if [[ $# -lt 2 ]]; then
        echo "--record-file requires a recording directory path." >&2
        exit 1
      fi
      record=1
      record_file="$2"
      shift 2
      ;;
    --intent-diagnostics)
      intent_diagnostics=1
      shift
      ;;
    --intents)
      if [[ $# -lt 2 ]]; then
        echo "--intents requires a file path." >&2
        exit 1
      fi
      intent_diagnostics=1
      intents_file="$2"
      shift 2
      ;;
    --tick-sample)
      if [[ $# -lt 2 || ! "$2" =~ ^[0-9]+$ ]]; then
        echo "--tick-sample requires a non-negative integer." >&2
        exit 1
      fi
      tick_sample="$2"
      shift 2
      ;;
    --legacy)
      if [[ $# -lt 2 ]]; then
        echo "--legacy requires a bot alias, directory name, or 'all'." >&2
        exit 1
      fi
      legacy_inputs+=("$2")
      shift 2
      ;;
    --legacy-root)
      if [[ $# -lt 2 ]]; then
        echo "--legacy-root requires a directory path." >&2
        exit 1
      fi
      export ROBOCODE_LEGACY_BOTS_ROOT="$2"
      shift 2
      ;;
    --list-legacy)
      list_legacy_bots "$ROOT_DIR"
      exit 0
      ;;
    --help|-h)
      echo "Usage: scripts/run-battle.sh [--rounds N] [--run-dir DIR] [--results FILE] [--runner-log FILE] [--process-log FILE] [--debug] [--debug-log-dir DIR] [--telemetry] [--telemetry-dir DIR] [--telemetry-viewer] [--telemetry-open] [--record] [--record-file DIR] [--intent-diagnostics] [--intents FILE] [--tick-sample N] [--legacy NAME|all] [--legacy-root DIR] [--list-legacy] [bot-dir...]"
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        bot_inputs+=("$1")
        shift
      done
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      bot_inputs+=("$1")
      shift
      ;;
  esac
done

if [[ ${#legacy_inputs[@]} -gt 0 ]]; then
  for legacy in "${legacy_inputs[@]}"; do
    legacy_matches=()
    while IFS= read -r bot; do
      legacy_matches+=("$bot")
    done < <(append_legacy_bot_args "$ROOT_DIR" "$legacy")
    if [[ ${#legacy_matches[@]} -eq 0 ]]; then
      echo "No legacy bot matched '$legacy' under $(legacy_bots_root "$ROOT_DIR")." >&2
      exit 1
    fi
    bot_inputs+=("${legacy_matches[@]}")
  done
fi

if [[ ${#bot_inputs[@]} -gt 0 ]]; then
  bot_args=()
  for bot in "${bot_inputs[@]}"; do
    normalized_bot="$(normalize_bot_dir "$ROOT_DIR" "$bot")" || {
      echo "No legacy bot matched '$bot' under $(legacy_bots_root "$ROOT_DIR")." >&2
      exit 1
    }
    bot_args+=("$normalized_bot")
  done
else
  bot_args=()
  while IFS= read -r bot; do
    bot_args+=("$bot")
  done < <(discover_bot_dirs "$ROOT_DIR")
fi

if [[ ${#bot_args[@]} -lt 2 ]]; then
  echo "Need at least two bot directories to run a battle." >&2
  exit 1
fi

if [[ "$run_dir" != /* ]]; then
  run_dir="$ROOT_DIR/$run_dir"
fi
if [[ -z "$results_file" ]]; then
  results_file="$run_dir/results.json"
fi
if [[ -z "$runner_log_file" ]]; then
  runner_log_file="$run_dir/runner.log"
fi
if [[ -z "$process_log_file" ]]; then
  process_log_file="$run_dir/process.log"
fi
if [[ "$record" -eq 1 && -z "$record_file" ]]; then
  record_file="$run_dir/recordings"
fi
if [[ "$intent_diagnostics" -eq 1 && -z "$intents_file" ]]; then
  intents_file="$run_dir/intents.jsonl"
fi
if [[ "$debug" -eq 1 && -z "$debug_log_dir" ]]; then
  debug_log_dir="$run_dir/debug"
fi
if [[ "$telemetry" -eq 1 && -z "$telemetry_dir" ]]; then
  telemetry_dir="$run_dir/telemetry"
fi

if [[ "$results_file" != /* ]]; then
  results_file="$ROOT_DIR/$results_file"
fi
if [[ "$runner_log_file" != /* ]]; then
  runner_log_file="$ROOT_DIR/$runner_log_file"
fi
if [[ "$process_log_file" != /* ]]; then
  process_log_file="$ROOT_DIR/$process_log_file"
fi
if [[ "$debug_log_dir" != /* ]]; then
  debug_log_dir="$ROOT_DIR/$debug_log_dir"
fi
if [[ -n "$telemetry_dir" && "$telemetry_dir" != /* ]]; then
  telemetry_dir="$ROOT_DIR/$telemetry_dir"
fi
if [[ -n "$record_file" && "$record_file" != /* ]]; then
  record_file="$ROOT_DIR/$record_file"
fi
if [[ -n "$intents_file" && "$intents_file" != /* ]]; then
  intents_file="$ROOT_DIR/$intents_file"
fi

prepared_bot_args=()
for bot in "${bot_args[@]}"; do
  if is_legacy_bot_dir "$ROOT_DIR" "$bot"; then
    prepared_bot_args+=("$(prepare_legacy_bot_shim "$bot" "$run_dir/legacy-bots")")
  else
    prepared_bot_args+=("$bot")
  fi
done
bot_args=("${prepared_bot_args[@]}")

mkdir -p "$(dirname "$results_file")"
mkdir -p "$(dirname "$runner_log_file")"
mkdir -p "$(dirname "$process_log_file")"
runner_args=(--rounds "$rounds" --results "$results_file" --runner-log "$runner_log_file" --tick-sample "$tick_sample")
if [[ "$record" -eq 1 ]]; then
  mkdir -p "$record_file"
  runner_args+=(--record "$record_file")
fi
if [[ "$intent_diagnostics" -eq 1 ]]; then
  mkdir -p "$(dirname "$intents_file")"
  runner_args+=(--intent-diagnostics --intents "$intents_file")
fi
runner_args+=("${bot_args[@]}")

if [[ "$debug" -eq 1 ]]; then
  mkdir -p "$debug_log_dir"
  export ROBOCODE_DEBUG=1
  export ROBOCODE_LOG_DIR="$debug_log_dir"
fi
if [[ "$telemetry" -eq 1 ]]; then
  mkdir -p "$telemetry_dir"
  export ROBOCODE_TELEMETRY=1
  export ROBOCODE_TELEMETRY_ROOT="$ROOT_DIR"
  export ROBOCODE_TELEMETRY_DIR="$telemetry_dir"
  export ROBOCODE_TELEMETRY_AUTOSTART=0
  export ROBOCODE_TELEMETRY_PORT="${ROBOCODE_TELEMETRY_PORT:-8765}"
  echo "Telemetry dir: $telemetry_dir"
  if [[ "$telemetry_viewer" -eq 1 ]]; then
    viewer_args=(--dir "$telemetry_dir" --host "${ROBOCODE_TELEMETRY_HOST:-127.0.0.1}" --port "$ROBOCODE_TELEMETRY_PORT" --fallback-port)
    if [[ "$telemetry_open" -eq 1 ]]; then
      viewer_args+=(--open)
    fi
    "$RUNTIME_PYTHON_BIN" "$ROOT_DIR/tools/telemetry_viewer/server.py" \
      "${viewer_args[@]}" \
      --daemon \
      --pid-file "$telemetry_dir/telemetry-viewer.lock" \
      --log-file "$telemetry_dir/telemetry-viewer.log"
    for _ in {1..30}; do
      if [[ -f "$telemetry_dir/telemetry-viewer.url" ]]; then
        break
      fi
      sleep 0.1
    done
    if [[ -f "$telemetry_dir/telemetry-viewer.url" ]]; then
      printf 'Telemetry viewer: '
      cat "$telemetry_dir/telemetry-viewer.url"
    else
      echo "Telemetry viewer: starting; see $telemetry_dir/telemetry-viewer.log"
    fi
  fi
else
  if [[ ! -f "$TELEMETRY_SUPPRESSION_FILE" ]]; then
    : > "$TELEMETRY_SUPPRESSION_FILE"
    created_telemetry_suppression=1
  fi
  export ROBOCODE_SUPPRESS_GUI_TELEMETRY=1
  export ROBOCODE_TELEMETRY_AUTOSTART=0
fi

mvn \
  -s "$ROOT_DIR/tools/maven-central-settings.xml" \
  -Dmaven.repo.local="$MVN_REPO" \
  -q \
  -f "$ROOT_DIR/tools/battle-runner/pom.xml" \
  compile exec:java \
  -Dexec.args="${runner_args[*]}" \
  2>&1 | tee "$process_log_file"

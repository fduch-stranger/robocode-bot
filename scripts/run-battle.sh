#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MVN_REPO="$ROOT_DIR/.m2/repository"
rounds=3
results_file="$ROOT_DIR/battle-results/latest.json"
debug=0
debug_log_dir="$ROOT_DIR/battle-results/debug"
bot_inputs=()

cd "$ROOT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  scripts/setup.sh
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
    --help|-h)
      echo "Usage: scripts/run-battle.sh [--rounds N] [--results FILE] [--debug] [--debug-log-dir DIR] [bot-dir...]"
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

if [[ ${#bot_inputs[@]} -gt 0 ]]; then
  bot_args=()
  for bot in "${bot_inputs[@]}"; do
    if [[ "$bot" = /* ]]; then
      bot_args+=("$bot")
    else
      bot_args+=("$ROOT_DIR/$bot")
    fi
  done
else
  bot_args=()
  for bot in "$ROOT_DIR"/bots/*; do
    if [[ -d "$bot" ]]; then
      bot_args+=("$bot")
    fi
  done
fi

if [[ ${#bot_args[@]} -lt 2 ]]; then
  echo "Need at least two bot directories to run a battle." >&2
  exit 1
fi

if [[ "$results_file" != /* ]]; then
  results_file="$ROOT_DIR/$results_file"
fi
if [[ "$debug_log_dir" != /* ]]; then
  debug_log_dir="$ROOT_DIR/$debug_log_dir"
fi

mkdir -p "$(dirname "$results_file")"
runner_args=(--rounds "$rounds" --results "$results_file")
runner_args+=("${bot_args[@]}")

if [[ "$debug" -eq 1 ]]; then
  mkdir -p "$debug_log_dir"
  export ROBOCODE_DEBUG=1
  export ROBOCODE_LOG_DIR="$debug_log_dir"
fi

mvn \
  -s "$ROOT_DIR/tools/maven-central-settings.xml" \
  -Dmaven.repo.local="$MVN_REPO" \
  -q \
  -f "$ROOT_DIR/tools/battle-runner/pom.xml" \
  compile exec:java \
  -Dexec.args="${runner_args[*]}"

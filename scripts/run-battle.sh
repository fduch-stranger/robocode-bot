#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/bots.sh"
MVN_REPO="$ROOT_DIR/.m2/repository"
run_id="$(date +%Y%m%d-%H%M%S)"
run_dir="$ROOT_DIR/battle-results/runs/$run_id"
rounds=3
results_file=""
runner_log_file=""
process_log_file=""
debug=0
debug_log_dir=""
record=0
record_file=""
intent_diagnostics=0
intents_file=""
tick_sample=0
bot_inputs=()
legacy_inputs=()

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
      echo "Usage: scripts/run-battle.sh [--rounds N] [--run-dir DIR] [--results FILE] [--runner-log FILE] [--process-log FILE] [--debug] [--debug-log-dir DIR] [--record] [--record-file DIR] [--intent-diagnostics] [--intents FILE] [--tick-sample N] [--legacy NAME|all] [--legacy-root DIR] [--list-legacy] [bot-dir...]"
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
if [[ -n "$record_file" && "$record_file" != /* ]]; then
  record_file="$ROOT_DIR/$record_file"
fi
if [[ -n "$intents_file" && "$intents_file" != /* ]]; then
  intents_file="$ROOT_DIR/$intents_file"
fi

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

mvn \
  -s "$ROOT_DIR/tools/maven-central-settings.xml" \
  -Dmaven.repo.local="$MVN_REPO" \
  -q \
  -f "$ROOT_DIR/tools/battle-runner/pom.xml" \
  compile exec:java \
  -Dexec.args="${runner_args[*]}" \
  2>&1 | tee "$process_log_file"

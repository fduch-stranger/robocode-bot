#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

runs=3
rounds=24
run_id="$(date +%Y%m%d-%H%M%S)"
series_dir="$ROOT_DIR/battle-results/series/$run_id"
run_battle_args=()
verbose=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs)
      if [[ $# -lt 2 || ! "$2" =~ ^[1-9][0-9]*$ ]]; then
        echo "--runs requires a positive integer." >&2
        exit 1
      fi
      runs="$2"
      shift 2
      ;;
    --rounds)
      if [[ $# -lt 2 || ! "$2" =~ ^[1-9][0-9]*$ ]]; then
        echo "--rounds requires a positive integer." >&2
        exit 1
      fi
      rounds="$2"
      shift 2
      ;;
    --run-dir)
      if [[ $# -lt 2 ]]; then
        echo "--run-dir requires a directory path." >&2
        exit 1
      fi
      series_dir="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: scripts/run-battle-series.sh [--runs N] [--rounds N] [--run-dir DIR] [--verbose] [run-battle options] [bot-dir...]"
      echo "All non-series options are forwarded to scripts/run-battle.sh for each batch."
      exit 0
      ;;
    --verbose)
      verbose=1
      shift
      ;;
    *)
      run_battle_args+=("$1")
      shift
      ;;
  esac
done

if [[ "$series_dir" != /* ]]; then
  series_dir="$ROOT_DIR/$series_dir"
fi

mkdir -p "$series_dir"

for run_number in $(seq 1 "$runs"); do
  run_dir="$series_dir/run-$run_number"
  series_log="$run_dir/series.log"
  mkdir -p "$run_dir"
  echo "Series run $run_number/$runs -> $run_dir"
  if [[ "$verbose" -eq 1 ]]; then
    "$ROOT_DIR/scripts/run-battle.sh" \
      --rounds "$rounds" \
      --run-dir "$run_dir" \
      "${run_battle_args[@]}"
  else
    if ! "$ROOT_DIR/scripts/run-battle.sh" \
      --rounds "$rounds" \
      --run-dir "$run_dir" \
      "${run_battle_args[@]}" >"$series_log" 2>&1; then
      echo "Series run $run_number failed. Last log lines from $series_log:" >&2
      tail -40 "$series_log" >&2
      exit 1
    fi
    grep '^Battle results:\|^#[0-9]' "$series_log" || true
  fi
done

summary_file="$series_dir/summary.json"
python3 - "$series_dir" "$runs" "$rounds" "$summary_file" <<'PY'
import json
import pathlib
import sys

series_dir = pathlib.Path(sys.argv[1])
requested_runs = int(sys.argv[2])
rounds = int(sys.argv[3])
summary_file = pathlib.Path(sys.argv[4])

metric_names = ("totalScore", "survival", "bulletDamage", "ramDamage", "firstPlaces")
runs = []
aggregate = {}

for result_path in sorted(series_dir.glob("run-*/results.json")):
    with result_path.open() as fh:
        payload = json.load(fh)
    runs.append(
        {
            "runDir": str(result_path.parent),
            "rounds": payload.get("rounds"),
            "gameType": payload.get("gameType"),
            "results": payload.get("results", []),
        }
    )
    for result in payload.get("results", []):
        key = f"{result['name']} {result.get('version', '')}".strip()
        stats = aggregate.setdefault(
            key,
            {
                "name": result["name"],
                "version": result.get("version", ""),
                "runs": 0,
                "rankCounts": {},
                "rankSum": 0,
                **{metric: 0 for metric in metric_names},
            },
        )
        stats["runs"] += 1
        rank = str(result["rank"])
        stats["rankCounts"][rank] = stats["rankCounts"].get(rank, 0) + 1
        stats["rankSum"] += result["rank"]
        for metric in metric_names:
            stats[metric] += result.get(metric, 0)

summary_results = []
for stats in aggregate.values():
    completed_runs = max(1, stats["runs"])
    summary = {
        "name": stats["name"],
        "version": stats["version"],
        "runs": stats["runs"],
        "averageRank": round(stats["rankSum"] / completed_runs, 3),
        "rankCounts": {key: stats["rankCounts"][key] for key in sorted(stats["rankCounts"], key=int)},
    }
    for metric in metric_names:
        summary[metric] = stats[metric]
        summary[f"average{metric[0].upper()}{metric[1:]}"] = round(stats[metric] / completed_runs, 3)
    summary_results.append(summary)

summary_results.sort(
    key=lambda item: (
        item["totalScore"],
        item["firstPlaces"],
        item["survival"],
        item["bulletDamage"],
    ),
    reverse=True,
)

summary = {
    "seriesDir": str(series_dir),
    "requestedRuns": requested_runs,
    "completedRuns": len(runs),
    "roundsPerRun": rounds,
    "totalRounds": len(runs) * rounds,
    "runs": runs,
    "results": summary_results,
}

summary_file.write_text(json.dumps(summary, indent=2) + "\n")

print("Aggregate results:")
for index, result in enumerate(summary_results, start=1):
    ranks = ", ".join(f"#{rank}:{count}" for rank, count in result["rankCounts"].items())
    print(
        f"#{index} {result['name']} {result['version']} "
        f"score={result['totalScore']} avgScore={result['averageTotalScore']} "
        f"firstPlaces={result['firstPlaces']} avgRank={result['averageRank']} ranks=[{ranks}]"
    )
print(f"Wrote series summary: {summary_file}")
PY

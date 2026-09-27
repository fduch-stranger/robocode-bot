#!/usr/bin/env python3
"""Compare A/B candidate runs against a pooled baseline.

One 24-round run of identical code varies by about ±150 points, so a candidate
should be judged against every baseline run of the same code, not only the six
runs paired with it. This tool pools the runs of one or more A/B experiment
directories per side and reports the difference in standard errors.

Usage:

    tools/ab_pool.py --candidate battle-results/ab/<experiment> \
        --baseline battle-results/ab/<experiment> battle-results/ab/<earlier>

A directory may be an experiment root (`battle-results/ab/<experiment>`), in
which case the side named by the option is used, or a side/matchup directory
that contains `run-*/results.json` files directly.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TARGET_BOT = "Adaptive Prime"
METRICS = ("score", "firsts", "dealt", "taken")
METRIC_LABELS = {
    "score": "score",
    "firsts": "first places",
    "dealt": "bullet damage dealt",
    "taken": "bullet damage taken",
}
WIN_Z = 2.0


@dataclass(frozen=True)
class RunResult:
    path: str
    score: float
    firsts: float
    dealt: float
    taken: float

    def metric(self, name: str) -> float:
        return float(getattr(self, name))


def _results_files(directory: Path, side: str) -> list[Path]:
    direct = sorted(directory.glob("run-*/results.json"))
    if direct:
        return direct
    return sorted(directory.glob(f"{side}/*/run-*/results.json"))


def load_runs(directories: list[Path], side: str, target_bot: str) -> list[RunResult]:
    runs: list[RunResult] = []
    for directory in directories:
        for path in _results_files(directory, side):
            with path.open(encoding="utf-8") as handle:
                result = json.load(handle)
            entries = result.get("results", [])
            target = next((entry for entry in entries if entry.get("name") == target_bot), None)
            if target is None:
                continue
            opponents = [entry for entry in entries if entry is not target]
            runs.append(
                RunResult(
                    path=str(path.parent),
                    score=float(target.get("totalScore", 0)),
                    firsts=float(target.get("firstPlaces", 0)),
                    dealt=float(target.get("bulletDamage", 0)),
                    taken=float(sum(entry.get("bulletDamage", 0) for entry in opponents)),
                )
            )
    return runs


def mean_and_standard_error(values: list[float]) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        return values[0], float("nan")
    return statistics.mean(values), statistics.stdev(values) / len(values) ** 0.5


def compare(candidate: list[RunResult], baseline: list[RunResult]) -> dict[str, object]:
    summary: dict[str, object] = {
        "candidate_runs": len(candidate),
        "baseline_runs": len(baseline),
        "metrics": {},
    }
    metrics: dict[str, dict[str, float]] = {}
    for name in METRICS:
        candidate_mean, candidate_se = mean_and_standard_error([run.metric(name) for run in candidate])
        baseline_mean, baseline_se = mean_and_standard_error([run.metric(name) for run in baseline])
        delta = candidate_mean - baseline_mean
        delta_se = (candidate_se**2 + baseline_se**2) ** 0.5
        metrics[name] = {
            "candidate_mean": candidate_mean,
            "candidate_se": candidate_se,
            "baseline_mean": baseline_mean,
            "baseline_se": baseline_se,
            "delta": delta,
            "delta_percent": (100.0 * delta / baseline_mean) if baseline_mean else float("nan"),
            "delta_se": delta_se,
            "z": (delta / delta_se) if delta_se else float("nan"),
        }
    summary["metrics"] = metrics
    score_z = metrics["score"]["z"]
    if score_z >= WIN_Z:
        summary["decision"] = "win"
    elif score_z <= -WIN_Z:
        summary["decision"] = "negative"
    else:
        summary["decision"] = "neutral"
    return summary


def _format_side(name: str, runs: list[RunResult]) -> list[str]:
    lines = [f"{name}: {len(runs)} runs"]
    for metric in METRICS:
        mean, se = mean_and_standard_error([run.metric(metric) for run in runs])
        lines.append(f"  {METRIC_LABELS[metric]}: {mean:.1f} ± {se:.1f}")
    return lines


def format_summary(candidate: list[RunResult], baseline: list[RunResult], summary: dict[str, object]) -> str:
    lines = _format_side("candidate", candidate) + _format_side("baseline (pooled)", baseline)
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    for name in METRICS:
        values = metrics[name]
        lines.append(
            f"{METRIC_LABELS[name]}: candidate - baseline = {values['delta']:+.1f} "
            f"({values['delta_percent']:+.1f}%), SE {values['delta_se']:.1f}, z = {values['z']:+.2f}"
        )
    lines.append(f"decision: {summary['decision']} (win needs score z >= {WIN_Z:.0f})")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", nargs="+", required=True, help="Experiment or side directories for the candidate.")
    parser.add_argument("--baseline", nargs="+", required=True, help="Experiment or side directories to pool as the baseline.")
    parser.add_argument("--target-bot", default=DEFAULT_TARGET_BOT, help=f"Bot name to compare. Defaults to {DEFAULT_TARGET_BOT!r}.")
    parser.add_argument("--json-output", default=None, help="Write the summary as JSON to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidate = load_runs([Path(p) for p in args.candidate], "candidate", args.target_bot)
    baseline = load_runs([Path(p) for p in args.baseline], "baseline", args.target_bot)
    if not candidate or not baseline:
        print("no runs found for the candidate or the baseline", file=sys.stderr)
        return 1
    summary = compare(candidate, baseline)
    print(format_summary(candidate, baseline, summary))
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

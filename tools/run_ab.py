#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METRICS = ("totalScore", "survival", "bulletDamage", "ramDamage", "firstPlaces")
TARGET_BOT = "Adaptive Prime"
CHASE_BOT = "Chase Lock"
CIRCLE_BOT = "Circle Strafer"
SWEEP_BOT = "Sweep Pressure"


PRESETS: dict[str, dict[str, Any]] = {
    "adaptive-1v1-core": {
        "description": "Adaptive Prime 1v1 benchmark against the three local sparring bots.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": TARGET_BOT,
        "matchups": [
            {"name": "adaptive-vs-chase", "bots": ["bots/adaptive-prime", "bots/chase-lock"]},
            {"name": "adaptive-vs-circle", "bots": ["bots/adaptive-prime", "bots/circle-strafer"]},
            {"name": "adaptive-vs-sweep", "bots": ["bots/adaptive-prime", "bots/sweep-pressure"]},
        ],
    },
    "chase-1v1-core": {
        "description": "Chase Lock 1v1 benchmark against the other local bots.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": CHASE_BOT,
        "matchups": [
            {"name": "chase-vs-adaptive", "bots": ["bots/chase-lock", "bots/adaptive-prime"]},
            {"name": "chase-vs-circle", "bots": ["bots/chase-lock", "bots/circle-strafer"]},
            {"name": "chase-vs-sweep", "bots": ["bots/chase-lock", "bots/sweep-pressure"]},
        ],
    },
    "circle-1v1-core": {
        "description": "Circle Strafer 1v1 benchmark against the other local bots.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": CIRCLE_BOT,
        "matchups": [
            {"name": "circle-vs-adaptive", "bots": ["bots/circle-strafer", "bots/adaptive-prime"]},
            {"name": "circle-vs-chase", "bots": ["bots/circle-strafer", "bots/chase-lock"]},
            {"name": "circle-vs-sweep", "bots": ["bots/circle-strafer", "bots/sweep-pressure"]},
        ],
    },
    "sweep-1v1-core": {
        "description": "Sweep Pressure 1v1 benchmark against the other local bots.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": SWEEP_BOT,
        "matchups": [
            {"name": "sweep-vs-adaptive", "bots": ["bots/sweep-pressure", "bots/adaptive-prime"]},
            {"name": "sweep-vs-chase", "bots": ["bots/sweep-pressure", "bots/chase-lock"]},
            {"name": "sweep-vs-circle", "bots": ["bots/sweep-pressure", "bots/circle-strafer"]},
        ],
    },
    "adaptive-melee-core": {
        "description": "Local four-bot melee benchmark.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": TARGET_BOT,
        "matchups": [
            {
                "name": "adaptive-local-melee",
                "bots": [
                    "bots/adaptive-prime",
                    "bots/chase-lock",
                    "bots/circle-strafer",
                    "bots/sweep-pressure",
                ],
            }
        ],
    },
    "adaptive-1v1-boss": {
        "description": "Adaptive Prime 1v1 benchmark against configured legacy boss bots.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": TARGET_BOT,
        "matchups": [
            {"name": "adaptive-vs-drussgt", "bots": ["bots/adaptive-prime", "legacy:drussgt"]},
            {"name": "adaptive-vs-saguaro", "bots": ["bots/adaptive-prime", "legacy:saguaro"]},
            {"name": "adaptive-vs-basic-gf-surfer", "bots": ["bots/adaptive-prime", "legacy:basic-gf-surfer"]},
            {"name": "adaptive-vs-diamond", "bots": ["bots/adaptive-prime", "legacy:diamond"]},
        ],
    },
    "adaptive-1v1-basic-gf-surfer": {
        "description": "Adaptive Prime focused BasicGFSurfer 1v1 benchmark.",
        "rounds": 24,
        "repeats": 3,
        "targetBot": TARGET_BOT,
        "matchups": [
            {"name": "adaptive-vs-basic-gf-surfer", "bots": ["bots/adaptive-prime", "legacy:basic-gf-surfer"]},
        ],
    },
}


@dataclass(frozen=True)
class SideConfig:
    name: str
    repo: Path
    env: dict[str, str]


def slugify(value: str) -> str:
    allowed = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            allowed.append(char)
            previous_dash = False
        elif not previous_dash:
            allowed.append("-")
            previous_dash = True
    return "".join(allowed).strip("-") or "ab"


def repo_state(repo: Path) -> dict[str, Any]:
    def git_output(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    status = git_output("status", "--short")
    return {
        "path": str(repo),
        "gitSha": git_output("rev-parse", "HEAD"),
        "gitBranch": git_output("branch", "--show-current"),
        "dirty": bool(status),
        "statusShort": status or "",
    }


def resolve_bot_args(repo: Path, bots: list[str]) -> list[str]:
    resolved = []
    for bot in bots:
        if bot.startswith("legacy:"):
            resolved.append(bot)
        elif Path(bot).is_absolute():
            resolved.append(bot)
        else:
            resolved.append(str(repo / bot))
    return resolved


def parse_env_overrides(values: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Environment override must be KEY=VALUE: {value!r}")
        key, env_value = value.split("=", 1)
        if not key:
            raise ValueError(f"Environment override must include a key: {value!r}")
        env[key] = env_value
    return env


def read_results(result_path: Path, target_bot: str) -> dict[str, Any]:
    payload = json.loads(result_path.read_text())
    for result in payload.get("results", []):
        if result.get("name") == target_bot:
            return result
    available = ", ".join(result.get("name", "?") for result in payload.get("results", []))
    raise ValueError(f"{target_bot!r} was not found in {result_path}; available bots: {available}")


def classify_delta(
    baseline_score: int,
    score_delta: int,
    first_delta: int,
    first_regression_limit: int,
) -> str:
    score_regression_limit = -max(1, round(abs(baseline_score) * 0.02))
    if score_delta <= score_regression_limit or first_delta < first_regression_limit:
        return "regression"
    if (score_delta > 0 and first_delta >= 0) or (first_delta > 0 and score_delta >= -max(1, round(abs(baseline_score) * 0.01))):
        return "win"
    return "mixed"


def aggregate_results(
    experiment_dir: Path,
    preset: dict[str, Any],
    repeats: int,
    target_bot: str,
) -> dict[str, Any]:
    matchup_summaries = []
    totals = {
        "baseline": {metric: 0 for metric in METRICS},
        "candidate": {metric: 0 for metric in METRICS},
    }

    for matchup in preset["matchups"]:
        matchup_name = matchup["name"]
        side_totals = {
            "baseline": {metric: 0 for metric in METRICS},
            "candidate": {metric: 0 for metric in METRICS},
        }
        runs = []

        for repeat in range(1, repeats + 1):
            run_record: dict[str, Any] = {"repeat": repeat}
            for side in ("baseline", "candidate"):
                result_path = experiment_dir / side / matchup_name / f"run-{repeat}" / "results.json"
                result = read_results(result_path, target_bot)
                run_record[side] = {"resultPath": str(result_path), "target": result}
                for metric in METRICS:
                    value = int(result.get(metric, 0))
                    side_totals[side][metric] += value
                    totals[side][metric] += value
            runs.append(run_record)

        score_delta = side_totals["candidate"]["totalScore"] - side_totals["baseline"]["totalScore"]
        first_delta = side_totals["candidate"]["firstPlaces"] - side_totals["baseline"]["firstPlaces"]
        matchup_summaries.append(
            {
                "name": matchup_name,
                "bots": matchup["bots"],
                "repeats": repeats,
                "baseline": side_totals["baseline"],
                "candidate": side_totals["candidate"],
                "delta": {metric: side_totals["candidate"][metric] - side_totals["baseline"][metric] for metric in METRICS},
                "decision": classify_delta(
                    side_totals["baseline"]["totalScore"],
                    score_delta,
                    first_delta,
                    -repeats,
                ),
                "runs": runs,
            }
        )

    total_score_delta = totals["candidate"]["totalScore"] - totals["baseline"]["totalScore"]
    total_first_delta = totals["candidate"]["firstPlaces"] - totals["baseline"]["firstPlaces"]
    summary = {
        "experimentDir": str(experiment_dir),
        "targetBot": target_bot,
        "matchups": matchup_summaries,
        "totals": {
            "baseline": totals["baseline"],
            "candidate": totals["candidate"],
            "delta": {metric: totals["candidate"][metric] - totals["baseline"][metric] for metric in METRICS},
            "decision": classify_delta(
                totals["baseline"]["totalScore"],
                total_score_delta,
                total_first_delta,
                -len(preset["matchups"]) * repeats,
            ),
        },
    }
    return summary


def write_summary_markdown(summary: dict[str, Any], destination: Path) -> None:
    lines = [
        "# A/B Battle Summary",
        "",
        f"Target bot: `{summary['targetBot']}`",
        "",
        "| Matchup | Decision | Baseline score | Candidate score | Score delta | Baseline 1sts | Candidate 1sts | 1sts delta |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for matchup in summary["matchups"]:
        lines.append(
            "| {name} | {decision} | {bs} | {cs} | {ds} | {bf} | {cf} | {df} |".format(
                name=matchup["name"],
                decision=matchup["decision"],
                bs=matchup["baseline"]["totalScore"],
                cs=matchup["candidate"]["totalScore"],
                ds=matchup["delta"]["totalScore"],
                bf=matchup["baseline"]["firstPlaces"],
                cf=matchup["candidate"]["firstPlaces"],
                df=matchup["delta"]["firstPlaces"],
            )
        )
    totals = summary["totals"]
    lines.extend(
        [
            "",
            "## Total",
            "",
            f"Decision: `{totals['decision']}`",
            "",
            f"- Baseline score: `{totals['baseline']['totalScore']}`",
            f"- Candidate score: `{totals['candidate']['totalScore']}`",
            f"- Score delta: `{totals['delta']['totalScore']}`",
            f"- Baseline first places: `{totals['baseline']['firstPlaces']}`",
            f"- Candidate first places: `{totals['candidate']['firstPlaces']}`",
            f"- First-place delta: `{totals['delta']['firstPlaces']}`",
            "",
        ]
    )
    destination.write_text("\n".join(lines))


def run_command(command: list[str], cwd: Path, log_file: Path, verbose: bool, env: dict[str, str] | None = None) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if verbose:
        print("Running:", " ".join(command), flush=True)
    with log_file.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            if verbose:
                print(line, end="")
        process.wait()
    if process.returncode != 0:
        tail = "\n".join(log_file.read_text(errors="replace").splitlines()[-40:])
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(command)}\n{tail}")
    if not verbose:
        lines = log_file.read_text(errors="replace").splitlines()
        for line in lines:
            if line.startswith("Battle results:") or line.startswith("#"):
                print(line)


def telemetry_warning(repo: Path) -> str | None:
    script = repo / "scripts" / "telemetry-ui.sh"
    if not script.exists():
        return None
    result = subprocess.run(
        [str(script), "list"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout.strip()
    if "No telemetry viewers discovered." not in output:
        return output
    return None


def run_experiment(args: argparse.Namespace) -> int:
    root_dir = Path(__file__).resolve().parents[1]
    preset = PRESETS[args.preset]
    rounds = args.rounds if args.rounds is not None else int(preset["rounds"])
    repeats = args.repeats if args.repeats is not None else int(preset["repeats"])
    target_bot = args.target_bot or str(preset.get("targetBot", TARGET_BOT))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    experiment_name = slugify(args.name)
    experiment_dir = Path(args.run_dir) if args.run_dir else root_dir / "battle-results" / "ab" / f"{timestamp}-{experiment_name}"
    if not experiment_dir.is_absolute():
        experiment_dir = root_dir / experiment_dir

    sides = [
        SideConfig("baseline", Path(args.baseline).resolve(), parse_env_overrides(args.baseline_env)),
        SideConfig("candidate", Path(args.candidate).resolve(), parse_env_overrides(args.candidate_env)),
    ]
    experiment_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "name": args.name,
        "preset": args.preset,
        "description": preset["description"],
        "rounds": rounds,
        "repeats": repeats,
        "targetBot": target_bot,
        "command": sys.argv,
        "telemetry": "on" if args.telemetry else "off",
        "sides": {
            side.name: {
                **repo_state(side.repo),
                "env": side.env,
            }
            for side in sides
        },
        "matchups": preset["matchups"],
    }
    (experiment_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"A/B experiment: {experiment_dir}")
    print(f"Preset: {args.preset}, rounds={rounds}, repeats={repeats}")
    for side in sides:
        run_battle = side.repo / "scripts" / "run-battle.sh"
        if not run_battle.exists():
            raise FileNotFoundError(f"Missing run-battle script for {side.name}: {run_battle}")
        for matchup in preset["matchups"]:
            for repeat in range(1, repeats + 1):
                run_dir = experiment_dir / side.name / matchup["name"] / f"run-{repeat}"
                command = [
                    str(run_battle),
                    "--rounds",
                    str(rounds),
                    "--run-dir",
                    str(run_dir),
                ]
                if args.telemetry:
                    command.append("--telemetry")
                command.extend(resolve_bot_args(side.repo, matchup["bots"]))
                print(f"{side.name} {matchup['name']} run {repeat}/{repeats}")
                side_env = {**os.environ, **side.env}
                run_command(command, side.repo, run_dir / "ab-run.log", args.verbose, side_env)

    warnings = {}
    if not args.telemetry:
        for side in sides:
            warning = telemetry_warning(side.repo)
            if warning:
                warnings[side.name] = warning
    if warnings:
        print("Telemetry warning: viewer(s) discovered after no-telemetry A/B run.", file=sys.stderr)
        for side, warning in warnings.items():
            print(f"[{side}]\n{warning}", file=sys.stderr)

    summary = aggregate_results(experiment_dir, preset, repeats, target_bot)
    if warnings:
        summary["warnings"] = {"telemetry": warnings}
    (experiment_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_summary_markdown(summary, experiment_dir / "summary.md")
    print(f"Wrote summary: {experiment_dir / 'summary.md'}")
    totals = summary["totals"]
    print(
        "Total: decision={decision} score {baseline}->{candidate} delta={delta} firsts {baseline_firsts}->{candidate_firsts} delta={first_delta}".format(
            decision=totals["decision"],
            baseline=totals["baseline"]["totalScore"],
            candidate=totals["candidate"]["totalScore"],
            delta=totals["delta"]["totalScore"],
            baseline_firsts=totals["baseline"]["firstPlaces"],
            candidate_firsts=totals["candidate"]["firstPlaces"],
            first_delta=totals["delta"]["firstPlaces"],
        )
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    root_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run repeatable A/B battle benchmarks.")
    parser.add_argument("--name", required=True, help="Experiment name used in the output directory.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="adaptive-1v1-core")
    parser.add_argument("--baseline", default=str(root_dir), help="Baseline repo/worktree path.")
    parser.add_argument("--candidate", default=str(root_dir), help="Candidate repo/worktree path.")
    parser.add_argument("--baseline-env", action="append", default=[], help="Env override for baseline runs, KEY=VALUE.")
    parser.add_argument("--candidate-env", action="append", default=[], help="Env override for candidate runs, KEY=VALUE.")
    parser.add_argument("--rounds", type=int, default=None, help="Override preset rounds.")
    parser.add_argument("--repeats", type=int, default=None, help="Override preset repeat count.")
    parser.add_argument("--run-dir", default=None, help="Output directory. Defaults to battle-results/ab/<timestamp>-<name>.")
    parser.add_argument("--target-bot", default=None, help=f"Bot name to compare. Defaults to {TARGET_BOT!r}.")
    parser.add_argument("--telemetry", action="store_true", help="Enable telemetry JSONL for each battle run.")
    parser.add_argument("--verbose", action="store_true", help="Write full battle output to the terminal as well as logs.")
    args = parser.parse_args(argv)
    if args.rounds is not None and args.rounds < 1:
        parser.error("--rounds must be positive")
    if args.repeats is not None and args.repeats < 1:
        parser.error("--repeats must be positive")
    for label, values in (("--baseline-env", args.baseline_env), ("--candidate-env", args.candidate_env)):
        try:
            parse_env_overrides(values)
        except ValueError as error:
            parser.error(f"{label}: {error}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return run_experiment(args)


if __name__ == "__main__":
    raise SystemExit(main())

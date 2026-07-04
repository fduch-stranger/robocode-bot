#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


BOT_STATE_RE = re.compile(r"(?:^|\s)(?P<key>[A-Za-z][A-Za-z0-9_.]*)=(?P<value>\S+)")
SCORE_METRICS = ("score", "survival", "bulletDamage", "ramDamage", "firstPlaces")


@dataclass(frozen=True)
class BotState:
    round: int
    turn: int
    name: str
    x: float
    y: float
    speed: float
    energy: float


@dataclass(frozen=True)
class RoundScore:
    round: int
    name: str
    score: int
    survival: int
    bulletDamage: int
    ramDamage: int
    firstPlaces: int


@dataclass
class RoundMotion:
    round: int
    samples: int = 0
    firstTurn: int | None = None
    lastTurn: int | None = None
    sampledTurns: int = 0
    sampledDistance: float = 0.0
    longestStationaryTurns: int = 0
    stationaryStartTurn: int | None = None
    stationaryEndTurn: int | None = None
    suspect: bool = False


@dataclass
class BotMotion:
    name: str
    rounds: list[RoundMotion]
    suspect: bool
    cleanRounds: int
    suspectRounds: int


@dataclass
class ScoreAggregate:
    rounds: int = 0
    score: int = 0
    survival: int = 0
    bulletDamage: int = 0
    ramDamage: int = 0
    firstPlaces: int = 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect sampled runner.log bot.state lines for live bots that stop moving for too long. "
            "Run battles with scripts/run-battle.sh --tick-sample N before using this tool."
        )
    )
    parser.add_argument("path", type=Path, help="Path to runner.log, a run directory, or a series directory")
    parser.add_argument("--bot", action="append", default=[], help="Bot name to inspect. Can be repeated.")
    parser.add_argument("--max-stationary-turns", type=int, default=100)
    parser.add_argument("--stationary-distance", type=float, default=0.5)
    parser.add_argument("--speed-threshold", type=float, default=0.05)
    parser.add_argument("--min-energy", type=float, default=0.1)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--warn-only", action="store_true", help="Always exit 0 after reporting suspects.")
    return parser.parse_args(argv)


def normalized_name(name: str) -> str:
    return name.replace(" ", "_")


def parse_runner_log(path: Path) -> list[BotState]:
    states: list[BotState] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "event=bot.state" not in line:
                continue
            fields = dict(BOT_STATE_RE.findall(line))
            try:
                states.append(
                    BotState(
                        round=int(fields["round"]),
                        turn=int(fields["turn"]),
                        name=fields["name"],
                        x=float(fields["x"]),
                        y=float(fields["y"]),
                        speed=float(fields["speed"]),
                        energy=float(fields["energy"]),
                    )
                )
            except (KeyError, ValueError):
                continue
    return states


def discover_runner_logs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("**/runner.log"))
    return []


def parse_round_scores(path: Path) -> list[RoundScore]:
    cumulative: dict[str, dict[str, int]] = {}
    scores: list[RoundScore] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if "event=round.result" not in line:
                continue
            fields = dict(BOT_STATE_RE.findall(line))
            try:
                name = fields["name"]
                current = {metric: int(fields[metric]) for metric in SCORE_METRICS}
                previous = cumulative.get(name, {metric: 0 for metric in SCORE_METRICS})
                delta = {metric: current[metric] - previous[metric] for metric in SCORE_METRICS}
                cumulative[name] = current
                scores.append(
                    RoundScore(
                        round=int(fields["round"]),
                        name=name,
                        score=delta["score"],
                        survival=delta["survival"],
                        bulletDamage=delta["bulletDamage"],
                        ramDamage=delta["ramDamage"],
                        firstPlaces=delta["firstPlaces"],
                    )
                )
            except (KeyError, ValueError):
                continue
    return scores


def analyze_motion(
    states: list[BotState],
    *,
    bot_filters: set[str],
    stationary_distance: float,
    speed_threshold: float,
    max_stationary_turns: int,
    min_energy: float,
) -> list[BotMotion]:
    by_bot: dict[str, dict[int, list[BotState]]] = {}
    for state in states:
        name = normalized_name(state.name)
        if bot_filters and name not in bot_filters:
            continue
        by_bot.setdefault(name, {}).setdefault(state.round, []).append(state)

    motions: list[BotMotion] = []
    for name, by_round in sorted(by_bot.items()):
        round_motions = [
            analyze_round(
                round_number,
                sorted(round_states, key=lambda item: item.turn),
                stationary_distance=stationary_distance,
                speed_threshold=speed_threshold,
                max_stationary_turns=max_stationary_turns,
                min_energy=min_energy,
            )
            for round_number, round_states in sorted(by_round.items())
        ]
        suspect_rounds = sum(1 for item in round_motions if item.suspect)
        motions.append(
            BotMotion(
                name=name,
                rounds=round_motions,
                suspect=suspect_rounds > 0,
                cleanRounds=len(round_motions) - suspect_rounds,
                suspectRounds=suspect_rounds,
            )
        )
    return motions


def analyze_round(
    round_number: int,
    states: list[BotState],
    *,
    stationary_distance: float,
    speed_threshold: float,
    max_stationary_turns: int,
    min_energy: float,
) -> RoundMotion:
    motion = RoundMotion(round=round_number, samples=len(states))
    if not states:
        return motion

    motion.firstTurn = states[0].turn
    motion.lastTurn = states[-1].turn
    motion.sampledTurns = max(0, states[-1].turn - states[0].turn)

    run_start: int | None = None
    previous = states[0]
    for current in states[1:]:
        delta = math.hypot(current.x - previous.x, current.y - previous.y)
        motion.sampledDistance += delta
        both_alive = previous.energy > min_energy and current.energy > min_energy
        stationary = both_alive and delta <= stationary_distance and abs(current.speed) <= speed_threshold
        if stationary:
            if run_start is None:
                run_start = previous.turn
            span = current.turn - run_start
            if span > motion.longestStationaryTurns:
                motion.longestStationaryTurns = span
                motion.stationaryStartTurn = run_start
                motion.stationaryEndTurn = current.turn
        else:
            run_start = None
        previous = current

    motion.sampledDistance = round(motion.sampledDistance, 3)
    motion.suspect = motion.longestStationaryTurns >= max_stationary_turns
    return motion


def score_split(round_scores: list[RoundScore], excluded_rounds: set[int]) -> dict[str, Any] | None:
    if not round_scores:
        return None

    by_bot: dict[str, dict[str, ScoreAggregate]] = {}
    for score in round_scores:
        section = "suspect" if score.round in excluded_rounds else "clean"
        bot = by_bot.setdefault(
            score.name,
            {
                "all": ScoreAggregate(),
                "clean": ScoreAggregate(),
                "suspect": ScoreAggregate(),
            },
        )
        add_score(bot["all"], score)
        add_score(bot[section], score)

    return {
        "excludedRounds": sorted(excluded_rounds),
        "bots": [
            {
                "name": name,
                "all": asdict(sections["all"]),
                "clean": asdict(sections["clean"]),
                "suspect": asdict(sections["suspect"]),
            }
            for name, sections in sorted(by_bot.items())
        ],
    }


def add_score(aggregate: ScoreAggregate, score: RoundScore) -> None:
    aggregate.rounds += 1
    aggregate.score += score.score
    aggregate.survival += score.survival
    aggregate.bulletDamage += score.bulletDamage
    aggregate.ramDamage += score.ramDamage
    aggregate.firstPlaces += score.firstPlaces


def result_payload(runner_log: Path, motions: list[BotMotion], args: argparse.Namespace) -> dict[str, Any]:
    suspects = [
        {
            "bot": motion.name,
            "round": round_motion.round,
            "longestStationaryTurns": round_motion.longestStationaryTurns,
            "stationaryStartTurn": round_motion.stationaryStartTurn,
            "stationaryEndTurn": round_motion.stationaryEndTurn,
        }
        for motion in motions
        for round_motion in motion.rounds
        if round_motion.suspect
    ]
    payload = {
        "runnerLog": str(runner_log),
        "status": "suspect" if suspects else "ok",
        "thresholds": {
            "maxStationaryTurns": args.max_stationary_turns,
            "stationaryDistance": args.stationary_distance,
            "speedThreshold": args.speed_threshold,
            "minEnergy": args.min_energy,
        },
        "bots": [asdict(motion) for motion in motions],
        "suspects": suspects,
    }
    split = score_split(parse_round_scores(runner_log), {item["round"] for item in suspects})
    if split is not None:
        payload["scoreSummary"] = split
    return payload


def aggregate_run_payloads(path: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, dict[str, ScoreAggregate]] = {}
    excluded_rounds = []
    for run in runs:
        score_summary = run.get("scoreSummary")
        if not isinstance(score_summary, dict):
            continue
        excluded_rounds.append(
            {
                "runnerLog": run["runnerLog"],
                "rounds": score_summary.get("excludedRounds", []),
            }
        )
        for bot in score_summary.get("bots", []):
            name = str(bot["name"])
            sections = aggregate.setdefault(
                name,
                {
                    "all": ScoreAggregate(),
                    "clean": ScoreAggregate(),
                    "suspect": ScoreAggregate(),
                },
            )
            for section_name in ("all", "clean", "suspect"):
                add_aggregate(sections[section_name], bot[section_name])

    payload = {
        "path": str(path),
        "status": "suspect" if any(run["status"] == "suspect" for run in runs) else "ok",
        "runs": runs,
    }
    if aggregate:
        payload["scoreSummary"] = {
            "excludedRoundsByRun": excluded_rounds,
            "bots": [
                {
                    "name": name,
                    "all": asdict(sections["all"]),
                    "clean": asdict(sections["clean"]),
                    "suspect": asdict(sections["suspect"]),
                }
                for name, sections in sorted(aggregate.items())
            ],
        }
    return payload


def add_aggregate(aggregate: ScoreAggregate, values: dict[str, int]) -> None:
    aggregate.rounds += int(values["rounds"])
    aggregate.score += int(values["score"])
    aggregate.survival += int(values["survival"])
    aggregate.bulletDamage += int(values["bulletDamage"])
    aggregate.ramDamage += int(values["ramDamage"])
    aggregate.firstPlaces += int(values["firstPlaces"])


def print_summary(payload: dict[str, Any]) -> None:
    if "runs" in payload:
        print(f"Bot motion sanity: {payload['status'].upper()} path={payload['path']}")
        for run in payload["runs"]:
            print(f"Run: {run['runnerLog']}")
            print_summary(run)
        if "scoreSummary" in payload:
            print("Aggregate score split:")
            for bot in payload["scoreSummary"]["bots"]:
                clean = bot["clean"]
                suspect = bot["suspect"]
                print(
                    f"- {bot['name']}: cleanScore={clean['score']} cleanRounds={clean['rounds']} "
                    f"suspectScore={suspect['score']} suspectRounds={suspect['rounds']}"
                )
        return

    print(f"Bot motion sanity: {payload['status'].upper()}")
    for bot in payload["bots"]:
        suspect_rounds = [item for item in bot["rounds"] if item["suspect"]]
        longest = max((item["longestStationaryTurns"] for item in bot["rounds"]), default=0)
        print(
            f"- {bot['name']}: rounds={len(bot['rounds'])} cleanRounds={bot['cleanRounds']} "
            f"suspectRounds={bot['suspectRounds']} longestStationaryTurns={longest}"
        )
        for item in suspect_rounds:
            print(
                "  suspect round={round} stationaryTurns={longestStationaryTurns} "
                "turns={stationaryStartTurn}-{stationaryEndTurn} sampledDistance={sampledDistance}".format(**item)
            )
    if "scoreSummary" in payload:
        excluded = payload["scoreSummary"]["excludedRounds"]
        print(f"Score split: excludedRounds={excluded}")
        for bot in payload["scoreSummary"]["bots"]:
            clean = bot["clean"]
            suspect = bot["suspect"]
            print(
                f"- {bot['name']}: cleanScore={clean['score']} cleanRounds={clean['rounds']} "
                f"suspectScore={suspect['score']} suspectRounds={suspect['rounds']}"
            )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    runner_logs = discover_runner_logs(args.path)
    if not runner_logs:
        print(f"No runner.log files found under {args.path}.", file=sys.stderr)
        return 2

    bot_filters = {normalized_name(bot) for bot in args.bot}
    run_payloads = []
    for runner_log in runner_logs:
        states = parse_runner_log(runner_log)
        if not states:
            continue
        motions = analyze_motion(
            states,
            bot_filters=bot_filters,
            stationary_distance=args.stationary_distance,
            speed_threshold=args.speed_threshold,
            max_stationary_turns=args.max_stationary_turns,
            min_energy=args.min_energy,
        )
        if motions:
            run_payloads.append(result_payload(runner_log, motions, args))

    if not run_payloads:
        if bot_filters:
            print(f"No sampled bot.state lines matched: {', '.join(sorted(bot_filters))}", file=sys.stderr)
        else:
            print("No sampled bot.state lines found. Rerun the battle with --tick-sample N.", file=sys.stderr)
        return 2

    payload = run_payloads[0] if len(run_payloads) == 1 else aggregate_run_payloads(args.path, run_payloads)
    print_summary(payload)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if payload["status"] == "suspect" and not args.warn_only:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

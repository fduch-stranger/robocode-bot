#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROUND_RESULT_RE = re.compile(
    r"event=round\.result round=(?P<round>\d+) rank=(?P<rank>\d+) name=(?P<name>\S+) "
    r"score=(?P<score>\d+) survival=(?P<survival>\d+) bulletDamage=(?P<bulletDamage>\d+) "
    r"ramDamage=(?P<ramDamage>\d+) firstPlaces=(?P<firstPlaces>\d+)"
)
SCORE_METRICS = ("score", "survival", "bulletDamage", "ramDamage", "firstPlaces")
COUNT_METRICS = ("shots", "hits", "dynamicShots", "dynamicHits")


@dataclass(frozen=True)
class RoundSummary:
    round: int
    score: int = 0
    survival: int = 0
    bulletDamage: int = 0
    ramDamage: int = 0
    firstPlaces: int = 0
    shots: int = 0
    hits: int = 0
    dynamicShots: int = 0
    dynamicHits: int = 0
    accuracy: float = 0.0
    dynamicAccuracy: float = 0.0
    dynamicWaveVisits: int = 0
    dynamicErrorVisits: int = 0
    dynamicAvgError: float = 0.0
    dynamicAvgAbsError: float = 0.0
    dynamicAmbiguousVisits: int = 0
    dynamicAmbiguousRate: float = 0.0
    dynamicAimConfidenceVisits: int = 0
    dynamicAvgAimConfidence: float = 0.0
    dynamicPeakRatioVisits: int = 0
    dynamicAvgPeakScoreRatio: float = 0.0
    dynamicBandwidthVisits: int = 0
    dynamicAvgEffectiveBandwidth: float = 0.0
    excludedGlitch: bool = False


@dataclass(frozen=True)
class AggregateSummary:
    runs: int = 0
    rounds: int = 0
    score: int = 0
    survival: int = 0
    bulletDamage: int = 0
    ramDamage: int = 0
    firstPlaces: int = 0
    shots: int = 0
    hits: int = 0
    accuracy: float = 0.0
    dynamicShots: int = 0
    dynamicHits: int = 0
    dynamicAccuracy: float = 0.0
    dynamicWaveVisits: int = 0
    dynamicErrorVisits: int = 0
    dynamicAvgError: float = 0.0
    dynamicAvgAbsError: float = 0.0
    dynamicAmbiguousVisits: int = 0
    dynamicAmbiguousRate: float = 0.0
    dynamicAimConfidenceVisits: int = 0
    dynamicAvgAimConfidence: float = 0.0
    dynamicPeakRatioVisits: int = 0
    dynamicAvgPeakScoreRatio: float = 0.0
    dynamicBandwidthVisits: int = 0
    dynamicAvgEffectiveBandwidth: float = 0.0
    excludedRounds: int = 0
    unpairedRounds: int = 0


@dataclass(frozen=True)
class RunSummary:
    side: str
    runDir: str
    raw: AggregateSummary
    filtered: AggregateSummary
    rounds: tuple[RoundSummary, ...]
    warnings: tuple[str, ...] = ()


def main() -> int:
    args = _parse_args()
    summary = analyze_experiment(
        [Path(path) for path in args.paths],
        bot=args.bot,
        target_name=args.target_name,
        threshold=args.threshold,
    )
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _print_summary(summary)
    warnings = summary["warnings"]
    if warnings and not args.allow_missing_data:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze BasicGFSurfer-style runs and exclude likely stuck-surfer high-accuracy rounds.",
    )
    parser.add_argument("paths", nargs="+", help="Run directories or experiment directories containing run directories.")
    parser.add_argument("--bot", default="adaptive-prime", help="Telemetry bot name to analyze.")
    parser.add_argument(
        "--target-name",
        default="Adaptive_Prime",
        help="Runner-log target name. Spaces and underscores are treated equivalently.",
    )
    parser.add_argument(
        "--threshold",
        type=_accuracy_threshold,
        default=0.30,
        help="Exclude rounds where bot hit accuracy is greater than this value.",
    )
    parser.add_argument("--json-output", help="Write structured summary JSON to this path.")
    parser.add_argument(
        "--allow-missing-data",
        action="store_true",
        help="Print warnings but return success when logs or telemetry are incomplete.",
    )
    return parser.parse_args()


def analyze_experiment(
    roots: list[Path],
    *,
    bot: str = "adaptive-prime",
    target_name: str = "Adaptive_Prime",
    threshold: float = 0.30,
) -> dict[str, Any]:
    if threshold < 0.0 or threshold > 1.0:
        raise ValueError("threshold must be between 0.0 and 1.0")
    run_dirs = discover_run_dirs(roots)
    runs = [analyze_run(run_dir, bot=bot, target_name=target_name, threshold=threshold) for run_dir in run_dirs]
    sides = sorted({run.side for run in runs})
    raw = {side: _aggregate_runs([run.raw for run in runs if run.side == side]) for side in sides}
    filtered = {side: _aggregate_runs([run.filtered for run in runs if run.side == side]) for side in sides}
    paired_filtered = _paired_filtered_summary(runs)
    warnings = [f"{run.runDir}: {warning}" for run in runs for warning in run.warnings]
    if not run_dirs:
        warnings.append("no run directories discovered")
    warnings.extend(paired_filtered.pop("warnings", []))
    return {
        "threshold": threshold,
        "bot": bot,
        "targetName": target_name,
        "runCount": len(runs),
        "warnings": warnings,
        "runs": [run_to_dict(run) for run in runs],
        "raw": _with_delta(raw),
        "filtered": _with_delta(filtered),
        "pairedFiltered": paired_filtered,
    }


def discover_run_dirs(roots: list[Path]) -> list[Path]:
    run_dirs: set[Path] = set()
    for root in roots:
        if _looks_like_run_dir(root):
            run_dirs.add(root)
            continue
        for runner_log in root.glob("**/runner.log"):
            run_dirs.add(runner_log.parent)
        for results_file in root.glob("**/results.json"):
            run_dirs.add(results_file.parent)
        for telemetry_dir in root.glob("**/telemetry"):
            if telemetry_dir.is_dir():
                run_dirs.add(telemetry_dir.parent)
        for side in ("baseline", "candidate"):
            side_dir = root / side
            if side_dir.is_dir():
                run_dirs.update(child for child in side_dir.iterdir() if _has_run_artifacts(child))
    return sorted(run_dirs)


def analyze_run(
    run_dir: Path,
    *,
    bot: str = "adaptive-prime",
    target_name: str = "Adaptive_Prime",
    threshold: float = 0.30,
) -> RunSummary:
    scores = _round_scores(run_dir / "runner.log", target_name)
    accuracy = _round_accuracy(run_dir / "telemetry", bot, threshold)
    round_count = max([*scores.keys(), *accuracy.keys()], default=0)
    rounds = tuple(
        _round_summary(index, scores.get(index, {}), accuracy.get(index, {}), threshold)
        for index in range(1, round_count + 1)
    )
    warnings = _run_warnings(run_dir, scores, accuracy)
    return RunSummary(
        side=_side_for_run_dir(run_dir),
        runDir=str(run_dir),
        raw=_aggregate_rounds(rounds, filtered=False),
        filtered=_aggregate_rounds(rounds, filtered=True),
        rounds=rounds,
        warnings=warnings,
    )


def run_to_dict(run: RunSummary) -> dict[str, Any]:
    return {
        "side": run.side,
        "runDir": run.runDir,
        "raw": asdict(run.raw),
        "filtered": asdict(run.filtered),
        "rounds": [asdict(round_summary) for round_summary in run.rounds],
        "warnings": list(run.warnings),
    }


def _round_scores(runner_log: Path, target_name: str) -> dict[int, dict[str, int]]:
    target = _normalize_name(target_name)
    cumulative: list[tuple[int, dict[str, int]]] = []
    if not runner_log.exists():
        return {}
    for line in runner_log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ROUND_RESULT_RE.search(line)
        if match is None or _normalize_name(match.group("name")) != target:
            continue
        cumulative.append(
            (
                int(match.group("round")),
                {metric: int(match.group(metric)) for metric in SCORE_METRICS},
            )
        )
    previous = {metric: 0 for metric in SCORE_METRICS}
    per_round: dict[int, dict[str, int]] = {}
    for round_number, current in cumulative:
        per_round[round_number] = {metric: current[metric] - previous[metric] for metric in SCORE_METRICS}
        previous = current
    return per_round


def _round_accuracy(telemetry_dir: Path, bot: str, threshold: float) -> dict[int, dict[str, int | float | bool]]:
    events = _read_bot_events(telemetry_dir, bot)
    if not events:
        return {}
    rounds: dict[int, dict[str, int | float | bool]] = defaultdict(_accuracy_bucket)
    current_round = 1
    previous_turn: int | None = None
    bullet_modes: dict[str, str] = {}
    pending_hits: dict[str, int] = defaultdict(int)
    rounds[current_round]
    for event in events:
        name = event.get("event")
        if name == "round.reset":
            current_round += 1
            previous_turn = None
            bullet_modes.clear()
            pending_hits.clear()
            rounds[current_round]
            continue
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        bullet_id = _bullet_id(fields)
        resolves_pending_hit = name == "bullet.fired" and bullet_id is not None and bullet_id in pending_hits
        turn = event.get("turn")
        if isinstance(turn, int):
            if previous_turn is not None and turn < previous_turn and not resolves_pending_hit:
                current_round += 1
                bullet_modes.clear()
                pending_hits.clear()
                rounds[current_round]
            previous_turn = turn
        mode = str(fields["aim_mode"]) if fields.get("aim_mode") else None
        bucket = rounds[current_round]
        if name == "bullet.fired":
            bucket["shots"] = int(bucket["shots"]) + 1
            if mode is not None and bullet_id is not None:
                bullet_modes[bullet_id] = mode
            if mode == "dynamic_cluster":
                bucket["dynamicShots"] = int(bucket["dynamicShots"]) + 1
                if bullet_id is not None and pending_hits.get(bullet_id):
                    bucket["dynamicHits"] = int(bucket["dynamicHits"]) + pending_hits.pop(bullet_id)
        elif name == "bullet.hit_bot":
            bucket["hits"] = int(bucket["hits"]) + 1
            if mode is None and bullet_id is not None:
                mode = bullet_modes.get(bullet_id)
            if mode == "dynamic_cluster":
                bucket["dynamicHits"] = int(bucket["dynamicHits"]) + 1
            elif mode is None and bullet_id is not None:
                pending_hits[bullet_id] += 1
        elif name == "gun.wave_visit":
            _record_dynamic_wave_visit(bucket, fields)

    for bucket in rounds.values():
        shots = int(bucket["shots"])
        hits = int(bucket["hits"])
        dynamic_shots = int(bucket["dynamicShots"])
        dynamic_hits = int(bucket["dynamicHits"])
        bucket["accuracy"] = hits / shots if shots else 0.0
        bucket["dynamicAccuracy"] = dynamic_hits / dynamic_shots if dynamic_shots else 0.0
        _finalize_dynamic_wave_diagnostics(bucket)
        bucket["excludedGlitch"] = float(bucket["accuracy"]) > threshold
    return dict(rounds)


def _read_bot_events(telemetry_dir: Path, bot: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not telemetry_dir.exists():
        return events
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("bot") == bot:
                    events.append(event)
    return events


def _bullet_id(fields: dict[str, Any]) -> str | None:
    bullet_id = fields.get("bullet_id")
    if bullet_id is None:
        return None
    return str(bullet_id)


def _record_dynamic_wave_visit(bucket: dict[str, int | float | bool], fields: dict[str, Any]) -> None:
    if fields.get("selected_gun") != "dynamic_cluster":
        return
    bucket["dynamicWaveVisits"] = int(bucket["dynamicWaveVisits"]) + 1
    actual_guess_factor = _float_or_none(fields.get("guess_factor"))
    selected_guess_factor = _float_or_none(fields.get("dynamic_cluster_selected_guess_factor"))
    if actual_guess_factor is not None and selected_guess_factor is not None:
        bucket["dynamicErrorVisits"] = int(bucket["dynamicErrorVisits"]) + 1
        error = actual_guess_factor - selected_guess_factor
        bucket["dynamicErrorSum"] = float(bucket["dynamicErrorSum"]) + error
        bucket["dynamicAbsErrorSum"] = float(bucket["dynamicAbsErrorSum"]) + abs(error)
    if fields.get("dynamic_cluster_ambiguous_peak") is True:
        bucket["dynamicAmbiguousVisits"] = int(bucket["dynamicAmbiguousVisits"]) + 1
    aim_confidence = _float_or_none(fields.get("dynamic_cluster_aim_confidence"))
    if aim_confidence is not None:
        bucket["dynamicAimConfidenceVisits"] = int(bucket["dynamicAimConfidenceVisits"]) + 1
        bucket["dynamicAimConfidenceSum"] = float(bucket["dynamicAimConfidenceSum"]) + aim_confidence
    peak_ratio = _float_or_none(fields.get("dynamic_cluster_peak_score_ratio"))
    if peak_ratio is not None:
        bucket["dynamicPeakRatioVisits"] = int(bucket["dynamicPeakRatioVisits"]) + 1
        bucket["dynamicPeakScoreRatioSum"] = float(bucket["dynamicPeakScoreRatioSum"]) + peak_ratio
    bandwidth = _float_or_none(fields.get("dynamic_cluster_effective_bandwidth"))
    if bandwidth is not None:
        bucket["dynamicBandwidthVisits"] = int(bucket["dynamicBandwidthVisits"]) + 1
        bucket["dynamicEffectiveBandwidthSum"] = float(bucket["dynamicEffectiveBandwidthSum"]) + bandwidth


def _finalize_dynamic_wave_diagnostics(bucket: dict[str, int | float | bool]) -> None:
    wave_visits = int(bucket["dynamicWaveVisits"])
    error_visits = int(bucket["dynamicErrorVisits"])
    confidence_visits = int(bucket["dynamicAimConfidenceVisits"])
    peak_ratio_visits = int(bucket["dynamicPeakRatioVisits"])
    bandwidth_visits = int(bucket["dynamicBandwidthVisits"])
    bucket["dynamicAvgError"] = float(bucket["dynamicErrorSum"]) / error_visits if error_visits else 0.0
    bucket["dynamicAvgAbsError"] = float(bucket["dynamicAbsErrorSum"]) / error_visits if error_visits else 0.0
    bucket["dynamicAmbiguousRate"] = int(bucket["dynamicAmbiguousVisits"]) / wave_visits if wave_visits else 0.0
    bucket["dynamicAvgAimConfidence"] = (
        float(bucket["dynamicAimConfidenceSum"]) / confidence_visits if confidence_visits else 0.0
    )
    bucket["dynamicAvgPeakScoreRatio"] = (
        float(bucket["dynamicPeakScoreRatioSum"]) / peak_ratio_visits if peak_ratio_visits else 0.0
    )
    bucket["dynamicAvgEffectiveBandwidth"] = (
        float(bucket["dynamicEffectiveBandwidthSum"]) / bandwidth_visits if bandwidth_visits else 0.0
    )


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _round_summary(
    round_number: int,
    score: dict[str, int],
    accuracy: dict[str, int | float | bool],
    threshold: float,
) -> RoundSummary:
    shots = int(accuracy.get("shots", 0))
    hits = int(accuracy.get("hits", 0))
    dynamic_shots = int(accuracy.get("dynamicShots", 0))
    dynamic_hits = int(accuracy.get("dynamicHits", 0))
    hit_accuracy = hits / shots if shots else 0.0
    dynamic_accuracy = dynamic_hits / dynamic_shots if dynamic_shots else 0.0
    dynamic_wave_visits = int(accuracy.get("dynamicWaveVisits", 0))
    dynamic_error_visits = int(accuracy.get("dynamicErrorVisits", 0))
    dynamic_ambiguous_visits = int(accuracy.get("dynamicAmbiguousVisits", 0))
    dynamic_aim_confidence_visits = int(accuracy.get("dynamicAimConfidenceVisits", 0))
    dynamic_peak_ratio_visits = int(accuracy.get("dynamicPeakRatioVisits", 0))
    dynamic_bandwidth_visits = int(accuracy.get("dynamicBandwidthVisits", 0))
    return RoundSummary(
        round=round_number,
        score=score.get("score", 0),
        survival=score.get("survival", 0),
        bulletDamage=score.get("bulletDamage", 0),
        ramDamage=score.get("ramDamage", 0),
        firstPlaces=score.get("firstPlaces", 0),
        shots=shots,
        hits=hits,
        dynamicShots=dynamic_shots,
        dynamicHits=dynamic_hits,
        accuracy=hit_accuracy,
        dynamicAccuracy=dynamic_accuracy,
        dynamicWaveVisits=dynamic_wave_visits,
        dynamicErrorVisits=dynamic_error_visits,
        dynamicAvgError=float(accuracy.get("dynamicAvgError", 0.0)),
        dynamicAvgAbsError=float(accuracy.get("dynamicAvgAbsError", 0.0)),
        dynamicAmbiguousVisits=dynamic_ambiguous_visits,
        dynamicAmbiguousRate=float(accuracy.get("dynamicAmbiguousRate", 0.0)),
        dynamicAimConfidenceVisits=dynamic_aim_confidence_visits,
        dynamicAvgAimConfidence=float(accuracy.get("dynamicAvgAimConfidence", 0.0)),
        dynamicPeakRatioVisits=dynamic_peak_ratio_visits,
        dynamicAvgPeakScoreRatio=float(accuracy.get("dynamicAvgPeakScoreRatio", 0.0)),
        dynamicBandwidthVisits=dynamic_bandwidth_visits,
        dynamicAvgEffectiveBandwidth=float(accuracy.get("dynamicAvgEffectiveBandwidth", 0.0)),
        excludedGlitch=bool(accuracy.get("excludedGlitch", hit_accuracy > threshold)),
    )


def _aggregate_rounds(rounds: tuple[RoundSummary, ...], *, filtered: bool) -> AggregateSummary:
    selected = [round_summary for round_summary in rounds if not filtered or not round_summary.excludedGlitch]
    return _aggregate_round_values(selected, runs=1 if rounds else 0, excluded_rounds=_excluded_count(rounds) if filtered else 0)


def _aggregate_runs(aggregates: list[AggregateSummary]) -> dict[str, int | float]:
    shots = sum(aggregate.shots for aggregate in aggregates)
    hits = sum(aggregate.hits for aggregate in aggregates)
    dynamic_shots = sum(aggregate.dynamicShots for aggregate in aggregates)
    dynamic_hits = sum(aggregate.dynamicHits for aggregate in aggregates)
    dynamic_wave_visits = sum(aggregate.dynamicWaveVisits for aggregate in aggregates)
    dynamic_error_visits = sum(aggregate.dynamicErrorVisits for aggregate in aggregates)
    dynamic_ambiguous_visits = sum(aggregate.dynamicAmbiguousVisits for aggregate in aggregates)
    dynamic_aim_confidence_visits = sum(aggregate.dynamicAimConfidenceVisits for aggregate in aggregates)
    dynamic_peak_ratio_visits = sum(aggregate.dynamicPeakRatioVisits for aggregate in aggregates)
    dynamic_bandwidth_visits = sum(aggregate.dynamicBandwidthVisits for aggregate in aggregates)
    rounds = sum(aggregate.rounds for aggregate in aggregates)
    score = sum(aggregate.score for aggregate in aggregates)
    first_places = sum(aggregate.firstPlaces for aggregate in aggregates)
    survival = sum(aggregate.survival for aggregate in aggregates)
    bullet_damage = sum(aggregate.bulletDamage for aggregate in aggregates)
    ram_damage = sum(aggregate.ramDamage for aggregate in aggregates)
    return {
        "runs": len(aggregates),
        "rounds": rounds,
        "score": score,
        "scorePerRound": score / rounds if rounds else 0.0,
        "survival": survival,
        "survivalPerRound": survival / rounds if rounds else 0.0,
        "bulletDamage": bullet_damage,
        "bulletDamagePerRound": bullet_damage / rounds if rounds else 0.0,
        "ramDamage": ram_damage,
        "ramDamagePerRound": ram_damage / rounds if rounds else 0.0,
        "firstPlaces": first_places,
        "firstPlacesPerRound": first_places / rounds if rounds else 0.0,
        "shots": shots,
        "hits": hits,
        "accuracy": hits / shots if shots else 0.0,
        "dynamicShots": dynamic_shots,
        "dynamicHits": dynamic_hits,
        "dynamicAccuracy": dynamic_hits / dynamic_shots if dynamic_shots else 0.0,
        "dynamicWaveVisits": dynamic_wave_visits,
        "dynamicErrorVisits": dynamic_error_visits,
        "dynamicAvgError": _weighted_average(
            [(aggregate.dynamicAvgError, aggregate.dynamicErrorVisits) for aggregate in aggregates]
        ),
        "dynamicAvgAbsError": _weighted_average(
            [(aggregate.dynamicAvgAbsError, aggregate.dynamicErrorVisits) for aggregate in aggregates]
        ),
        "dynamicAmbiguousVisits": dynamic_ambiguous_visits,
        "dynamicAmbiguousRate": dynamic_ambiguous_visits / dynamic_wave_visits if dynamic_wave_visits else 0.0,
        "dynamicAimConfidenceVisits": dynamic_aim_confidence_visits,
        "dynamicAvgAimConfidence": _weighted_average(
            [(aggregate.dynamicAvgAimConfidence, aggregate.dynamicAimConfidenceVisits) for aggregate in aggregates]
        ),
        "dynamicPeakRatioVisits": dynamic_peak_ratio_visits,
        "dynamicAvgPeakScoreRatio": _weighted_average(
            [(aggregate.dynamicAvgPeakScoreRatio, aggregate.dynamicPeakRatioVisits) for aggregate in aggregates]
        ),
        "dynamicBandwidthVisits": dynamic_bandwidth_visits,
        "dynamicAvgEffectiveBandwidth": _weighted_average(
            [(aggregate.dynamicAvgEffectiveBandwidth, aggregate.dynamicBandwidthVisits) for aggregate in aggregates]
        ),
        "excludedRounds": sum(aggregate.excludedRounds for aggregate in aggregates),
        "unpairedRounds": sum(aggregate.unpairedRounds for aggregate in aggregates),
    }


def _aggregate_round_values(
    rounds: list[RoundSummary],
    *,
    runs: int,
    excluded_rounds: int,
) -> AggregateSummary:
    shots = sum(round_summary.shots for round_summary in rounds)
    hits = sum(round_summary.hits for round_summary in rounds)
    dynamic_shots = sum(round_summary.dynamicShots for round_summary in rounds)
    dynamic_hits = sum(round_summary.dynamicHits for round_summary in rounds)
    dynamic_wave_visits = sum(round_summary.dynamicWaveVisits for round_summary in rounds)
    dynamic_error_visits = sum(round_summary.dynamicErrorVisits for round_summary in rounds)
    dynamic_ambiguous_visits = sum(round_summary.dynamicAmbiguousVisits for round_summary in rounds)
    dynamic_aim_confidence_visits = sum(round_summary.dynamicAimConfidenceVisits for round_summary in rounds)
    dynamic_peak_ratio_visits = sum(round_summary.dynamicPeakRatioVisits for round_summary in rounds)
    dynamic_bandwidth_visits = sum(round_summary.dynamicBandwidthVisits for round_summary in rounds)
    return AggregateSummary(
        runs=runs,
        rounds=len(rounds),
        score=sum(round_summary.score for round_summary in rounds),
        survival=sum(round_summary.survival for round_summary in rounds),
        bulletDamage=sum(round_summary.bulletDamage for round_summary in rounds),
        ramDamage=sum(round_summary.ramDamage for round_summary in rounds),
        firstPlaces=sum(round_summary.firstPlaces for round_summary in rounds),
        shots=shots,
        hits=hits,
        accuracy=hits / shots if shots else 0.0,
        dynamicShots=dynamic_shots,
        dynamicHits=dynamic_hits,
        dynamicAccuracy=dynamic_hits / dynamic_shots if dynamic_shots else 0.0,
        dynamicWaveVisits=dynamic_wave_visits,
        dynamicErrorVisits=dynamic_error_visits,
        dynamicAvgError=_weighted_average(
            [(round_summary.dynamicAvgError, round_summary.dynamicErrorVisits) for round_summary in rounds]
        ),
        dynamicAvgAbsError=_weighted_average(
            [(round_summary.dynamicAvgAbsError, round_summary.dynamicErrorVisits) for round_summary in rounds]
        ),
        dynamicAmbiguousVisits=dynamic_ambiguous_visits,
        dynamicAmbiguousRate=dynamic_ambiguous_visits / dynamic_wave_visits if dynamic_wave_visits else 0.0,
        dynamicAimConfidenceVisits=dynamic_aim_confidence_visits,
        dynamicAvgAimConfidence=_weighted_average(
            [
                (round_summary.dynamicAvgAimConfidence, round_summary.dynamicAimConfidenceVisits)
                for round_summary in rounds
            ]
        ),
        dynamicPeakRatioVisits=dynamic_peak_ratio_visits,
        dynamicAvgPeakScoreRatio=_weighted_average(
            [(round_summary.dynamicAvgPeakScoreRatio, round_summary.dynamicPeakRatioVisits) for round_summary in rounds]
        ),
        dynamicBandwidthVisits=dynamic_bandwidth_visits,
        dynamicAvgEffectiveBandwidth=_weighted_average(
            [(round_summary.dynamicAvgEffectiveBandwidth, round_summary.dynamicBandwidthVisits) for round_summary in rounds]
        ),
        excludedRounds=excluded_rounds,
    )


def _weighted_average(values: list[tuple[float, int]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def _with_delta(summary_by_side: dict[str, dict[str, int | float]]) -> dict[str, Any]:
    result: dict[str, Any] = dict(summary_by_side)
    if "baseline" in summary_by_side and "candidate" in summary_by_side:
        result["delta"] = {
            key: summary_by_side["candidate"][key] - summary_by_side["baseline"][key]
            for key in [
                "rounds",
                "score",
                "scorePerRound",
                "survival",
                "survivalPerRound",
                "bulletDamage",
                "bulletDamagePerRound",
                "ramDamage",
                "ramDamagePerRound",
                "firstPlaces",
                "firstPlacesPerRound",
                "shots",
                "hits",
                "dynamicShots",
                "dynamicHits",
                "dynamicWaveVisits",
                "dynamicErrorVisits",
                "dynamicAmbiguousVisits",
                "dynamicAimConfidenceVisits",
                "dynamicPeakRatioVisits",
                "dynamicBandwidthVisits",
                "excludedRounds",
                "unpairedRounds",
            ]
            if key in summary_by_side["candidate"] and key in summary_by_side["baseline"]
        }
    return result


def _paired_filtered_summary(runs: list[RunSummary]) -> dict[str, Any]:
    pairs: dict[str, dict[str, RunSummary]] = defaultdict(dict)
    warnings: list[str] = []
    for run in runs:
        if run.side in {"baseline", "candidate"}:
            key = _paired_run_key(run)
            if run.side in pairs[key]:
                warnings.append(f"duplicate paired {run.side} run for key {key}: {run.runDir}")
            pairs[key][run.side] = run

    paired_baseline: list[AggregateSummary] = []
    paired_candidate: list[AggregateSummary] = []
    pair_details: list[dict[str, Any]] = []
    for key in sorted(pairs):
        pair = pairs[key]
        baseline = pair.get("baseline")
        candidate = pair.get("candidate")
        if baseline is None or candidate is None:
            continue
        valid_rounds = _paired_valid_rounds(baseline, candidate)
        baseline_rounds = _rounds_by_number(baseline)
        candidate_rounds = _rounds_by_number(candidate)
        baseline_unpaired_rounds = _unpaired_round_numbers(baseline, candidate)
        candidate_unpaired_rounds = _unpaired_round_numbers(candidate, baseline)
        baseline_excluded_rounds = _shared_excluded_round_numbers(baseline, candidate)
        candidate_excluded_rounds = _shared_excluded_round_numbers(candidate, baseline)
        paired_baseline.append(
            _aggregate_round_values(
                [baseline_rounds[round_number] for round_number in valid_rounds],
                runs=1,
                excluded_rounds=len(baseline_excluded_rounds),
            )
        )
        paired_candidate.append(
            _aggregate_round_values(
                [candidate_rounds[round_number] for round_number in valid_rounds],
                runs=1,
                excluded_rounds=len(candidate_excluded_rounds),
            )
        )
        baseline_unpaired_count = len(baseline_unpaired_rounds)
        candidate_unpaired_count = len(candidate_unpaired_rounds)
        paired_baseline[-1] = _aggregate_with_unpaired(paired_baseline[-1], baseline_unpaired_count)
        paired_candidate[-1] = _aggregate_with_unpaired(paired_candidate[-1], candidate_unpaired_count)
        pair_details.append(
            {
                "key": key,
                "validRounds": valid_rounds,
                "baselineExcludedRounds": baseline_excluded_rounds,
                "candidateExcludedRounds": candidate_excluded_rounds,
                "baselineUnpairedRounds": baseline_unpaired_rounds,
                "candidateUnpairedRounds": candidate_unpaired_rounds,
                "rounds": [
                    _paired_round_comparison(
                        round_number,
                        baseline_rounds[round_number],
                        candidate_rounds[round_number],
                    )
                    for round_number in valid_rounds
                ],
            }
        )

    summary = _with_delta(
        {
            "baseline": _aggregate_runs(paired_baseline),
            "candidate": _aggregate_runs(paired_candidate),
        }
    )
    has_valid_rounds = any(pair["validRounds"] for pair in pair_details)
    summary["available"] = has_valid_rounds
    summary["pairCount"] = len(pair_details)
    summary["pairs"] = pair_details
    if runs and not pair_details:
        summary.pop("delta", None)
        warnings.append("no baseline/candidate pairs discovered for pairedFiltered comparison")
    elif pair_details and not has_valid_rounds:
        summary.pop("delta", None)
        warnings.append("no valid pairedFiltered rounds discovered after glitch and round-pair filtering")
    summary["warnings"] = warnings
    return summary


def _paired_run_key(run: RunSummary) -> str:
    parts = list(Path(run.runDir).parts)
    for reverse_index, part in enumerate(reversed(parts)):
        if part in {"baseline", "candidate"}:
            index = len(parts) - reverse_index - 1
            parts[index] = "<side>"
            return "/".join(parts)
    return run.runDir


def _paired_valid_rounds(baseline: RunSummary, candidate: RunSummary) -> list[int]:
    baseline_rounds = _rounds_by_number(baseline)
    candidate_rounds = _rounds_by_number(candidate)
    return [
        round_number
        for round_number in sorted(set(baseline_rounds).intersection(candidate_rounds))
        if not baseline_rounds[round_number].excludedGlitch
        and not candidate_rounds[round_number].excludedGlitch
    ]


def _rounds_by_number(run: RunSummary) -> dict[int, RoundSummary]:
    return {round_summary.round: round_summary for round_summary in run.rounds}


def _excluded_round_numbers(run: RunSummary) -> list[int]:
    return [round_summary.round for round_summary in run.rounds if round_summary.excludedGlitch]


def _shared_excluded_round_numbers(left: RunSummary, right: RunSummary) -> list[int]:
    right_rounds = set(_rounds_by_number(right))
    return [
        round_summary.round
        for round_summary in left.rounds
        if round_summary.round in right_rounds and round_summary.excludedGlitch
    ]


def _unpaired_round_numbers(left: RunSummary, right: RunSummary) -> list[int]:
    right_rounds = set(_rounds_by_number(right))
    return [round_summary.round for round_summary in left.rounds if round_summary.round not in right_rounds]


def _aggregate_with_unpaired(aggregate: AggregateSummary, unpaired_rounds: int) -> AggregateSummary:
    data = asdict(aggregate)
    data["unpairedRounds"] = unpaired_rounds
    return AggregateSummary(**data)


def _paired_round_comparison(
    round_number: int,
    baseline: RoundSummary,
    candidate: RoundSummary,
) -> dict[str, int | float]:
    return {
        "round": round_number,
        "baselineScore": baseline.score,
        "candidateScore": candidate.score,
        "scoreDelta": candidate.score - baseline.score,
        "baselineFirstPlaces": baseline.firstPlaces,
        "candidateFirstPlaces": candidate.firstPlaces,
        "firstPlacesDelta": candidate.firstPlaces - baseline.firstPlaces,
        "baselineAccuracy": baseline.accuracy,
        "candidateAccuracy": candidate.accuracy,
        "accuracyDelta": candidate.accuracy - baseline.accuracy,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"runs: {summary['runCount']} threshold: {summary['threshold']}")
    for warning in summary["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    for label in ("raw", "filtered", "pairedFiltered"):
        print(label)
        bucket = summary[label]
        if label == "pairedFiltered":
            print(f"  pair_count={bucket.get('pairCount', 0)} available={bucket.get('available', False)}")
        for side in sorted(
            key for key in bucket if key not in {"delta", "pairs", "pairCount", "warnings", "available"}
        ):
            values = bucket[side]
            print(
                "  {side}: runs={runs} rounds={rounds} score={score} score/round={score_per_round:.2f} "
                "firsts={firsts} firsts/round={firsts_per_round:.3f} "
                "accuracy={accuracy:.3f} dynamic={dynamic_hits}/{dynamic_shots} "
                "dynamic_accuracy={dynamic_accuracy:.3f} dyn_error={dynamic_error:.3f}/{dynamic_abs_error:.3f} "
                "ambiguous={ambiguous:.3f} excluded={excluded} unpaired={unpaired}".format(
                    side=side,
                    runs=values["runs"],
                    rounds=values["rounds"],
                    score=values["score"],
                    score_per_round=values["scorePerRound"],
                    firsts=values["firstPlaces"],
                    firsts_per_round=values["firstPlacesPerRound"],
                    accuracy=values["accuracy"],
                    dynamic_hits=values["dynamicHits"],
                    dynamic_shots=values["dynamicShots"],
                    dynamic_accuracy=values["dynamicAccuracy"],
                    dynamic_error=values["dynamicAvgError"],
                    dynamic_abs_error=values["dynamicAvgAbsError"],
                    ambiguous=values["dynamicAmbiguousRate"],
                    excluded=values["excludedRounds"],
                    unpaired=values.get("unpairedRounds", 0),
                )
            )
        if "delta" in bucket:
            delta = bucket["delta"]
            print(
                "  delta: score={score} score/round={score_per_round:.2f} "
                "firsts={firsts} firsts/round={firsts_per_round:.3f} "
                "hits={hits} dynamic_hits={dynamic_hits} excluded={excluded} unpaired={unpaired}".format(
                    score=delta["score"],
                    score_per_round=delta["scorePerRound"],
                    firsts=delta["firstPlaces"],
                    firsts_per_round=delta["firstPlacesPerRound"],
                    hits=delta["hits"],
                    dynamic_hits=delta["dynamicHits"],
                    excluded=delta["excludedRounds"],
                    unpaired=delta.get("unpairedRounds", 0),
                )
            )
        if label == "pairedFiltered":
            for pair in bucket.get("pairs", []):
                print(
                    "  pair {key}: valid_rounds={valid} "
                    "baseline_excluded={baseline} candidate_excluded={candidate} "
                    "baseline_unpaired={baseline_unpaired} candidate_unpaired={candidate_unpaired}".format(
                        key=pair["key"],
                        valid=pair["validRounds"],
                        baseline=pair["baselineExcludedRounds"],
                        candidate=pair["candidateExcludedRounds"],
                        baseline_unpaired=pair["baselineUnpairedRounds"],
                        candidate_unpaired=pair["candidateUnpairedRounds"],
                    )
                )
                for round_row in pair.get("rounds", []):
                    print(
                        "    round {round}: score {baseline_score}->{candidate_score} delta={score_delta} "
                        "firsts {baseline_firsts}->{candidate_firsts} delta={first_delta} "
                        "accuracy {baseline_accuracy:.3f}->{candidate_accuracy:.3f} delta={accuracy_delta:.3f}".format(
                            round=round_row["round"],
                            baseline_score=round_row["baselineScore"],
                            candidate_score=round_row["candidateScore"],
                            score_delta=round_row["scoreDelta"],
                            baseline_firsts=round_row["baselineFirstPlaces"],
                            candidate_firsts=round_row["candidateFirstPlaces"],
                            first_delta=round_row["firstPlacesDelta"],
                            baseline_accuracy=round_row["baselineAccuracy"],
                            candidate_accuracy=round_row["candidateAccuracy"],
                            accuracy_delta=round_row["accuracyDelta"],
                        )
                    )


def _accuracy_bucket() -> dict[str, int | float | bool]:
    return {
        "shots": 0,
        "hits": 0,
        "dynamicShots": 0,
        "dynamicHits": 0,
        "dynamicWaveVisits": 0,
        "dynamicErrorVisits": 0,
        "dynamicErrorSum": 0.0,
        "dynamicAvgError": 0.0,
        "dynamicAbsErrorSum": 0.0,
        "dynamicAmbiguousVisits": 0,
        "dynamicAmbiguousRate": 0.0,
        "dynamicAimConfidenceVisits": 0,
        "dynamicAimConfidenceSum": 0.0,
        "dynamicAvgAimConfidence": 0.0,
        "dynamicPeakRatioVisits": 0,
        "dynamicPeakScoreRatioSum": 0.0,
        "dynamicAvgPeakScoreRatio": 0.0,
        "dynamicBandwidthVisits": 0,
        "dynamicEffectiveBandwidthSum": 0.0,
        "dynamicAvgEffectiveBandwidth": 0.0,
        "accuracy": 0.0,
        "dynamicAccuracy": 0.0,
        "excludedGlitch": False,
    }


def _excluded_count(rounds: tuple[RoundSummary, ...]) -> int:
    return sum(1 for round_summary in rounds if round_summary.excludedGlitch)


def _normalize_name(value: str) -> str:
    return value.replace(" ", "_")


def _accuracy_threshold(value: str) -> float:
    threshold = float(value)
    if threshold < 0.0 or threshold > 1.0:
        raise argparse.ArgumentTypeError("threshold must be between 0.0 and 1.0")
    return threshold


def _run_warnings(
    run_dir: Path,
    scores: dict[int, dict[str, int]],
    accuracy: dict[int, dict[str, int | float | bool]],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not (run_dir / "runner.log").exists():
        warnings.append("missing runner.log")
    elif not scores:
        warnings.append("no matching runner score rows")
    telemetry_dir = run_dir / "telemetry"
    if not telemetry_dir.exists():
        warnings.append("missing telemetry directory")
    elif not list(telemetry_dir.glob("*.jsonl")):
        warnings.append("missing telemetry JSONL files")
    elif not accuracy:
        warnings.append("no matching telemetry events")
    elif sum(int(bucket.get("shots", 0)) for bucket in accuracy.values()) == 0:
        warnings.append("no bullet.fired telemetry")
    if scores and accuracy:
        score_rounds = set(scores)
        accuracy_rounds = set(accuracy)
        if score_rounds != accuracy_rounds:
            warnings.append(
                "score/telemetry round mismatch "
                f"scores={_round_range(score_rounds)} telemetry={_round_range(accuracy_rounds)}"
            )
        rounds_without_shots = {
            round_number
            for round_number in score_rounds & accuracy_rounds
            if int(accuracy[round_number].get("shots", 0)) == 0
        }
        if rounds_without_shots:
            warnings.append(f"scored rounds without shot telemetry: {_round_range(rounds_without_shots)}")
    if scores and len(scores) < 20:
        warnings.append(f"short run has {len(scores)} scored rounds; BasicGFSurfer validation expects 20+")
    return tuple(warnings)


def _round_range(rounds: set[int]) -> str:
    if not rounds:
        return "none"
    ordered = sorted(rounds)
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]}..{ordered[-1]}"
    return ",".join(str(round_number) for round_number in ordered)


def _side_for_run_dir(run_dir: Path) -> str:
    for part in reversed(run_dir.parts):
        if part in {"baseline", "candidate"}:
            return part
    return "runs"


def _looks_like_run_dir(path: Path) -> bool:
    return path.is_dir() and _has_run_artifacts(path)


def _has_run_artifacts(path: Path) -> bool:
    return (
        (path / "runner.log").exists()
        or (path / "results.json").exists()
        or (path / "telemetry").is_dir()
    )


if __name__ == "__main__":
    raise SystemExit(main())

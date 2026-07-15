#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable


_FIXED_PRIOR_HIT_RATE = 1.0 / 6.0


class TelemetryJsonlError(ValueError):
    pass


def main() -> int:
    args = _parse_args()
    try:
        events = _read_events(Path(args.telemetry_dir), args.bot)
    except TelemetryJsonlError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    summary = summarize_events(events)
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _print_summary(summary)
    return 0 if summary["acceptedShots"] else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize shadow fire-utility reliability from telemetry."
    )
    parser.add_argument("telemetry_dir", help="Directory containing telemetry JSONL files")
    parser.add_argument("--bot", default="adaptive-prime", help="Telemetry bot name")
    parser.add_argument("--json-output", help="Optional JSON summary path")
    return parser.parse_args()


def _read_events(telemetry_dir: Path, bot: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    kind = "truncated final JSON" if not line.endswith("\n") else "invalid JSON"
                    raise TelemetryJsonlError(
                        f"{path}:{line_number}: {kind}: {error.msg}"
                    ) from error
                if event.get("bot") == bot:
                    events.append(event)
    return events


def summarize_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    shots: list[dict[str, Any]] = []
    round_shots: dict[str, dict[str, Any]] = {}
    pending_hits: set[str] = set()
    opportunities = Counter()
    opportunity_reasons: dict[str, Counter[str]] = defaultdict(Counter)
    fallback_counts = Counter()
    fired_bullets = 0
    outcome_events = 0
    correction_events = 0
    invalid_corrections = 0
    duplicate_accepted = 0

    def flush_round() -> None:
        nonlocal round_shots, pending_hits
        shots.extend(round_shots.values())
        round_shots = {}
        pending_hits = set()

    for event in events:
        name = str(event.get("event") or "")
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if name == "round.reset":
            flush_round()
            continue
        if name == "bullet.fired":
            fired_bullets += 1
            continue
        if name == "fire.utility_opportunity":
            action = str(fields.get("action") or "unknown")
            reason = str(fields.get("reason") or "unknown")
            opportunities[action] += 1
            opportunity_reasons[action][reason] += 1
            continue
        if name == "fire.utility_accepted":
            bullet_id = _bullet_id(fields)
            if bullet_id is None:
                continue
            if bullet_id in round_shots:
                duplicate_accepted += 1
                continue
            q = _float_or_none(fields.get("q"))
            if q is None:
                continue
            shot = {
                "bulletId": bullet_id,
                "q": max(0.0, min(1.0, q)),
                "hit": bullet_id in pending_hits,
                "outcome": "hit_bot" if bullet_id in pending_hits else "unresolved",
                "damage": 0.0,
                "aimMode": str(fields.get("aim_mode") or "unknown"),
                "rangeBand": str(fields.get("range_band") or "unknown"),
                "powerBand": str(fields.get("power_band") or "unknown"),
                "qualityBand": str(fields.get("quality_band") or "unknown"),
                "fallbackLevel": str(fields.get("fallback_level") or "unknown"),
                "power": _float_or_none(fields.get("power")) or 0.0,
                "scoreUtility": _float_or_none(fields.get("score_utility")) or 0.0,
                "energySwingUtility": _float_or_none(fields.get("energy_swing_utility")) or 0.0,
                "calibrationSupport": _int_or_zero(fields.get("calibration_support")),
                "behaviorReason": str(fields.get("reason") or "unknown"),
                "resolvedByUtility": False,
                "utilityOutcome": None,
            }
            round_shots[bullet_id] = shot
            fallback_counts[shot["fallbackLevel"]] += 1
            continue
        if name == "bullet.hit_bot":
            bullet_id = _bullet_id(fields)
            if bullet_id is None:
                continue
            shot = round_shots.get(bullet_id)
            if shot is None:
                pending_hits.add(bullet_id)
            else:
                shot["hit"] = True
                shot["outcome"] = "hit_bot"
                shot["damage"] = _float_or_none(fields.get("damage")) or 0.0
            continue
        if name in {"fire.utility_outcome", "fire.utility_outcome_corrected"}:
            bullet_id = _bullet_id(fields)
            if bullet_id is None:
                continue
            outcome_events += 1
            if name.endswith("corrected"):
                correction_events += 1
            shot = round_shots.get(bullet_id)
            if shot is None:
                continue
            if name == "fire.utility_outcome_corrected" and not (
                shot["utilityOutcome"] == "round_end"
                and fields.get("previous_outcome") == "round_end"
                and fields.get("outcome") == "hit_bot"
                and fields.get("hit") is True
            ):
                invalid_corrections += 1
                continue
            shot["resolvedByUtility"] = True
            shot["outcome"] = str(fields.get("outcome") or "unknown")
            shot["utilityOutcome"] = shot["outcome"]
            shot["hit"] = bool(fields.get("hit")) or shot["hit"]
            if shot["hit"]:
                shot["outcome"] = "hit_bot"
            shot["damage"] = max(
                float(shot["damage"]),
                _float_or_none(fields.get("damage")) or 0.0,
            )

    flush_round()
    for resolved_shot in shots:
        if resolved_shot["outcome"] == "unresolved":
            resolved_shot["outcome"] = "eof_miss"

    overall = _reliability(shots)
    probability_bands = _grouped_reliability(shots, _probability_band)
    calibration_diagnostics = _calibration_diagnostics(shots, probability_bands)
    by_range = _grouped_reliability(shots, lambda entry: str(entry["rangeBand"]))
    by_power = _grouped_reliability(shots, lambda entry: str(entry["powerBand"]))
    by_mode = _grouped_reliability(shots, lambda entry: str(entry["aimMode"]))
    by_quality = _grouped_reliability(shots, lambda entry: str(entry["qualityBand"]))
    by_fallback = _grouped_reliability(shots, lambda entry: str(entry["fallbackLevel"]))
    chronological = _chronological_windows(shots)
    accepted = len(shots)
    resolved_by_utility = sum(bool(shot["resolvedByUtility"]) for shot in shots)
    warnings: list[str] = []
    if fired_bullets and accepted != fired_bullets:
        warnings.append(
            f"accepted fire-utility coverage is {accepted}/{fired_bullets} bullet.fired events"
        )
    if duplicate_accepted:
        warnings.append(f"duplicate accepted utility events: {duplicate_accepted}")
    if invalid_corrections:
        warnings.append(f"invalid utility corrections: {invalid_corrections}")
    if accepted and not probability_bands:
        warnings.append("no probability reliability bands were produced")

    return {
        "acceptedShots": accepted,
        "bulletFiredEvents": fired_bullets,
        "acceptedCoverage": accepted / fired_bullets if fired_bullets else 0.0,
        "utilityOutcomeEvents": outcome_events,
        "utilityCorrections": correction_events,
        "utilityResolutionCoverage": resolved_by_utility / accepted if accepted else 0.0,
        "opportunities": {
            "total": sum(opportunities.values()),
            "fire": opportunities["fire"],
            "hold": opportunities["hold"],
            "other": sum(value for key, value in opportunities.items() if key not in {"fire", "hold"}),
            "reasons": {
                action: dict(sorted(counts.items()))
                for action, counts in sorted(opportunity_reasons.items())
            },
        },
        "overall": overall,
        "calibrationDiagnostics": calibration_diagnostics,
        "probabilityBands": probability_bands,
        "byRangeBand": by_range,
        "byPowerBand": by_power,
        "byAimMode": by_mode,
        "byQualityBand": by_quality,
        "byFallbackLevel": by_fallback,
        "chronologicalWindows": chronological,
        "fallbackCounts": dict(sorted(fallback_counts.items())),
        "warnings": warnings,
    }


def _reliability(shots: list[dict[str, Any]]) -> dict[str, Any]:
    if not shots:
        return {
            "shots": 0,
            "hits": 0,
            "predictedHitRate": 0.0,
            "observedHitRate": 0.0,
            "calibrationGap": 0.0,
            "brierScore": 0.0,
            "meanPower": 0.0,
            "meanScoreUtility": 0.0,
            "meanEnergySwingUtility": 0.0,
        }
    count = len(shots)
    hits = sum(bool(shot["hit"]) for shot in shots)
    predicted = sum(float(shot["q"]) for shot in shots) / count
    observed = hits / count
    return {
        "shots": count,
        "hits": hits,
        "predictedHitRate": predicted,
        "observedHitRate": observed,
        "calibrationGap": observed - predicted,
        "brierScore": sum(
            (float(shot["q"]) - (1.0 if shot["hit"] else 0.0)) ** 2
            for shot in shots
        )
        / count,
        "meanPower": sum(float(shot["power"]) for shot in shots) / count,
        "meanScoreUtility": sum(float(shot["scoreUtility"]) for shot in shots) / count,
        "meanEnergySwingUtility": sum(
            float(shot["energySwingUtility"]) for shot in shots
        )
        / count,
    }


def _grouped_reliability(
    shots: list[dict[str, Any]],
    key: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for shot in shots:
        grouped[key(shot)].append(shot)
    return {name: _reliability(values) for name, values in sorted(grouped.items())}


def _calibration_diagnostics(
    shots: list[dict[str, Any]],
    probability_bands: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    count = len(shots)
    if not count:
        return {
            "supportedShots": 0,
            "supportedCoverage": 0.0,
            "fixedPriorHitRate": _FIXED_PRIOR_HIT_RATE,
            "fixedPriorBrierScore": 0.0,
            "brierSkillVsFixedPrior": None,
            "expectedCalibrationError": 0.0,
            "meanPredictedHitQ": None,
            "meanPredictedMissQ": None,
            "hitMissProbabilitySeparation": None,
        }

    model_brier = float(_reliability(shots)["brierScore"])
    fixed_prior_brier = sum(
        (_FIXED_PRIOR_HIT_RATE - (1.0 if shot["hit"] else 0.0)) ** 2
        for shot in shots
    ) / count
    supported = sum(int(shot["calibrationSupport"]) > 0 for shot in shots)
    hits = [float(shot["q"]) for shot in shots if shot["hit"]]
    misses = [float(shot["q"]) for shot in shots if not shot["hit"]]
    mean_hit_q = sum(hits) / len(hits) if hits else None
    mean_miss_q = sum(misses) / len(misses) if misses else None
    return {
        "supportedShots": supported,
        "supportedCoverage": supported / count,
        "fixedPriorHitRate": _FIXED_PRIOR_HIT_RATE,
        "fixedPriorBrierScore": fixed_prior_brier,
        "brierSkillVsFixedPrior": (
            1.0 - model_brier / fixed_prior_brier
            if fixed_prior_brier > 0.0
            else None
        ),
        "expectedCalibrationError": sum(
            int(values["shots"]) / count * abs(float(values["calibrationGap"]))
            for values in probability_bands.values()
        ),
        "meanPredictedHitQ": mean_hit_q,
        "meanPredictedMissQ": mean_miss_q,
        "hitMissProbabilitySeparation": (
            mean_hit_q - mean_miss_q
            if mean_hit_q is not None and mean_miss_q is not None
            else None
        ),
    }


def _probability_band(shot: dict[str, Any]) -> str:
    index = min(9, max(0, int(float(shot["q"]) * 10.0)))
    return f"{index / 10:.1f}-{(index + 1) / 10:.1f}"


def _chronological_windows(shots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not shots:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    count = len(shots)
    for index, shot in enumerate(shots):
        window = min(3, index * 4 // count) + 1
        grouped[f"q{window}"].append(shot)
    return {name: _reliability(values) for name, values in sorted(grouped.items())}


def _bullet_id(fields: dict[str, Any]) -> str | None:
    value = fields.get("bullet_id")
    return str(value) if value is not None else None


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: object) -> int:
    numeric = _float_or_none(value)
    return max(0, int(numeric)) if numeric is not None else 0


def _print_summary(summary: dict[str, Any]) -> None:
    overall = summary["overall"]
    print(
        "Fire utility: "
        f"accepted={summary['acceptedShots']} "
        f"coverage={summary['acceptedCoverage']:.1%} "
        f"predicted={overall['predictedHitRate']:.1%} "
        f"observed={overall['observedHitRate']:.1%} "
        f"gap={overall['calibrationGap']:+.1%} "
        f"brier={overall['brierScore']:.4f}"
    )
    diagnostics = summary["calibrationDiagnostics"]
    brier_skill = diagnostics["brierSkillVsFixedPrior"]
    brier_skill_label = f"{brier_skill:+.4f}" if brier_skill is not None else "n/a"
    separation = diagnostics["hitMissProbabilitySeparation"]
    separation_label = f"{separation:+.4f}" if separation is not None else "n/a"
    print(
        "Calibration: "
        f"supported={diagnostics['supportedShots']}/{summary['acceptedShots']} "
        f"ece={diagnostics['expectedCalibrationError']:.4f} "
        f"prior_brier={diagnostics['fixedPriorBrierScore']:.4f} "
        f"brier_skill={brier_skill_label} "
        f"hit_miss_separation={separation_label}"
    )
    opportunities = summary["opportunities"]
    print(
        "Opportunities: "
        f"total={opportunities['total']} fire={opportunities['fire']} hold={opportunities['hold']}"
    )
    for label, groups in (
        ("Probability", summary["probabilityBands"]),
        ("Range", summary["byRangeBand"]),
        ("Power", summary["byPowerBand"]),
        ("Fallback", summary["byFallbackLevel"]),
    ):
        print(f"{label} bands:")
        for name, values in groups.items():
            print(
                f"  {name}: shots={values['shots']} predicted={values['predictedHitRate']:.1%} "
                f"observed={values['observedHitRate']:.1%} gap={values['calibrationGap']:+.1%}"
            )
    for warning in summary["warnings"]:
        print(f"warning: {warning}")


if __name__ == "__main__":
    raise SystemExit(main())

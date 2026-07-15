#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"
for import_root in (ROOT, BOTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from bot_core.combat.utility import (  # noqa: E402
    FireUtilityCalibrator,
    FireUtilityConfig,
    FireUtilityOpportunity,
    build_fire_utility_context,
)
from tools.fire_utility_summary import summarize_events  # noqa: E402


class TelemetryJsonlError(ValueError):
    pass


def replay_events(
    events: Iterable[dict[str, Any]],
    bot: str = "adaptive-prime",
) -> dict[str, Any]:
    """Replay the production calibrator causally and summarize its predictions."""

    summary, _ = _replay_events(events, bot)
    return summary


def replay_telemetry_dirs(
    telemetry_dirs: Iterable[Path],
    bot: str = "adaptive-prime",
) -> dict[str, Any]:
    """Replay each telemetry run independently and aggregate the scored shots."""

    config = FireUtilityConfig()
    runs: list[dict[str, Any]] = []
    aggregate_events: list[dict[str, Any]] = []
    for telemetry_dir in telemetry_dirs:
        path = Path(telemetry_dir)
        summary, replayed = _replay_events(_read_events(path), bot)
        runs.append({"telemetryDir": str(path), "summary": summary})
        if aggregate_events:
            aggregate_events.append(_synthetic_event(bot, "round.reset", 0, {}))
        aggregate_events.extend(replayed)

    return {
        "bot": bot,
        "config": {
            "priorHits": config.prior_hits,
            "priorMisses": config.prior_misses,
            "dynamicHighQuality": config.dynamic_high_quality,
            "dynamicHighQualityOddsMultiplier": (
                config.dynamic_high_quality_odds_multiplier
            ),
        },
        "runs": runs,
        "aggregate": summarize_events(aggregate_events),
    }


def _replay_events(
    events: Iterable[dict[str, Any]],
    bot: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    calibrator = FireUtilityCalibrator()
    pending: FireUtilityOpportunity | None = None
    replayed: list[dict[str, Any]] = []
    last_turn = 0

    for event in events:
        if event.get("bot") != bot:
            continue
        name = str(event.get("event") or "")
        turn = _int_or_zero(event.get("turn"))
        last_turn = turn
        fields = event.get("fields")
        fields = fields if isinstance(fields, dict) else {}

        if name == "battle.reset":
            _append_outcomes(replayed, bot, calibrator.close_round(turn))
            calibrator.clear_battle_state()
            pending = None
            replayed.append(_synthetic_event(bot, "round.reset", turn, {}))
            continue
        if name == "round.reset":
            _append_outcomes(replayed, bot, calibrator.close_round(turn))
            calibrator.clear_round_state()
            pending = None
            replayed.append(_copy_event(event))
            continue
        if name == "fire.utility_opportunity":
            replayed.append(_copy_event(event))
            context = _context_from_fields(fields, calibrator.config)
            snapshots = calibrator.snapshot_power_bands(context)
            power = _float_or(fields.get("power"), 0.1)
            estimate = calibrator.estimate(
                context,
                power,
                cooling_rate=_float_or(fields.get("cooling_rate"), 0.1),
                calibration=next(
                    snapshot
                    for snapshot in snapshots
                    if snapshot.power_band == context.power_band
                ),
            )
            opportunity = FireUtilityOpportunity(
                target_id=_int_or_none(fields.get("target")),
                turn=turn,
                action=str(fields.get("action") or "hold"),
                reason=str(fields.get("reason") or "unknown"),
                estimate=estimate,
                power_band_calibration=snapshots,
            )
            if opportunity.action == "fire":
                pending = opportunity
            continue
        if name == "bullet.fired":
            replayed.append(_copy_event(event))
            continue
        if name == "fire.utility_accepted":
            target_id = _int_or_none(fields.get("target"))
            accepted_context = _context_from_fields(fields, calibrator.config)
            staged = pending
            pending = None
            pending_matches = (
                staged is not None
                and (staged.target_id == target_id or target_id is None)
                and staged.estimate.context.gun_mode == accepted_context.gun_mode
            )
            if pending_matches:
                assert staged is not None
                context = staged.estimate.context
                estimate = staged.estimate
                reason = staged.reason
                snapshots = staged.power_band_calibration
            else:
                context = accepted_context
                estimate = None
                reason = "accepted_unstaged"
                snapshots = ()
            shot = calibrator.record_accepted_shot(
                turn,
                fields.get("bullet_id"),
                target_id,
                context,
                _float_or(fields.get("power"), 0.1),
                cooling_rate=_float_or(fields.get("cooling_rate"), 0.1),
                behavior_reason=reason,
                estimate=estimate,
                calibration_snapshots=snapshots,
            )
            if shot is not None:
                replayed.append(_accepted_event(bot, turn, fields, shot))
            continue
        if name == "bullet.hit_bot":
            replayed.append(_copy_event(event))
            outcome = calibrator.resolve_shot(
                turn,
                fields.get("bullet_id"),
                "hit_bot",
                damage=_float_or(fields.get("damage"), 0.0),
            )
            if outcome is not None:
                replayed.append(_outcome_event(bot, outcome))
            continue
        if name in {"fire.utility_outcome", "fire.utility_outcome_corrected"}:
            outcome = calibrator.resolve_shot(
                turn,
                fields.get("bullet_id"),
                str(fields.get("outcome") or "unknown"),
                damage=_float_or(fields.get("damage"), 0.0),
            )
            if outcome is not None:
                replayed.append(_outcome_event(bot, outcome))

    _append_outcomes(replayed, bot, calibrator.close_round(last_turn))
    return summarize_events(replayed), replayed


def _context_from_fields(
    fields: dict[str, Any],
    config: FireUtilityConfig,
):
    return build_fire_utility_context(
        str(fields.get("aim_mode") or "unknown"),
        _float_or(fields.get("distance"), 0.0),
        _float_or(fields.get("power"), 0.1),
        solution_quality=_float_or_none(fields.get("solution_quality")),
        model_support=_int_or_zero(fields.get("model_support")),
        config=config,
    )


def _accepted_event(bot: str, turn: int, original: dict[str, Any], shot: Any) -> dict[str, Any]:
    estimate = shot.estimate
    context = estimate.context
    fields = dict(original)
    fields.update(
        {
            "bullet_id": shot.bullet_id,
            "target": shot.target_id,
            "reason": shot.behavior_reason,
            "aim_mode": context.gun_mode,
            "distance": context.distance,
            "range_band": context.range_band,
            "power_band": context.power_band,
            "quality_band": context.quality_band,
            "solution_quality": context.solution_quality,
            "model_support": context.model_support,
            "power": estimate.power,
            "q": estimate.q,
            "calibration_support": estimate.calibration_support,
            "calibration_hits": estimate.calibration_hits,
            "fallback_level": estimate.fallback_level,
            "bullet_damage": estimate.bullet_damage,
            "hit_bonus": estimate.hit_bonus,
            "gun_heat": estimate.gun_heat,
            "cooling_rate": estimate.cooling_rate,
            "cooldown_turns": estimate.cooldown_turns,
            "score_utility": estimate.score_utility,
            "energy_swing_utility": estimate.energy_swing_utility,
        }
    )
    return _synthetic_event(bot, "fire.utility_accepted", turn, fields)


def _append_outcomes(
    replayed: list[dict[str, Any]],
    bot: str,
    outcomes: Iterable[Any],
) -> None:
    replayed.extend(_outcome_event(bot, outcome) for outcome in outcomes)


def _outcome_event(bot: str, outcome: Any) -> dict[str, Any]:
    estimate = outcome.estimate
    fields = {
        "bullet_id": outcome.bullet_id,
        "target": outcome.target_id,
        "reason": outcome.behavior_reason,
        "aim_mode": estimate.context.gun_mode,
        "q": estimate.q,
        "power": estimate.power,
        "outcome": outcome.outcome,
        "hit": outcome.hit,
        "damage": outcome.damage,
    }
    if outcome.previous_outcome is not None:
        fields["previous_outcome"] = outcome.previous_outcome
    name = (
        "fire.utility_outcome_corrected"
        if outcome.previous_outcome is not None
        else "fire.utility_outcome"
    )
    return _synthetic_event(bot, name, outcome.resolved_turn, fields)


def _copy_event(event: dict[str, Any]) -> dict[str, Any]:
    fields = event.get("fields")
    return {
        **event,
        "fields": dict(fields) if isinstance(fields, dict) else {},
    }


def _synthetic_event(
    bot: str,
    name: str,
    turn: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {"bot": bot, "event": name, "turn": turn, "fields": fields}


def _read_events(telemetry_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as error:
                    kind = "truncated final JSON" if not line.endswith("\n") else "invalid JSON"
                    raise TelemetryJsonlError(
                        f"{path}:{line_number}: {kind}: {error.msg}"
                    ) from error
    return events


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or(value: object, default: float) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else default


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: object) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Causally replay the current fire-utility calibrator against telemetry."
        )
    )
    parser.add_argument(
        "telemetry_dirs",
        nargs="+",
        help="One or more directories containing telemetry JSONL files",
    )
    parser.add_argument("--bot", default="adaptive-prime", help="Telemetry bot name")
    parser.add_argument("--json-output", help="Optional JSON report path")
    return parser.parse_args()


def _metric(value: object) -> str:
    return "n/a" if value is None else f"{float(value):+.5f}"


def _print_summary(result: dict[str, Any]) -> None:
    for run in result["runs"]:
        summary = run["summary"]
        diagnostics = summary["calibrationDiagnostics"]
        print(
            f"{run['telemetryDir']}: accepted={summary['acceptedShots']} "
            f"brier_skill={_metric(diagnostics['brierSkillVsFixedPrior'])} "
            f"separation={_metric(diagnostics['hitMissProbabilitySeparation'])}"
        )
    aggregate = result["aggregate"]
    diagnostics = aggregate["calibrationDiagnostics"]
    print(
        f"aggregate: accepted={aggregate['acceptedShots']} "
        f"brier_skill={_metric(diagnostics['brierSkillVsFixedPrior'])} "
        f"separation={_metric(diagnostics['hitMissProbabilitySeparation'])}"
    )


def main() -> int:
    args = _parse_args()
    try:
        result = replay_telemetry_dirs(
            (Path(path) for path in args.telemetry_dirs),
            args.bot,
        )
    except TelemetryJsonlError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _print_summary(result)
    return 0 if result["aggregate"]["acceptedShots"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

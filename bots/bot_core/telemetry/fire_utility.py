from bot_core.combat import (
    AcceptedFireUtilityShot,
    FireUtilityEstimate,
    FireUtilityOpportunity,
    FireUtilityOutcome,
)
from bot_core.telemetry.sink import TelemetrySink


class FireUtilityTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def record_opportunity(self, opportunity: FireUtilityOpportunity) -> None:
        self._sink.log(
            "fire.utility_opportunity",
            target=opportunity.target_id,
            action=opportunity.action,
            reason=opportunity.reason,
            **_estimate_fields(opportunity.estimate),
        )

    def record_accepted(self, shot: AcceptedFireUtilityShot) -> None:
        self._sink.log(
            "fire.utility_accepted",
            bullet_id=shot.bullet_id,
            target=shot.target_id,
            action="fire",
            reason=shot.behavior_reason,
            fired_turn=shot.fired_turn,
            **_estimate_fields(shot.estimate),
        )

    def record_outcome(self, outcome: FireUtilityOutcome) -> None:
        event = (
            "fire.utility_outcome_corrected"
            if outcome.previous_outcome is not None
            else "fire.utility_outcome"
        )
        fields: dict[str, object] = {
            "bullet_id": outcome.bullet_id,
            "target": outcome.target_id,
            "action": "fire",
            "reason": outcome.behavior_reason,
            "fired_turn": outcome.fired_turn,
            "resolved_turn": outcome.resolved_turn,
            "outcome": outcome.outcome,
            "hit": outcome.hit,
            "damage": round(outcome.damage, 6),
            **_estimate_fields(outcome.estimate),
        }
        if outcome.previous_outcome is not None:
            fields["previous_outcome"] = outcome.previous_outcome
        self._sink.log(event, **fields)


def _estimate_fields(estimate: FireUtilityEstimate) -> dict[str, object]:
    context = estimate.context
    return {
        "aim_mode": context.gun_mode,
        "distance": round(context.distance, 6),
        "range_band": context.range_band,
        "power_band": context.power_band,
        "quality_band": context.quality_band,
        "solution_quality": round(context.solution_quality, 6)
        if context.solution_quality is not None
        else None,
        "model_support": context.model_support,
        "q": round(estimate.q, 6),
        "calibration_support": estimate.calibration_support,
        "calibration_hits": estimate.calibration_hits,
        "fallback_level": estimate.fallback_level,
        "power": round(estimate.power, 6),
        "bullet_damage": round(estimate.bullet_damage, 6),
        "hit_bonus": round(estimate.hit_bonus, 6),
        "gun_heat": round(estimate.gun_heat, 6),
        "cooling_rate": round(estimate.cooling_rate, 6),
        "cooldown_turns": estimate.cooldown_turns,
        "score_utility": round(estimate.score_utility, 6),
        "energy_swing_utility": round(estimate.energy_swing_utility, 6),
    }

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace

from bot_core.geometry.numeric import clamp
from bot_core.physics import (
    bullet_damage_for_power,
    bullet_hit_bonus_for_power,
    gun_heat_for_power,
)


@dataclass(frozen=True)
class FireUtilityConfig:
    """Low-dimensional calibration and fallback policy for shadow fire utility."""

    prior_hits: float = 1.0
    prior_misses: float = 5.0
    near_distance: float = 300.0
    far_distance: float = 550.0
    low_power: float = 0.75
    high_power: float = 1.5
    cold_model_support: int = 8
    mature_model_support: int = 36
    dynamic_high_quality: float = 0.10
    dynamic_high_quality_odds_multiplier: float = 1.75


@dataclass(frozen=True)
class FireUtilityContext:
    gun_mode: str
    distance: float
    range_band: str
    power_band: str
    quality_band: str
    solution_quality: float | None
    model_support: int


@dataclass(frozen=True)
class FireUtilityEstimate:
    context: FireUtilityContext
    power: float
    q: float
    calibration_support: int
    calibration_hits: int
    fallback_level: str
    bullet_damage: float
    hit_bonus: float
    gun_heat: float
    cooling_rate: float
    cooldown_turns: int
    score_utility: float
    energy_swing_utility: float


@dataclass(frozen=True)
class FireUtilityCalibrationSnapshot:
    power_band: str
    q: float
    calibration_support: int
    calibration_hits: int
    fallback_level: str


@dataclass(frozen=True)
class FireUtilityOpportunity:
    target_id: int | None
    turn: int
    action: str
    reason: str
    estimate: FireUtilityEstimate
    power_band_calibration: tuple[FireUtilityCalibrationSnapshot, ...] = ()


@dataclass(frozen=True)
class AcceptedFireUtilityShot:
    bullet_id: str
    target_id: int | None
    fired_turn: int
    behavior_reason: str
    estimate: FireUtilityEstimate


@dataclass(frozen=True)
class FireUtilityOutcome:
    bullet_id: str
    target_id: int | None
    fired_turn: int
    resolved_turn: int
    behavior_reason: str
    estimate: FireUtilityEstimate
    outcome: str
    hit: bool
    damage: float
    previous_outcome: str | None = None


@dataclass
class _CalibrationStats:
    resolved: int = 0
    hits: int = 0


def range_band_for(distance: float, config: FireUtilityConfig | None = None) -> str:
    selected = config or FireUtilityConfig()
    if distance < selected.near_distance:
        return "near"
    if distance < selected.far_distance:
        return "mid"
    return "far"


def power_band_for(power: float, config: FireUtilityConfig | None = None) -> str:
    selected = config or FireUtilityConfig()
    if power < selected.low_power:
        return "low"
    if power < selected.high_power:
        return "medium"
    return "high"


def quality_band_for(
    gun_mode: str | None,
    solution_quality: float | None,
    model_support: int,
    config: FireUtilityConfig | None = None,
) -> str:
    selected = config or FireUtilityConfig()
    support = max(0, int(model_support))
    if support < selected.cold_model_support:
        return "cold"
    if gun_mode == "dynamic_cluster" and solution_quality is not None:
        quality = clamp(float(solution_quality), 0.0, 1.0)
        return "high" if quality >= selected.dynamic_high_quality else "low"
    if support < selected.mature_model_support:
        return "warming"
    return "mature"


def build_fire_utility_context(
    gun_mode: str | None,
    distance: float,
    power: float,
    *,
    solution_quality: float | None = None,
    model_support: int = 0,
    config: FireUtilityConfig | None = None,
) -> FireUtilityContext:
    selected = config or FireUtilityConfig()
    normalized_mode = str(gun_mode or "unknown")
    normalized_distance = max(0.0, float(distance))
    normalized_quality = (
        clamp(float(solution_quality), 0.0, 1.0) if solution_quality is not None else None
    )
    normalized_support = max(0, int(model_support))
    return FireUtilityContext(
        gun_mode=normalized_mode,
        distance=normalized_distance,
        range_band=range_band_for(normalized_distance, selected),
        power_band=power_band_for(power, selected),
        quality_band=quality_band_for(
            normalized_mode,
            normalized_quality,
            normalized_support,
            selected,
        ),
        solution_quality=normalized_quality,
        model_support=normalized_support,
    )


def cooldown_turns_for_power(power: float, cooling_rate: float) -> int:
    if cooling_rate <= 0.0:
        return 0
    return max(1, int(math.ceil(gun_heat_for_power(power) / cooling_rate - 1e-9)))


class FireUtilityCalibrator:
    """Causally estimates hit probability from already resolved accepted shots."""

    def __init__(self, config: FireUtilityConfig | None = None) -> None:
        self.config = config or FireUtilityConfig()
        self._stats: dict[tuple[str, ...], _CalibrationStats] = defaultdict(_CalibrationStats)
        self._accepted: dict[str, AcceptedFireUtilityShot] = {}
        self._resolved: dict[str, FireUtilityOutcome] = {}
        self._closed_round_turn: int | None = None

    def estimate(
        self,
        context: FireUtilityContext,
        power: float,
        *,
        cooling_rate: float,
        calibration: FireUtilityCalibrationSnapshot | None = None,
    ) -> FireUtilityEstimate:
        normalized_power = clamp(float(power), 0.1, 3.0)
        normalized_context = replace(
            context,
            power_band=power_band_for(normalized_power, self.config),
        )
        selected_calibration = calibration or self._calibration_snapshot(normalized_context)
        if selected_calibration.power_band != normalized_context.power_band:
            raise ValueError(
                "fire-utility calibration snapshot does not match accepted power band"
            )
        q = selected_calibration.q
        damage = bullet_damage_for_power(normalized_power)
        bonus = bullet_hit_bonus_for_power(normalized_power)
        heat = gun_heat_for_power(normalized_power)
        normalized_cooling_rate = max(0.0, float(cooling_rate))
        return FireUtilityEstimate(
            context=normalized_context,
            power=normalized_power,
            q=clamp(q, 0.0, 1.0),
            calibration_support=selected_calibration.calibration_support,
            calibration_hits=selected_calibration.calibration_hits,
            fallback_level=selected_calibration.fallback_level,
            bullet_damage=damage,
            hit_bonus=bonus,
            gun_heat=heat,
            cooling_rate=normalized_cooling_rate,
            cooldown_turns=cooldown_turns_for_power(normalized_power, normalized_cooling_rate),
            score_utility=q * damage,
            energy_swing_utility=q * (damage + bonus) - normalized_power,
        )

    def snapshot_power_bands(
        self,
        context: FireUtilityContext,
    ) -> tuple[FireUtilityCalibrationSnapshot, ...]:
        return tuple(
            self._calibration_snapshot(replace(context, power_band=power_band))
            for power_band in ("low", "medium", "high")
        )

    def record_accepted_shot(
        self,
        turn: int,
        bullet_id: object,
        target_id: int | None,
        context: FireUtilityContext,
        power: float,
        *,
        cooling_rate: float,
        behavior_reason: str,
        estimate: FireUtilityEstimate | None = None,
        calibration_snapshots: tuple[FireUtilityCalibrationSnapshot, ...] = (),
    ) -> AcceptedFireUtilityShot | None:
        key = _bullet_key(bullet_id)
        if key is None or key in self._accepted or key in self._resolved:
            return None
        normalized_power = clamp(float(power), 0.1, 3.0)
        if (
            estimate is None
            or abs(estimate.power - normalized_power) > 1e-6
            or estimate.context.gun_mode != context.gun_mode
            or estimate.context.range_band != context.range_band
            or estimate.context.quality_band != context.quality_band
        ):
            accepted_power_band = power_band_for(normalized_power, self.config)
            frozen_calibration = next(
                (
                    snapshot
                    for snapshot in calibration_snapshots
                    if snapshot.power_band == accepted_power_band
                ),
                None,
            )
            estimate = self.estimate(
                context,
                normalized_power,
                cooling_rate=cooling_rate,
                calibration=frozen_calibration,
            )
        shot = AcceptedFireUtilityShot(
            bullet_id=key,
            target_id=target_id,
            fired_turn=turn,
            behavior_reason=str(behavior_reason),
            estimate=estimate,
        )
        self._accepted[key] = shot
        return shot

    def resolve_shot(
        self,
        turn: int,
        bullet_id: object,
        outcome: str,
        *,
        damage: float = 0.0,
    ) -> FireUtilityOutcome | None:
        key = _bullet_key(bullet_id)
        shot = self._accepted.pop(key, None) if key is not None else None
        hit = outcome == "hit_bot"
        if shot is None:
            previous = self._resolved.get(key) if key is not None else None
            if previous is None or not hit or previous.outcome != "round_end":
                return None
            self._apply_hit_correction()
            corrected = FireUtilityOutcome(
                bullet_id=previous.bullet_id,
                target_id=previous.target_id,
                fired_turn=previous.fired_turn,
                resolved_turn=turn,
                behavior_reason=previous.behavior_reason,
                estimate=previous.estimate,
                outcome=outcome,
                hit=True,
                damage=max(0.0, float(damage)),
                previous_outcome=previous.outcome,
            )
            self._resolved[corrected.bullet_id] = corrected
            return corrected

        self._apply_outcome(hit)
        resolved = FireUtilityOutcome(
            bullet_id=shot.bullet_id,
            target_id=shot.target_id,
            fired_turn=shot.fired_turn,
            resolved_turn=turn,
            behavior_reason=shot.behavior_reason,
            estimate=shot.estimate,
            outcome=str(outcome),
            hit=hit,
            damage=max(0.0, float(damage)),
        )
        self._resolved[resolved.bullet_id] = resolved
        return resolved

    def close_round(self, turn: int) -> tuple[FireUtilityOutcome, ...]:
        self._closed_round_turn = turn
        outcomes: list[FireUtilityOutcome] = []
        for bullet_id in tuple(self._accepted):
            outcome = self.resolve_shot(turn, bullet_id, "round_end")
            if outcome is not None:
                outcomes.append(outcome)
        return tuple(outcomes)

    def clear_round_state(self) -> None:
        self._accepted.clear()
        self._resolved.clear()
        self._closed_round_turn = None

    def clear_battle_state(self) -> None:
        self._stats.clear()
        self.clear_round_state()

    @property
    def pending_accepted_shots(self) -> int:
        return len(self._accepted)

    @property
    def round_closed_turn(self) -> int | None:
        return self._closed_round_turn

    def _select_stats(self) -> tuple[_CalibrationStats, str]:
        global_stats = self._stats.get(("global",))
        if global_stats is None:
            return _CalibrationStats(), "global_prior"
        return global_stats, "global" if global_stats.resolved else "global_prior"

    def _calibration_snapshot(
        self,
        context: FireUtilityContext,
    ) -> FireUtilityCalibrationSnapshot:
        stats, fallback_level = self._select_stats()
        prior_total = self.config.prior_hits + self.config.prior_misses
        denominator = stats.resolved + prior_total
        q = (
            (stats.hits + self.config.prior_hits) / denominator
            if denominator > 0.0
            else 0.0
        )
        if (
            context.gun_mode == "dynamic_cluster"
            and context.solution_quality is not None
            and context.solution_quality >= self.config.dynamic_high_quality
        ):
            adjusted_numerator = q * max(
                0.0,
                self.config.dynamic_high_quality_odds_multiplier,
            )
            adjusted_denominator = 1.0 - q + adjusted_numerator
            q = (
                adjusted_numerator / adjusted_denominator
                if adjusted_denominator > 0.0
                else 0.0
            )
            fallback_level = (
                "dynamic_quality" if stats.resolved else "dynamic_quality_prior"
            )
        return FireUtilityCalibrationSnapshot(
            power_band=context.power_band,
            q=clamp(q, 0.0, 1.0),
            calibration_support=stats.resolved,
            calibration_hits=stats.hits,
            fallback_level=fallback_level,
        )

    def _apply_outcome(self, hit: bool) -> None:
        stats = self._stats[("global",)]
        stats.resolved += 1
        if hit:
            stats.hits += 1

    def _apply_hit_correction(self) -> None:
        self._stats[("global",)].hits += 1


def _bullet_key(bullet_id: object) -> str | None:
    if bullet_id is None:
        return None
    if isinstance(bullet_id, (int, str)):
        return str(bullet_id)
    return None

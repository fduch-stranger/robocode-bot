from dataclasses import dataclass
from typing import cast

from bot_core.energy import FireDecision
from bot_core.gun import AimSolution, GunSwitchCandidate, WaveVisit
from bot_core.movement import FlatteningDecision
from bot_core.radar import RadarCommand
from bot_core.target_snapshot import TargetSnapshot
from bot_core.telemetry.sink import TelemetrySink
from bot_core.telemetry.tick import rounded

_UNSET = object()


@dataclass(frozen=True)
class FireTick:
    target: TargetSnapshot
    age: int
    distance: float
    aim: AimSolution
    radar: RadarCommand
    decision: FireDecision
    gun_samples: int
    gun_scores: dict[str, str]
    evade_direction: int
    evading: bool
    movement_mode: str
    strafe_offset: float | None
    flattening: FlatteningDecision | None
    last_enemy_fire_age: int
    known_targets: int


@dataclass(frozen=True)
class SimpleTrackTick:
    target: TargetSnapshot
    age: int
    distance: float
    aim: AimSolution
    radar: RadarCommand
    firepower: float
    hold_reason: str
    gun_samples: int
    gun_scores: dict[str, str]
    known_targets: int


class FireTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def record_track(self, tick: FireTick | SimpleTrackTick) -> None:
        self._sink.log("track", **_track_fields(tick))

    def sample_track(self, tick: FireTick | SimpleTrackTick) -> None:
        self._sink.sample("track", **_track_fields(tick))

    def record_gun_switch(self, target_id: int, aim: AimSolution, scores: dict[str, str]) -> None:
        self._sink.log("gun.switch", **_gun_switch_fields(target_id, aim, scores))

    def record_gun_switch_decision(self, target_id: int, aim: AimSolution) -> None:
        self._sink.log("gun.switch_decision", **_gun_switch_decision_fields(target_id, aim))

    def record_wave_visit(self, visit: WaveVisit) -> None:
        self._sink.log("gun.wave_visit", **_wave_visit_fields(visit))

    def record_eval_wave_visit(self, visit: WaveVisit) -> None:
        self._sink.log("gun.eval_wave_visit", **_wave_visit_fields(visit))

    def record_bullet_hit_bot(
        self,
        victim_id: int,
        bullet_id: int,
        power: float,
        damage: float,
        energy: float,
        tracked_fields: dict[str, object],
    ) -> None:
        self._sink.log("bullet.hit_bot", **_bullet_hit_bot_fields(victim_id, bullet_id, power, damage, energy, tracked_fields))

    def record_bullet_fired(
        self,
        bullet_id: int,
        target_id: int | None,
        power: float,
        direction: float,
        energy: float,
        gun_waves: int,
        gun_samples: int,
        gun_confidence: float,
        gun_confidence_visits: int,
        tracked_fields: dict[str, object],
        *,
        target_age: int | None | object = _UNSET,
        target_x: float | None | object = _UNSET,
        target_y: float | None | object = _UNSET,
        wave_created: bool | object = _UNSET,
        shadow_bullets: int | object = _UNSET,
    ) -> None:
        self._sink.log(
            "bullet.fired",
            **_bullet_fired_fields(
                bullet_id,
                target_id,
                power,
                direction,
                energy,
                gun_waves,
                gun_samples,
                gun_confidence,
                gun_confidence_visits,
                tracked_fields,
                target_age=target_age,
                target_x=target_x,
                target_y=target_y,
                wave_created=wave_created,
                shadow_bullets=shadow_bullets,
            ),
        )


def _track_fields(tick: FireTick | SimpleTrackTick) -> dict[str, object]:
    if isinstance(tick, SimpleTrackTick):
        return {
            **_track_base_fields(tick.target, tick.age, tick.distance, tick.aim, tick.radar, tick.gun_samples, tick.gun_scores, tick.known_targets),
            "radar_target": tick.radar.target.bot_id,
            "firepower": tick.firepower,
            "hold_reason": tick.hold_reason,
        }
    return {
        **_track_base_fields(tick.target, tick.age, tick.distance, tick.aim, tick.radar, tick.gun_samples, tick.gun_scores, tick.known_targets),
        "radar_bearing": round(tick.radar.bearing, 2),
        "fire_alignment_limit": tick.decision.alignment_limit,
        "hold_reason": tick.decision.reason,
        "evade_direction": tick.evade_direction,
        "evading": tick.evading,
        "movement_mode": tick.movement_mode,
        "strafe_offset": rounded(tick.strafe_offset, 1),
        "flatten_reason": tick.flattening.reason if tick.flattening is not None else None,
        "flatten_bucket": tick.flattening.bucket if tick.flattening is not None else None,
        "last_enemy_fire_age": tick.last_enemy_fire_age,
    }


def _track_base_fields(
    target: TargetSnapshot,
    age: int,
    distance: float,
    aim: AimSolution,
    radar: RadarCommand,
    gun_samples: int,
    gun_scores: dict[str, str],
    known_targets: int,
) -> dict[str, object]:
    return {
        "target": target.bot_id,
        "age": age,
        "distance": round(distance, 1),
        "gun_bearing": round(aim.gun_bearing, 2),
        "radar_turn": round(radar.turn, 2),
        "radar_mode": radar.mode,
        "radar_age": radar.age,
        "predicted_x": round(aim.predicted_x, 1),
        "predicted_y": round(aim.predicted_y, 1),
        "aim_mode": aim.mode,
        "aim_guess_factor": rounded(aim.guess_factor, 3),
        "gun_samples": gun_samples,
        "gun_scores": gun_scores,
        "known_targets": known_targets,
    }


def _gun_switch_fields(target_id: int, aim: AimSolution, scores: dict[str, str]) -> dict[str, object]:
    return {
        "target": target_id,
        "previous": aim.previous_mode,
        "selected": aim.mode,
        "scores": scores,
    }


def _gun_switch_decision_fields(target_id: int, aim: AimSolution) -> dict[str, object]:
    return {
        "target": target_id,
        "previous": aim.previous_mode,
        "selected": aim.mode,
        "changed": aim.mode_changed,
        "candidates": [_gun_switch_candidate_fields(candidate) for candidate in aim.switch_candidates],
    }


def _gun_switch_candidate_fields(candidate: GunSwitchCandidate) -> dict[str, object]:
    return {
        "mode": candidate.mode,
        "available": candidate.available,
        "score": round(candidate.score, 3),
        "current_score": round(candidate.current_score, 3),
        "raw_score": round(candidate.raw_score if candidate.raw_score is not None else candidate.score, 3),
        "raw_current_score": round(
            candidate.raw_current_score if candidate.raw_current_score is not None else candidate.current_score,
            3,
        ),
        "confidence_penalty": round(candidate.confidence_penalty, 3),
        "current_confidence_penalty": round(candidate.current_confidence_penalty, 3),
        "visits": candidate.visits,
        "required_visits": candidate.required_visits,
        "min_score": round(candidate.min_score, 3),
        "margin": round(candidate.margin, 3),
        "reason": candidate.reason,
    }


def _bullet_hit_bot_fields(
    victim_id: int,
    bullet_id: int,
    power: float,
    damage: float,
    energy: float,
    tracked_fields: dict[str, object],
) -> dict[str, object]:
    return {
        "victim": victim_id,
        "bullet_id": bullet_id,
        "power": round(power, 2),
        "damage": round(damage, 2),
        "energy": round(energy, 1),
        **tracked_fields,
    }


def _bullet_fired_fields(
    bullet_id: int,
    target_id: int | None,
    power: float,
    direction: float,
    energy: float,
    gun_waves: int,
    gun_samples: int,
    gun_confidence: float,
    gun_confidence_visits: int,
    tracked_fields: dict[str, object],
    *,
    target_age: int | None | object = _UNSET,
    target_x: float | None | object = _UNSET,
    target_y: float | None | object = _UNSET,
    wave_created: bool | object = _UNSET,
    shadow_bullets: int | object = _UNSET,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "bullet_id": bullet_id,
        "target": target_id,
        "power": power,
        "direction": round(direction, 1),
        "energy": round(energy, 1),
        "gun_waves": gun_waves,
        "gun_samples": gun_samples,
        "gun_confidence": round(gun_confidence, 3),
        "gun_confidence_visits": gun_confidence_visits,
    }
    if target_age is not _UNSET:
        fields["target_age"] = cast(int | None, target_age)
    if target_x is not _UNSET:
        target_x_value = cast(float | None, target_x)
        fields["target_x"] = round(target_x_value, 1) if target_x_value is not None else None
    if target_y is not _UNSET:
        target_y_value = cast(float | None, target_y)
        fields["target_y"] = round(target_y_value, 1) if target_y_value is not None else None
    if wave_created is not _UNSET:
        fields["wave"] = cast(bool, wave_created)
    if shadow_bullets is not _UNSET:
        fields["shadow_bullets"] = cast(int, shadow_bullets)
    fields.update(tracked_fields)
    return fields


def _wave_visit_fields(visit: WaveVisit) -> dict[str, object]:
    return {
        "target": visit.target_id,
        "guess_factor": round(visit.guess_factor, 3),
        "samples": visit.samples,
        "traveled": round(visit.traveled, 1),
        "distance": round(visit.distance, 1),
        "selected_gun": visit.selected_gun,
        "virtual_scores": visit.virtual_scores,
        "gun_scores": visit.gun_scores,
    }

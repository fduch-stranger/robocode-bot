from dataclasses import dataclass

from bot_core.energy import FireDecision
from bot_core.gun import AimSolution, WaveVisit
from bot_core.movement import FlatteningDecision
from bot_core.radar import RadarCommand
from bot_core.target_snapshot import TargetSnapshot
from bot_core.telemetry.tick import rounded


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


def track_fields(tick: FireTick) -> dict[str, object]:
    return {
        "target": tick.target.bot_id,
        "age": tick.age,
        "distance": round(tick.distance, 1),
        "gun_bearing": round(tick.aim.gun_bearing, 2),
        "radar_bearing": round(tick.radar.bearing, 2),
        "radar_turn": round(tick.radar.turn, 2),
        "radar_mode": tick.radar.mode,
        "radar_age": tick.radar.age,
        "predicted_x": round(tick.aim.predicted_x, 1),
        "predicted_y": round(tick.aim.predicted_y, 1),
        "aim_mode": tick.aim.mode,
        "aim_guess_factor": rounded(tick.aim.guess_factor, 3),
        "gun_samples": tick.gun_samples,
        "gun_scores": tick.gun_scores,
        "fire_alignment_limit": tick.decision.alignment_limit,
        "hold_reason": tick.decision.reason,
        "evade_direction": tick.evade_direction,
        "evading": tick.evading,
        "movement_mode": tick.movement_mode,
        "strafe_offset": rounded(tick.strafe_offset, 1),
        "flatten_reason": tick.flattening.reason if tick.flattening is not None else None,
        "flatten_bucket": tick.flattening.bucket if tick.flattening is not None else None,
        "last_enemy_fire_age": tick.last_enemy_fire_age,
        "known_targets": tick.known_targets,
    }


def simple_track_fields(tick: SimpleTrackTick) -> dict[str, object]:
    return {
        "target": tick.target.bot_id,
        "age": tick.age,
        "distance": round(tick.distance, 1),
        "gun_bearing": round(tick.aim.gun_bearing, 2),
        "radar_turn": round(tick.radar.turn, 2),
        "radar_mode": tick.radar.mode,
        "radar_target": tick.radar.target.bot_id,
        "radar_age": tick.radar.age,
        "firepower": tick.firepower,
        "hold_reason": tick.hold_reason,
        "predicted_x": round(tick.aim.predicted_x, 1),
        "predicted_y": round(tick.aim.predicted_y, 1),
        "aim_mode": tick.aim.mode,
        "aim_guess_factor": rounded(tick.aim.guess_factor, 3),
        "gun_samples": tick.gun_samples,
        "gun_scores": tick.gun_scores,
        "known_targets": tick.known_targets,
    }


def gun_switch_fields(target_id: int, aim: AimSolution, scores: dict[str, str]) -> dict[str, object]:
    return {
        "target": target_id,
        "previous": aim.previous_mode,
        "selected": aim.mode,
        "scores": scores,
    }


def wave_visit_fields(visit: WaveVisit) -> dict[str, object]:
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

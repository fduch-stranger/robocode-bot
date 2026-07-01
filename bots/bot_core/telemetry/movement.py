from bot_core.movement import FlatteningDecision, GoToSurfDecision, MinimumRiskDecision, MovementCommand, MovementProfileVisit
from bot_core.telemetry.tick import rounded


def minimum_risk_fields(
    target_id: int,
    decision: MinimumRiskDecision,
    command: MovementCommand,
    known_targets: int,
    fire_threat_id: int | None = None,
    include_fire_threat: bool = False,
) -> dict[str, object]:
    fields = {
        "target": target_id,
        "destination_x": round(decision.x, 1),
        "destination_y": round(decision.y, 1),
        "risk": round(decision.risk, 3),
        "candidates": decision.candidates,
        "nearest_enemy": decision.nearest_enemy_id,
        "nearest_enemy_distance": round(decision.nearest_enemy_distance, 1),
        "reused_destination": decision.reused,
        "destination_age": decision.age,
        "turn": round(command.turn, 2),
        "speed": command.speed,
        "known_targets": known_targets,
    }
    if include_fire_threat or fire_threat_id is not None:
        fields["fire_threat"] = fire_threat_id
    return fields


def flattening_fields(
    target_id: int,
    current_direction: int,
    flattening: FlatteningDecision,
    distance: float,
    include_reason: bool = False,
) -> dict[str, object]:
    fields = {
        "target": target_id,
        "current_direction": current_direction,
        "suggested_direction": flattening.direction,
        "bucket": flattening.bucket,
        "current_count": round(flattening.current_count, 1),
        "alternative_count": round(flattening.alternative_count, 1),
        "distance": round(distance, 1),
    }
    if include_reason:
        fields["reason"] = flattening.reason
    return fields


def simple_flattening_fields(
    target_id: int,
    flattening: FlatteningDecision,
    distance: float,
) -> dict[str, object]:
    return {
        "target": target_id,
        "suggested_direction": flattening.direction,
        "bucket": flattening.bucket,
        "current_count": round(flattening.current_count, 1),
        "alternative_count": round(flattening.alternative_count, 1),
        "distance": round(distance, 1),
    }


def wall_avoid_fields(x: float, y: float, center_bearing: float, move_direction: int) -> dict[str, object]:
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "center_bearing": round(center_bearing, 2),
        "move_direction": move_direction,
    }


def goto_surf_fields(
    target_id: int,
    decision: GoToSurfDecision,
    command: MovementCommand,
    evade_direction: int,
) -> dict[str, object]:
    return {
        "target": target_id,
        "destination_x": round(decision.x, 1),
        "destination_y": round(decision.y, 1),
        "danger": round(decision.danger, 3),
        "profile_danger": round(decision.profile_danger, 3),
        "ensemble_danger": round(decision.ensemble_danger, 3),
        "ensemble_samples": round(decision.ensemble_samples, 1),
        "ensemble_weight": round(decision.ensemble_weight, 3),
        "wall_risk": round(decision.wall_risk, 3),
        "distance_risk": round(decision.distance_risk, 3),
        "travel_risk": round(decision.travel_risk, 3),
        "candidates": decision.candidates,
        "wave_kind": decision.wave_kind,
        "hit_guess_factor": round(decision.hit_guess_factor, 3),
        "hit_bin": decision.hit_bin,
        "hit_turn": decision.hit_turn,
        "evade_direction": evade_direction,
        "turn": round(command.turn, 2),
        "speed": command.speed,
    }


def duel_potential_fields(
    target_id: int,
    destination_x: float,
    destination_y: float,
    force_x: float,
    force_y: float,
    distance: float,
    mode: str,
    evading: bool,
    evade_direction: int,
    command: MovementCommand,
) -> dict[str, object]:
    return {
        "target": target_id,
        "destination_x": round(destination_x, 1),
        "destination_y": round(destination_y, 1),
        "force_x": round(force_x, 3),
        "force_y": round(force_y, 3),
        "distance": round(distance, 1),
        "mode": mode,
        "evading": evading,
        "evade_direction": evade_direction,
        "turn": round(command.turn, 2),
        "speed": command.speed,
    }


def profile_visit_fields(visit: MovementProfileVisit) -> dict[str, object]:
    return {
        "target": visit.target_id,
        "guess_factor": round(visit.guess_factor, 3),
        "bin": visit.bin_index,
        "bucket": visit.bucket,
        "visits": round(visit.visits, 1),
        "wave_age": visit.wave_age,
        "ensemble_danger": round(visit.ensemble_danger, 3),
        "ensemble_samples": round(visit.ensemble_samples, 1),
    }

from bot_core.movement import FlatteningDecision, GoToSurfDecision, MinimumRiskDecision, MovementCommand, MovementProfileVisit
from bot_core.telemetry.sink import TelemetrySink


class MovementTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def sample_wall_avoid(self, x: float, y: float, center_bearing: float, move_direction: int) -> None:
        self._sink.sample("wall.avoid", **_wall_avoid_fields(x, y, center_bearing, move_direction))

    def sample_minimum_risk(
        self,
        target_id: int,
        decision: MinimumRiskDecision,
        command: MovementCommand,
        known_targets: int,
        fire_threat_id: int | None = None,
        include_fire_threat: bool = False,
    ) -> None:
        self._sink.sample(
            "movement.minimum_risk",
            **_minimum_risk_fields(target_id, decision, command, known_targets, fire_threat_id, include_fire_threat),
        )

    def record_profile_visit(self, visit: MovementProfileVisit) -> None:
        self._sink.log("movement.profile_visit", **_profile_visit_fields(visit))

    def record_flattening(
        self,
        target_id: int,
        flattening: FlatteningDecision,
        distance: float,
        current_direction: int | None = None,
        include_reason: bool = False,
    ) -> None:
        self._sink.log(
            "movement.flatten",
            **_flattening_fields(target_id, flattening, distance, current_direction=current_direction, include_reason=include_reason),
        )

    def record_duel_flattening(
        self,
        target_id: int,
        flattening: FlatteningDecision,
        distance: float,
        current_direction: int,
    ) -> None:
        self._sink.log(
            "movement.duel_flatten",
            **_flattening_fields(target_id, flattening, distance, current_direction=current_direction, include_reason=True),
        )

    def record_flattening_shadow(
        self,
        target_id: int,
        flattening: FlatteningDecision,
        distance: float,
        current_direction: int,
    ) -> None:
        self._sink.log(
            "movement.flatten_shadow",
            **_flattening_fields(target_id, flattening, distance, current_direction=current_direction),
        )

    def sample_goto_surf(
        self,
        target_id: int,
        decision: GoToSurfDecision,
        command: MovementCommand,
        evade_direction: int,
    ) -> None:
        self._sink.sample("movement.goto_surf", **_goto_surf_fields(target_id, decision, command, evade_direction))

    def sample_duel_potential(
        self,
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
    ) -> None:
        self._sink.sample(
            "movement.duel_potential",
            **_duel_potential_fields(
                target_id,
                destination_x,
                destination_y,
                force_x,
                force_y,
                distance,
                mode,
                evading,
                evade_direction,
                command,
            ),
        )


def _minimum_risk_fields(
    target_id: int,
    decision: MinimumRiskDecision,
    command: MovementCommand,
    known_targets: int,
    fire_threat_id: int | None = None,
    include_fire_threat: bool = False,
) -> dict[str, object]:
    fields: dict[str, object] = {
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


def _flattening_fields(
    target_id: int,
    flattening: FlatteningDecision,
    distance: float,
    current_direction: int | None = None,
    include_reason: bool = False,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "target": target_id,
        "suggested_direction": flattening.direction,
        "bucket": flattening.bucket,
        "current_count": round(flattening.current_count, 1),
        "alternative_count": round(flattening.alternative_count, 1),
        "distance": round(distance, 1),
    }
    if current_direction is not None:
        fields["current_direction"] = current_direction
    if include_reason:
        fields["reason"] = flattening.reason
    return fields


def _wall_avoid_fields(x: float, y: float, center_bearing: float, move_direction: int) -> dict[str, object]:
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "center_bearing": round(center_bearing, 2),
        "move_direction": move_direction,
    }


def _goto_surf_fields(
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


def _duel_potential_fields(
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


def _profile_visit_fields(visit: MovementProfileVisit) -> dict[str, object]:
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

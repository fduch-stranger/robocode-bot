from bot_core.movement import FlatteningDecision, GoToSurfDecision, MinimumRiskDecision, MovementCommand, MovementProfileVisit
from bot_core.telemetry.sink import TelemetrySink


class MovementTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def sample_wall_avoid(self, x: float, y: float, center_bearing: float, move_direction: int) -> None:
        self._sink.sample("wall.avoid", **_wall_avoid_fields(x, y, center_bearing, move_direction))

    def sample_target_wall_avoid(self, x: float, y: float, center_bearing: float, target_id: int) -> None:
        self._sink.sample("wall.avoid", **_target_wall_avoid_fields(x, y, center_bearing, target_id))

    def sample_search_wall_avoid(self, x: float, y: float, center_bearing: float, evade_direction: int, near_wall: bool) -> None:
        self._sink.sample("search.wall_avoid", **_search_wall_avoid_fields(x, y, center_bearing, evade_direction, near_wall))

    def sample_separation(
        self,
        target_id: int,
        distance: float,
        away_bearing: float,
        target_speed: float,
        turn_limit: float,
        move_direction: int,
        collision_escape: bool,
    ) -> None:
        self._sink.sample(
            "separate",
            **_separation_fields(target_id, distance, away_bearing, target_speed, turn_limit, move_direction, collision_escape),
        )

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

    def record_feint(
        self,
        target_id: int,
        mode: str,
        reason: str,
        duration: int,
        move_direction: int,
        near_wall: bool,
        variant: str | None = None,
        turn_scale: float | None = None,
    ) -> None:
        self._sink.log(
            "movement.feint",
            **_feint_fields(target_id, mode, reason, duration, move_direction, near_wall, variant, turn_scale),
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

    def sample_evidence_shadow(
        self,
        target_id: int,
        flattening: FlatteningDecision,
        distance: float,
        current_direction: int,
    ) -> None:
        self._sink.sample(
            "movement.evidence_shadow",
            **_evidence_shadow_fields(target_id, flattening, distance, current_direction),
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


def _feint_fields(
    target_id: int,
    mode: str,
    reason: str,
    duration: int,
    move_direction: int,
    near_wall: bool,
    variant: str | None,
    turn_scale: float | None,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "target": target_id,
        "mode": mode,
        "reason": reason,
        "duration": duration,
        "move_direction": move_direction,
        "near_wall": near_wall,
    }
    if variant is not None:
        fields["variant"] = variant
    if turn_scale is not None:
        fields["turn_scale"] = round(turn_scale, 3)
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
    if flattening.legacy_direction is not None or flattening.shadow_direction is not None:
        fields.update(
            score_source=flattening.score_source,
            legacy_direction=flattening.legacy_direction,
            selected_current_danger=round(flattening.selected_current_danger, 3),
            selected_alternative_danger=round(flattening.selected_alternative_danger, 3),
        )
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


def _target_wall_avoid_fields(x: float, y: float, center_bearing: float, target_id: int) -> dict[str, object]:
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "center_bearing": round(center_bearing, 2),
        "target": target_id,
    }


def _search_wall_avoid_fields(
    x: float,
    y: float,
    center_bearing: float,
    evade_direction: int,
    near_wall: bool,
) -> dict[str, object]:
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "center_bearing": round(center_bearing, 2),
        "evade_direction": evade_direction,
        "near_wall": near_wall,
    }


def _separation_fields(
    target_id: int,
    distance: float,
    away_bearing: float,
    target_speed: float,
    turn_limit: float,
    move_direction: int,
    collision_escape: bool,
) -> dict[str, object]:
    return {
        "target": target_id,
        "distance": round(distance, 1),
        "away_bearing": round(away_bearing, 2),
        "target_speed": target_speed,
        "turn_limit": turn_limit,
        "move_direction": move_direction,
        "collision_escape": collision_escape,
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
        "occupancy_danger": round(decision.occupancy_danger, 3),
        "hit_danger": round(decision.hit_danger, 3),
        "hit_profile_support": round(decision.hit_profile_support, 1),
        "hit_fallback_level": decision.hit_fallback_level,
        "expected_pressure": round(decision.expected_pressure, 3),
        "shadow_danger": round(decision.shadow_danger, 3),
        "shadow_destination_x": round(decision.shadow_x, 1) if decision.shadow_x is not None else None,
        "shadow_destination_y": round(decision.shadow_y, 1) if decision.shadow_y is not None else None,
        "shadow_direction": decision.shadow_direction,
        "shadow_selected_danger": round(decision.shadow_selected_danger, 3)
        if decision.shadow_selected_danger is not None
        else None,
        "live_destination_x": round(decision.live_x, 1) if decision.live_x is not None else None,
        "live_destination_y": round(decision.live_y, 1) if decision.live_y is not None else None,
        "live_direction": decision.live_direction,
        "live_selected_danger": round(decision.live_selected_danger, 3)
        if decision.live_selected_danger is not None
        else None,
        "score_source": decision.score_source,
        "shadow_differs": decision.shadow_x != decision.live_x or decision.shadow_y != decision.live_y,
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
    fields: dict[str, object] = {
        "target": visit.target_id,
        "guess_factor": round(visit.guess_factor, 3),
        "bin": visit.bin_index,
        "bucket": visit.bucket,
        "visits": round(visit.visits, 1),
        "wave_age": visit.wave_age,
        "ensemble_danger": round(visit.ensemble_danger, 3),
        "ensemble_samples": round(visit.ensemble_samples, 1),
        "evidence_kind": visit.evidence_kind,
        "wave_kind": visit.wave_kind,
        "occupancy_visits": round(visit.occupancy_visits, 1),
        "hit_profile_support": round(visit.hit_profile_support, 1),
    }
    if visit.match_error is not None:
        fields["match_error"] = round(visit.match_error, 2)
    return fields


def _evidence_shadow_fields(
    target_id: int,
    flattening: FlatteningDecision,
    distance: float,
    current_direction: int,
) -> dict[str, object]:
    return {
        "target": target_id,
        "distance": round(distance, 1),
        "current_direction": current_direction,
        "live_direction": flattening.legacy_direction,
        "selected_direction": flattening.direction,
        "shadow_direction": flattening.shadow_direction,
        "shadow_differs": flattening.shadow_direction is not None
        and flattening.shadow_direction != flattening.legacy_direction,
        "score_source": flattening.score_source,
        "current_live_danger": round(flattening.current_count, 3),
        "alternative_live_danger": round(flattening.alternative_count, 3),
        "current_occupancy": round(flattening.current_occupancy, 3),
        "alternative_occupancy": round(flattening.alternative_occupancy, 3),
        "current_hit_danger": round(flattening.current_hit_danger, 3),
        "alternative_hit_danger": round(flattening.alternative_hit_danger, 3),
        "current_expected_pressure": round(flattening.current_expected_pressure, 3),
        "alternative_expected_pressure": round(flattening.alternative_expected_pressure, 3),
        "current_shadow_danger": round(flattening.current_shadow_danger, 3),
        "alternative_shadow_danger": round(flattening.alternative_shadow_danger, 3),
        "hit_profile_support": round(flattening.hit_profile_support, 1),
        "hit_fallback_level": flattening.hit_fallback_level,
    }

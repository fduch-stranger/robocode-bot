from dataclasses import dataclass
from typing import cast

from bot_core.energy import FireDecision
from bot_core.geometry.angles import relative_bearing
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

    def record_traditional_gf_profile(self, target_id: int, aim: AimSolution) -> None:
        if _traditional_gf_diagnostics(aim) is not None:
            self._sink.log("gun.traditional_gf_profile", **_traditional_gf_profile_fields(target_id, aim))

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
        selected_gun_confidence: float | object = _UNSET,
        selected_gun_confidence_visits: int | object = _UNSET,
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
                selected_gun_confidence=selected_gun_confidence,
                selected_gun_confidence_visits=selected_gun_confidence_visits,
            ),
        )

    def record_fire_drift(
        self,
        bullet_id: int,
        target_id: int | None,
        aim_mode: str | None,
        planned_x: float,
        planned_y: float,
        planned_direction: float,
        planned_power: float,
        planned_speed: float,
        actual_x: float,
        actual_y: float,
        actual_direction: float,
        actual_power: float,
        actual_speed: float,
    ) -> None:
        self._sink.log(
            "gun.fire_drift",
            **_fire_drift_fields(
                bullet_id,
                target_id,
                aim_mode,
                planned_x,
                planned_y,
                planned_direction,
                planned_power,
                planned_speed,
                actual_x,
                actual_y,
                actual_direction,
                actual_power,
                actual_speed,
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
    fields: dict[str, object] = {
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
    traditional_gf = _traditional_gf_diagnostics(aim)
    if traditional_gf is not None:
        fields.update(
            {
                "traditional_gf_global": rounded(getattr(traditional_gf, "global_guess_factor", None), 3),
                "traditional_gf_global_weight": round(getattr(traditional_gf, "global_weight", 0.0), 1),
                "traditional_gf_segment": rounded(getattr(traditional_gf, "segment_guess_factor", None), 3),
                "traditional_gf_segment_weight": round(getattr(traditional_gf, "segment_weight", 0.0), 1),
                "traditional_gf_blend": round(getattr(traditional_gf, "blend", 0.0), 3),
                "traditional_gf_raw": rounded(getattr(traditional_gf, "raw_guess_factor", None), 3),
                "traditional_gf_selected": rounded(getattr(traditional_gf, "selected_guess_factor", None), 3),
                "traditional_gf_source": getattr(traditional_gf, "source", None),
            }
        )
    return fields


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
    fields: dict[str, object] = {
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
        "source_penalty": round(candidate.source_penalty, 3),
        "current_source_penalty": round(candidate.current_source_penalty, 3),
        "decision_bonus": round(candidate.decision_bonus, 3),
        "current_decision_bonus": round(candidate.current_decision_bonus, 3),
        "eval_score_bonus": round(candidate.eval_score_bonus, 3),
        "current_eval_score_bonus": round(candidate.current_eval_score_bonus, 3),
        "eval_visits": candidate.eval_visits,
        "effective_visits": candidate.effective_visits,
        "visits": candidate.visits,
        "required_visits": candidate.required_visits,
        "min_score": round(candidate.min_score, 3),
        "margin": round(candidate.margin, 3),
        "reason": candidate.reason,
    }
    if candidate.decision_source is not None:
        fields["decision_source"] = candidate.decision_source
        if candidate.mode == "traditional_gf":
            fields["traditional_gf_source"] = candidate.decision_source
    return fields


def _traditional_gf_profile_fields(target_id: int, aim: AimSolution) -> dict[str, object]:
    traditional_gf = _traditional_gf_diagnostics(aim)
    assert traditional_gf is not None
    return {
        "target": target_id,
        "aim_mode": aim.mode,
        "global_guess_factor": rounded(getattr(traditional_gf, "global_guess_factor", None), 3),
        "global_weight": round(getattr(traditional_gf, "global_weight", 0.0), 1),
        "segment_guess_factor": rounded(getattr(traditional_gf, "segment_guess_factor", None), 3),
        "segment_weight": round(getattr(traditional_gf, "segment_weight", 0.0), 1),
        "blend": round(getattr(traditional_gf, "blend", 0.0), 3),
        "raw_guess_factor": rounded(getattr(traditional_gf, "raw_guess_factor", None), 3),
        "selected_guess_factor": rounded(getattr(traditional_gf, "selected_guess_factor", None), 3),
        "source": getattr(traditional_gf, "source", None),
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
    selected_gun_confidence: float | object = _UNSET,
    selected_gun_confidence_visits: int | object = _UNSET,
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
    if selected_gun_confidence is not _UNSET:
        fields["selected_gun_confidence"] = round(cast(float, selected_gun_confidence), 3)
    if selected_gun_confidence_visits is not _UNSET:
        fields["selected_gun_confidence_visits"] = cast(int, selected_gun_confidence_visits)
    fields.update(tracked_fields)
    return fields


def _fire_drift_fields(
    bullet_id: int,
    target_id: int | None,
    aim_mode: str | None,
    planned_x: float,
    planned_y: float,
    planned_direction: float,
    planned_power: float,
    planned_speed: float,
    actual_x: float,
    actual_y: float,
    actual_direction: float,
    actual_power: float,
    actual_speed: float,
) -> dict[str, object]:
    direction_error = relative_bearing(actual_direction, planned_direction)
    source_dx = actual_x - planned_x
    source_dy = actual_y - planned_y
    return {
        "bullet_id": bullet_id,
        "target": target_id,
        "aim_mode": aim_mode,
        "planned_x": round(planned_x, 2),
        "planned_y": round(planned_y, 2),
        "actual_x": round(actual_x, 2),
        "actual_y": round(actual_y, 2),
        "source_error": round((source_dx * source_dx + source_dy * source_dy) ** 0.5, 3),
        "planned_direction": round(planned_direction, 3),
        "actual_direction": round(actual_direction, 3),
        "direction_error": round(direction_error, 3),
        "abs_direction_error": round(abs(direction_error), 3),
        "planned_power": round(planned_power, 3),
        "actual_power": round(actual_power, 3),
        "power_error": round(actual_power - planned_power, 3),
        "planned_speed": round(planned_speed, 3),
        "actual_speed": round(actual_speed, 3),
        "speed_error": round(actual_speed - planned_speed, 3),
    }


def _wave_visit_fields(visit: WaveVisit) -> dict[str, object]:
    fields: dict[str, object] = {
        "target": visit.target_id,
        "guess_factor": round(visit.guess_factor, 3),
        "samples": visit.samples,
        "traveled": round(visit.traveled, 1),
        "distance": round(visit.distance, 1),
        "selected_gun": visit.selected_gun,
        "virtual_scores": visit.virtual_scores,
        "gun_scores": visit.gun_scores,
    }
    fire_context = visit.fire_context
    fields.update(
        {
            "fire_context_tags": sorted(fire_context.movement_tags),
            "fire_context_flight_time": round(fire_context.bullet_flight_time, 2),
            "fire_context_lateral_direction": fire_context.lateral_direction,
            "fire_context_lateral_speed_signed": round(fire_context.lateral_speed_signed, 3),
            "fire_context_lateral_confidence": round(fire_context.lateral_direction_confidence, 3),
            "fire_context_wall_margin": round(fire_context.wall_margin, 3),
            "fire_context_wall_escape_balance": round(fire_context.wall_escape_balance, 3),
            "fire_context_positive_escape_angle": round(fire_context.positive_escape_angle, 3),
            "fire_context_negative_escape_angle": round(fire_context.negative_escape_angle, 3),
            "fire_context_distance_bucket": fire_context.distance_bucket,
            "fire_context_firepower_bucket": fire_context.firepower_bucket,
        }
    )
    dynamic_cluster = visit.gun_diagnostics.get("dynamic_cluster", {})
    dynamic_neighbor_count = _diagnostic_int(dynamic_cluster, "neighbor_count")
    dynamic_avg_neighbor_distance = _diagnostic_float(dynamic_cluster, "avg_neighbor_distance")
    dynamic_neighbor_distance_min = _diagnostic_float(dynamic_cluster, "neighbor_distance_min")
    dynamic_neighbor_distance_max = _diagnostic_float(dynamic_cluster, "neighbor_distance_max")
    dynamic_tag_match_ratio = _diagnostic_float(dynamic_cluster, "tag_match_ratio")
    dynamic_avg_flight_time_delta = _diagnostic_float(dynamic_cluster, "avg_flight_time_delta")
    dynamic_avg_wall_escape_delta = _diagnostic_float(dynamic_cluster, "avg_wall_escape_delta")
    dynamic_avg_lateral_confidence = _diagnostic_float(dynamic_cluster, "avg_lateral_confidence")
    dynamic_density_score = _diagnostic_float(dynamic_cluster, "density_score")
    dynamic_selected_guess_factor = _diagnostic_float(dynamic_cluster, "selected_guess_factor")
    dynamic_effective_bandwidth = _diagnostic_float(dynamic_cluster, "effective_bandwidth")
    dynamic_best_bin_guess_factor = _diagnostic_float(dynamic_cluster, "best_bin_guess_factor")
    dynamic_peak_margin = _diagnostic_float(dynamic_cluster, "peak_margin")
    dynamic_neighbor_agreement = _diagnostic_float(dynamic_cluster, "neighbor_agreement")
    dynamic_aim_confidence = _diagnostic_float(dynamic_cluster, "aim_confidence")
    dynamic_best_peak_gf = _diagnostic_float(dynamic_cluster, "best_peak_gf")
    dynamic_best_peak_score = _diagnostic_float(dynamic_cluster, "best_peak_score")
    dynamic_second_peak_gf = _diagnostic_float(dynamic_cluster, "second_peak_gf")
    dynamic_second_peak_score = _diagnostic_float(dynamic_cluster, "second_peak_score")
    dynamic_peak_separation = _diagnostic_float(dynamic_cluster, "peak_separation")
    dynamic_peak_score_ratio = _diagnostic_float(dynamic_cluster, "peak_score_ratio")
    dynamic_ambiguous_peak = _diagnostic_bool(dynamic_cluster, "ambiguous_peak")
    if dynamic_neighbor_count is not None:
        fields["dynamic_cluster_neighbor_count"] = dynamic_neighbor_count
    if dynamic_avg_neighbor_distance is not None:
        fields["dynamic_cluster_avg_neighbor_distance"] = round(dynamic_avg_neighbor_distance, 3)
    if dynamic_neighbor_distance_min is not None:
        fields["dynamic_cluster_neighbor_distance_min"] = round(dynamic_neighbor_distance_min, 3)
    if dynamic_neighbor_distance_max is not None:
        fields["dynamic_cluster_neighbor_distance_max"] = round(dynamic_neighbor_distance_max, 3)
    if dynamic_tag_match_ratio is not None:
        fields["dynamic_cluster_tag_match_ratio"] = round(dynamic_tag_match_ratio, 3)
    if dynamic_avg_flight_time_delta is not None:
        fields["dynamic_cluster_avg_flight_time_delta"] = round(dynamic_avg_flight_time_delta, 3)
    if dynamic_avg_wall_escape_delta is not None:
        fields["dynamic_cluster_avg_wall_escape_delta"] = round(dynamic_avg_wall_escape_delta, 3)
    if dynamic_avg_lateral_confidence is not None:
        fields["dynamic_cluster_avg_lateral_confidence"] = round(dynamic_avg_lateral_confidence, 3)
    if dynamic_density_score is not None:
        fields["dynamic_cluster_density_score"] = round(dynamic_density_score, 3)
    if dynamic_selected_guess_factor is not None:
        fields["dynamic_cluster_selected_guess_factor"] = round(dynamic_selected_guess_factor, 3)
    if dynamic_effective_bandwidth is not None:
        fields["dynamic_cluster_effective_bandwidth"] = round(dynamic_effective_bandwidth, 3)
    if dynamic_best_bin_guess_factor is not None:
        fields["dynamic_cluster_best_bin_guess_factor"] = round(dynamic_best_bin_guess_factor, 3)
    if dynamic_peak_margin is not None:
        fields["dynamic_cluster_peak_margin"] = round(dynamic_peak_margin, 3)
    if dynamic_neighbor_agreement is not None:
        fields["dynamic_cluster_neighbor_agreement"] = round(dynamic_neighbor_agreement, 3)
    if dynamic_aim_confidence is not None:
        fields["dynamic_cluster_aim_confidence"] = round(dynamic_aim_confidence, 3)
    if dynamic_best_peak_gf is not None:
        fields["dynamic_cluster_best_peak_gf"] = round(dynamic_best_peak_gf, 3)
    if dynamic_best_peak_score is not None:
        fields["dynamic_cluster_best_peak_score"] = round(dynamic_best_peak_score, 3)
    if dynamic_second_peak_gf is not None:
        fields["dynamic_cluster_second_peak_gf"] = round(dynamic_second_peak_gf, 3)
    if dynamic_second_peak_score is not None:
        fields["dynamic_cluster_second_peak_score"] = round(dynamic_second_peak_score, 3)
    if dynamic_peak_separation is not None:
        fields["dynamic_cluster_peak_separation"] = round(dynamic_peak_separation, 3)
    if dynamic_peak_score_ratio is not None:
        fields["dynamic_cluster_peak_score_ratio"] = round(dynamic_peak_score_ratio, 3)
    if dynamic_ambiguous_peak is not None:
        fields["dynamic_cluster_ambiguous_peak"] = dynamic_ambiguous_peak
    traditional_gf = visit.gun_diagnostics.get("traditional_gf", {})
    aim_guess_factor = _diagnostic_float(traditional_gf, "aim_guess_factor")
    raw_guess_factor = _diagnostic_float(traditional_gf, "raw_guess_factor")
    error = _diagnostic_float(traditional_gf, "error")
    abs_error = _diagnostic_float(traditional_gf, "abs_error")
    source = _diagnostic_str(traditional_gf, "source")
    if aim_guess_factor is not None:
        fields["traditional_gf_guess_factor"] = round(aim_guess_factor, 3)
    if raw_guess_factor is not None:
        fields["traditional_gf_raw_guess_factor"] = round(raw_guess_factor, 3)
    if error is not None:
        fields["traditional_gf_error"] = round(error, 3)
    if abs_error is not None:
        fields["traditional_gf_abs_error"] = round(abs_error, 3)
    if source is not None:
        fields["traditional_gf_source"] = source
    traditional_context_flight_time = _diagnostic_float(traditional_gf, "context_flight_time")
    traditional_context_wall_escape_balance = _diagnostic_float(traditional_gf, "context_wall_escape_balance")
    traditional_context_lateral_confidence = _diagnostic_float(traditional_gf, "context_lateral_confidence")
    traditional_context_tags = _diagnostic_tags(traditional_gf, "context_tags")
    if traditional_context_flight_time is not None:
        fields["traditional_gf_context_flight_time"] = round(traditional_context_flight_time, 2)
    if traditional_context_wall_escape_balance is not None:
        fields["traditional_gf_context_wall_escape_balance"] = round(traditional_context_wall_escape_balance, 3)
    if traditional_context_lateral_confidence is not None:
        fields["traditional_gf_context_lateral_confidence"] = round(traditional_context_lateral_confidence, 3)
    if traditional_context_tags is not None:
        fields["traditional_gf_context_tags"] = traditional_context_tags
    anti_surfer = visit.gun_diagnostics.get("anti_surfer", {})
    anti_surfer_relevance = _diagnostic_float(anti_surfer, "surfer_relevance")
    anti_surfer_wall_escape_balance = _diagnostic_float(anti_surfer, "wall_escape_balance")
    anti_surfer_tags = _diagnostic_tags(anti_surfer, "context_tags")
    if anti_surfer_relevance is not None:
        fields["anti_surfer_context_relevance"] = round(anti_surfer_relevance, 3)
    if anti_surfer_wall_escape_balance is not None:
        fields["anti_surfer_wall_escape_balance"] = round(anti_surfer_wall_escape_balance, 3)
    if anti_surfer_tags is not None:
        fields["anti_surfer_context_tags"] = anti_surfer_tags
    displacement = visit.gun_diagnostics.get("displacement", {})
    displacement_flight_time = _diagnostic_float(displacement, "flight_time")
    displacement_wall_escape_balance = _diagnostic_float(displacement, "wall_escape_balance")
    displacement_tags = _diagnostic_tags(displacement, "context_tags")
    if displacement_flight_time is not None:
        fields["displacement_context_flight_time"] = round(displacement_flight_time, 2)
    if displacement_wall_escape_balance is not None:
        fields["displacement_wall_escape_balance"] = round(displacement_wall_escape_balance, 3)
    if displacement_tags is not None:
        fields["displacement_context_tags"] = displacement_tags
    linear = visit.gun_diagnostics.get("linear", {})
    if not linear:
        linear = visit.gun_diagnostics.get("linear_wall_aware", {})
    linear_flight_time = _diagnostic_float(linear, "flight_time")
    linear_lateral_confidence = _diagnostic_float(linear, "lateral_confidence")
    linear_short_flight_time = _diagnostic_bool(linear, "short_flight_time")
    linear_tags = _diagnostic_tags(linear, "context_tags")
    if linear_flight_time is not None:
        fields["linear_context_flight_time"] = round(linear_flight_time, 2)
    if linear_lateral_confidence is not None:
        fields["linear_context_lateral_confidence"] = round(linear_lateral_confidence, 3)
    if linear_short_flight_time is not None:
        fields["linear_context_short_flight_time"] = linear_short_flight_time
    if linear_tags is not None:
        fields["linear_context_tags"] = linear_tags
    linear_wall_aware = visit.gun_diagnostics.get("linear_wall_aware", {})
    linear_wall_aware_wall_hit = _diagnostic_bool(linear_wall_aware, "wall_hit")
    linear_wall_aware_ticks = _diagnostic_int(linear_wall_aware, "ticks")
    linear_wall_aware_final_speed = _diagnostic_float(linear_wall_aware, "final_speed")
    if linear_wall_aware_wall_hit is not None:
        fields["linear_wall_aware_wall_hit"] = linear_wall_aware_wall_hit
    if linear_wall_aware_ticks is not None:
        fields["linear_wall_aware_ticks"] = linear_wall_aware_ticks
    if linear_wall_aware_final_speed is not None:
        fields["linear_wall_aware_final_speed"] = round(linear_wall_aware_final_speed, 3)
    return fields


def _traditional_gf_diagnostics(aim: AimSolution) -> object | None:
    return aim.gun_diagnostics.get("traditional_gf")


def _diagnostic_float(diagnostics: object, key: str) -> float | None:
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get(key)
    return value if isinstance(value, float) else None


def _diagnostic_str(diagnostics: object, key: str) -> str | None:
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get(key)
    return value if isinstance(value, str) else None


def _diagnostic_int(diagnostics: object, key: str) -> int | None:
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get(key)
    return value if isinstance(value, int) else None


def _diagnostic_bool(diagnostics: object, key: str) -> bool | None:
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get(key)
    return value if isinstance(value, bool) else None


def _diagnostic_tags(diagnostics: object, key: str) -> list[str] | None:
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get(key)
    if isinstance(value, frozenset | set | list | tuple):
        return sorted(str(tag) for tag in value)
    return None

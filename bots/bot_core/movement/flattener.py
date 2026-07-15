import math
from dataclasses import replace

from robocode_tank_royale.bot_api import Bot

from bot_core.movement.config import MovementFlatteningConfig
from bot_core.movement.danger import MovementDangerModel
from bot_core.movement.decisions import (
    FlatteningDecision,
    GoToSurfDecision,
    MovementDangerBreakdown,
    MovementEvidenceBreakdown,
    MovementProfileVisit,
)
from bot_core.movement.profile import MovementProfile
from bot_core.movement.surfing import SurfingPlanner
from bot_core.movement.waves import MovementWave, MovementWaveFeatures, MovementWaveStore, ShadowBullet
from bot_core.physics import MAX_ROBOT_SPEED, RobotMovementState, bullet_speed_for_power, predict_robot_movement
from bot_core.geometry.numeric import clamp
from bot_core.geometry.waves import guess_factor_from_offset, wall_limited_escape_angle_from_state
from bot_core.target_snapshot import TargetSnapshot


class MovementFlattener:
    def __init__(self, config: MovementFlatteningConfig | None = None) -> None:
        self.config = config or MovementFlatteningConfig()
        self._wave_store = MovementWaveStore()
        self._legacy_behavior_profile = MovementProfile(self.config)
        self._visit_occupancy_profile = MovementProfile(self.config)
        self._enemy_hit_profile = MovementProfile(self.config)
        self._danger_model = MovementDangerModel(self.config, self._legacy_behavior_profile)
        self._surfing = SurfingPlanner(self.config, self._wave_store)
        self._profile = self._legacy_behavior_profile.profile
        self._stats_buffers = self._legacy_behavior_profile.stats_buffers
        self._waves = self._wave_store.waves
        self._shadow_bullets: list[ShadowBullet] = []
        self._last_switch_turn: dict[int, int] = {}

    @property
    def shadow_bullet_count(self) -> int:
        return len(self._shadow_bullets)

    @property
    def wave_count(self) -> int:
        return len(self._waves)

    def record_shadow_bullet(
        self,
        bot: Bot,
        bullet_id: object,
        fire_power: float,
        direction: float,
    ) -> None:
        self.record_shadow_bullet_state(
            bullet_id,
            bot.x,
            bot.y,
            direction,
            bullet_speed_for_power(fire_power),
            bot.turn_number,
        )

    def record_shadow_bullet_state(
        self,
        bullet_id: object,
        source_x: float,
        source_y: float,
        direction: float,
        bullet_speed: float,
        fired_turn: int,
    ) -> None:
        if not self.config.bullet_shadow_enabled:
            return
        self._shadow_bullets.append(
            ShadowBullet(
                bullet_id=self._shadow_bullet_key(bullet_id),
                source_x=source_x,
                source_y=source_y,
                direction=direction,
                bullet_speed=bullet_speed,
                fired_turn=fired_turn,
            )
        )

    def remove_shadow_bullet(self, bullet_id: object) -> None:
        key = self._shadow_bullet_key(bullet_id)
        self._shadow_bullets = [bullet for bullet in self._shadow_bullets if bullet.bullet_id != key]

    @staticmethod
    def _shadow_bullet_key(bullet_id: object) -> str:
        if isinstance(bullet_id, (int, str)):
            return str(bullet_id)
        return f"<{type(bullet_id).__name__}>"

    def record_enemy_fire(
        self,
        bot: Bot,
        target: TargetSnapshot,
        fire_power: float,
        wave_kind: str = "confirmed",
        expected_confidence: float = 1.0,
        fired_turn: int | None = None,
        acceleration: float = 0.0,
        direction_change_age: int = 0,
        decel_age: int = 0,
    ) -> MovementWave | None:
        distance = math.hypot(bot.x - target.x, bot.y - target.y)
        if not (self.config.min_distance <= distance <= self.config.max_distance):
            return None

        if wave_kind == "confirmed":
            self._wave_store.remove_recent_expected(target.bot_id, bot.turn_number, 4)

        bullet_speed = bullet_speed_for_power(fire_power)
        wave_lateral_direction = self._lateral_direction(bot, target) or 1
        features = self._wave_features(
            bot,
            target,
            distance,
            bullet_speed,
            acceleration=acceleration,
            direction_change_age=direction_change_age,
            decel_age=decel_age,
        )
        wave = MovementWave(
            target_id=target.bot_id,
            source_x=target.x,
            source_y=target.y,
            direct_bearing=self._absolute_bearing(target.x, target.y, bot.x, bot.y),
            lateral_direction=wave_lateral_direction,
            bullet_speed=bullet_speed,
            max_escape_angle_positive=wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                wave_lateral_direction,
                start_direction=bot.direction,
                start_speed=bot.speed,
            ),
            max_escape_angle_negative=wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                -wave_lateral_direction,
                start_direction=bot.direction,
                start_speed=bot.speed,
            ),
            fired_turn=bot.turn_number if fired_turn is None else fired_turn,
            distance_bucket=self._distance_bucket(distance),
            kind=wave_kind,
            expected_confidence=clamp(expected_confidence, 0.0, 1.0),
            features=features,
        )
        self._wave_store.add(wave)
        return wave

    def update(self, bot: Bot) -> list[MovementProfileVisit]:
        self._expire_shadow_bullets(bot)
        visits: list[MovementProfileVisit] = []
        remaining_waves: list[MovementWave] = []
        for wave in self._wave_store.waves:
            wave_age = bot.turn_number - wave.fired_turn
            if wave_age < 1:
                remaining_waves.append(wave)
                continue

            wave_radius = wave.bullet_speed * wave_age
            distance = math.hypot(bot.x - wave.source_x, bot.y - wave.source_y)
            if wave_radius < distance - 18:
                remaining_waves.append(wave)
                continue

            guess_factor = self._guess_factor(wave, bot.x, bot.y)
            bin_index = self._bin_index(guess_factor)
            profile_visits = self._record_visit(wave, bin_index, 1.0)
            occupancy_visits = 0.0
            if wave.kind == "confirmed":
                occupancy_visits = self._visit_occupancy_profile.record(wave, bin_index, 1.0)
            danger = self._danger_breakdown(wave, bin_index)
            evidence = self._evidence_breakdown(wave, bin_index, bot.x, bot.y)
            visits.append(
                MovementProfileVisit(
                    target_id=wave.target_id,
                    guess_factor=guess_factor,
                    bin_index=bin_index,
                    bucket=wave.distance_bucket,
                    visits=profile_visits,
                    wave_age=wave_age,
                    ensemble_danger=danger.ensemble_danger,
                    ensemble_samples=danger.ensemble_samples,
                    evidence_kind="occupancy" if wave.kind == "confirmed" else "expected_expired",
                    wave_kind=wave.kind,
                    occupancy_visits=occupancy_visits,
                    hit_profile_support=evidence.hit_profile_support,
                )
            )
        self._wave_store.replace(remaining_waves)
        return visits

    def record_bullet_hit(self, bot: Bot, target_id: int, bullet_power: float) -> MovementProfileVisit | None:
        if not self._wave_store.waves:
            return None

        bullet_speed = bullet_speed_for_power(bullet_power)
        candidates = self._wave_store.matching_target_speed(target_id, bullet_speed, 1.2)
        if not candidates:
            return None

        def hit_error(candidate_wave: MovementWave) -> float:
            wave_age = max(1, bot.turn_number - candidate_wave.fired_turn)
            wave_radius = candidate_wave.bullet_speed * wave_age
            distance = math.hypot(bot.x - candidate_wave.source_x, bot.y - candidate_wave.source_y)
            return abs(distance - wave_radius)

        wave = min(candidates, key=hit_error)
        match_error = hit_error(wave)
        if match_error > self.config.bullet_hit_wave_tolerance:
            return None

        guess_factor = self._guess_factor(wave, bot.x, bot.y)
        bin_index = self._bin_index(guess_factor)
        visits = self._record_visit(wave, bin_index, self.config.bullet_hit_visit_weight)
        self._enemy_hit_profile.record(wave, bin_index, 1.0)
        danger = self._danger_breakdown(wave, bin_index)
        evidence = self._evidence_breakdown(wave, bin_index, bot.x, bot.y)
        self._wave_store.remove(wave)
        return MovementProfileVisit(
            target_id=wave.target_id,
            guess_factor=guess_factor,
            bin_index=bin_index,
            bucket=wave.distance_bucket,
            visits=visits,
            wave_age=max(1, bot.turn_number - wave.fired_turn),
            ensemble_danger=danger.ensemble_danger,
            ensemble_samples=danger.ensemble_samples,
            evidence_kind="enemy_hit",
            wave_kind=wave.kind,
            hit_profile_support=evidence.hit_profile_support,
            match_error=match_error,
        )

    def choose_direction(
        self,
        bot: Bot,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        target_id: int,
        distance: float,
        current_direction: int,
        turn_number: int,
        allow_switch: bool,
        use_surfing: bool = True,
    ) -> FlatteningDecision:
        bucket = self._distance_bucket(distance)
        if not allow_switch:
            return self._decision(current_direction, False, "locked", target_id, bucket, current_direction)

        if not (self.config.min_distance <= distance <= self.config.max_distance):
            return self._decision(current_direction, False, "distance", target_id, bucket, current_direction)

        if turn_number - self._last_switch_turn.get(target_id, -1000) < self.config.switch_cooldown:
            return self._decision(current_direction, False, "cooldown", target_id, bucket, current_direction)

        wave = self._surf_wave(bot, target_id) if use_surfing else self._best_wave(target_id)
        if wave is None:
            return self._decision(current_direction, False, "no_wave", target_id, bucket, current_direction)

        alternative = -1 if current_direction >= 0 else 1
        current_count = self._candidate_score(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            current_direction,
            use_surfing,
        )
        alternative_count = self._candidate_score(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            alternative,
            use_surfing,
        )
        current_x, current_y = self._candidate_projection(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            current_direction,
            use_surfing,
        )
        alternative_x, alternative_y = self._candidate_projection(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            alternative,
            use_surfing,
        )
        current_evidence = self._evidence_breakdown(
            wave,
            self._bin_index(self._guess_factor(wave, current_x, current_y)),
            current_x,
            current_y,
        )
        alternative_evidence = self._evidence_breakdown(
            wave,
            self._bin_index(self._guess_factor(wave, alternative_x, alternative_y)),
            alternative_x,
            alternative_y,
        )
        selected_current_danger = current_count
        selected_alternative_danger = alternative_count
        legacy_margin = self.config.switch_margin
        if use_surfing and min(current_count, alternative_count) < 1.0:
            legacy_margin *= 0.35
        shadow_margin = self.config.switch_margin
        if use_surfing and min(current_evidence.shadow_danger, alternative_evidence.shadow_danger) < 1.0:
            shadow_margin *= 0.35
        legacy_direction = alternative if alternative_count + legacy_margin < current_count else current_direction
        shadow_direction = (
            alternative
            if alternative_evidence.shadow_danger + shadow_margin < current_evidence.shadow_danger
            else current_direction
        )
        evidence_fields = {
            "shadow_direction": shadow_direction,
            "current_occupancy": current_evidence.occupancy_danger,
            "alternative_occupancy": alternative_evidence.occupancy_danger,
            "current_hit_danger": current_evidence.hit_danger,
            "alternative_hit_danger": alternative_evidence.hit_danger,
            "current_expected_pressure": current_evidence.expected_pressure,
            "alternative_expected_pressure": alternative_evidence.expected_pressure,
            "current_shadow_danger": current_evidence.shadow_danger,
            "alternative_shadow_danger": alternative_evidence.shadow_danger,
            "hit_profile_support": current_evidence.hit_profile_support,
            "hit_fallback_level": current_evidence.hit_fallback_level,
            "legacy_direction": legacy_direction,
            "score_source": "legacy",
            "selected_current_danger": selected_current_danger,
            "selected_alternative_danger": selected_alternative_danger,
        }
        if selected_alternative_danger + legacy_margin >= selected_current_danger:
            return FlatteningDecision(
                direction=current_direction,
                changed=False,
                reason="balanced",
                bucket=bucket,
                current_count=current_count,
                alternative_count=alternative_count,
                **evidence_fields,
            )

        self._last_switch_turn[target_id] = turn_number
        return FlatteningDecision(
            direction=alternative,
            changed=True,
            reason="flatten",
            bucket=bucket,
            current_count=current_count,
            alternative_count=alternative_count,
            **evidence_fields,
        )

    def choose_go_to_surf_destination(
        self,
        bot: Bot,
        target: TargetSnapshot,
        max_speed: float,
        field_margin: float,
    ) -> GoToSurfDecision | None:
        wave = self._surf_wave(bot, target.bot_id)
        if wave is None:
            return None
        if wave.kind == "expected":
            if not self.config.goto_use_expected_waves:
                return None
            if wave.expected_confidence < self.config.goto_expected_wave_min_confidence:
                return None

        candidates = self._go_to_candidate_points(bot, target, field_margin)
        best: GoToSurfDecision | None = None
        shadow_best: GoToSurfDecision | None = None
        for destination_x, destination_y in candidates:
            decision = self._score_go_to_candidate(
                bot,
                target,
                wave,
                destination_x,
                destination_y,
                max_speed,
                field_margin,
            )
            if decision is None:
                continue
            if best is None or decision.danger < best.danger:
                best = decision
            if shadow_best is None or decision.shadow_danger < shadow_best.shadow_danger:
                shadow_best = decision

        if best is None or shadow_best is None:
            return None

        return replace(
            best,
            candidates=len(candidates),
            live_x=best.x,
            live_y=best.y,
            live_direction=best.direction,
            live_selected_danger=best.danger,
            shadow_x=shadow_best.x,
            shadow_y=shadow_best.y,
            shadow_direction=shadow_best.direction,
            shadow_selected_danger=shadow_best.shadow_danger,
            score_source="legacy",
        )

    def clear_round_state(self) -> None:
        self._wave_store.clear_round_state()
        self._shadow_bullets.clear()
        self._last_switch_turn.clear()

    def clear_battle_state(self) -> None:
        self._wave_store = MovementWaveStore()
        self._legacy_behavior_profile = MovementProfile(self.config)
        self._visit_occupancy_profile = MovementProfile(self.config)
        self._enemy_hit_profile = MovementProfile(self.config)
        self._danger_model = MovementDangerModel(self.config, self._legacy_behavior_profile)
        self._surfing = SurfingPlanner(self.config, self._wave_store)
        self._profile = self._legacy_behavior_profile.profile
        self._stats_buffers = self._legacy_behavior_profile.stats_buffers
        self._waves = self._wave_store.waves
        self._shadow_bullets.clear()
        self._last_switch_turn.clear()

    def remove_target(self, target_id: int, clear_profile: bool = True) -> None:
        self._wave_store.remove_target(target_id)
        if clear_profile:
            self._legacy_behavior_profile.remove_target(target_id)
            self._visit_occupancy_profile.remove_target(target_id)
            self._enemy_hit_profile.remove_target(target_id)
        self._last_switch_turn.pop(target_id, None)

    def _decision(
        self,
        direction: int,
        changed: bool,
        reason: str,
        target_id: int,
        bucket: int,
        current_direction: int,
    ) -> FlatteningDecision:
        alternative = -1 if current_direction >= 0 else 1
        return FlatteningDecision(
            direction=direction,
            changed=changed,
            reason=reason,
            bucket=bucket,
            current_count=self._count(target_id, bucket, current_direction),
            alternative_count=self._count(target_id, bucket, alternative),
        )

    def _count(self, target_id: int, bucket: int, direction: int) -> float:
        wave = self._best_wave(target_id)
        if wave is None:
            return 0.0
        offset_bin = self.config.bin_count // 2 + (1 if direction >= 0 else -1)
        return self._smoothed_count(target_id, bucket, offset_bin)

    def _decay_if_needed(self, target_id: int) -> None:
        self._legacy_behavior_profile.decay_if_needed(target_id)

    def _record_visit(self, wave: MovementWave, bin_index: int, weight: float) -> float:
        return self._legacy_behavior_profile.record(wave, bin_index, weight)

    @staticmethod
    def _wave_features(
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        bullet_speed: float,
        acceleration: float,
        direction_change_age: int,
        decel_age: int,
    ) -> MovementWaveFeatures:
        target_to_bot = math.atan2(bot.y - target.y, bot.x - target.x)
        bot_heading = math.radians(bot.direction)
        velocity_x = math.cos(bot_heading) * bot.speed
        velocity_y = math.sin(bot_heading) * bot.speed
        radial_x = math.cos(target_to_bot)
        radial_y = math.sin(target_to_bot)
        lateral_x = -radial_y
        lateral_y = radial_x
        return MovementWaveFeatures(
            lateral_velocity=velocity_x * lateral_x + velocity_y * lateral_y,
            advancing_velocity=velocity_x * radial_x + velocity_y * radial_y,
            bullet_flight_time=distance / max(0.1, bullet_speed),
            acceleration=acceleration,
            direction_change_age=max(0, direction_change_age),
            decel_age=max(0, decel_age),
            wall_distance=min(bot.x, bot.arena_width - bot.x, bot.y, bot.arena_height - bot.y),
        )

    def _distance_bucket(self, distance: float) -> int:
        if distance < self.config.near_distance:
            return 0
        if distance < self.config.mid_distance:
            return 1
        return 2

    def _best_wave(self, target_id: int) -> MovementWave | None:
        candidates = self._wave_store.for_target(target_id)
        if not candidates:
            return None
        return max(candidates, key=lambda wave: wave.fired_turn)

    def _surf_wave(self, bot: Bot, target_id: int) -> MovementWave | None:
        return self._surfing.surf_wave(bot, target_id)

    def _candidate_score(
        self,
        bot: Bot,
        wave: MovementWave,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
        use_surfing: bool,
    ) -> float:
        projected_x, projected_y = self._candidate_projection(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            direction,
            use_surfing,
        )
        guess_factor = self._guess_factor(wave, projected_x, projected_y)
        bin_index = self._bin_index(guess_factor)
        if use_surfing:
            return self._danger(wave, bin_index, bot)
        return self._smoothed_count(wave.target_id, wave.distance_bucket, bin_index)

    def _candidate_projection(
        self,
        bot: Bot,
        wave: MovementWave,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
        use_surfing: bool,
    ) -> tuple[float, float]:
        if use_surfing:
            return self._project_surf_position(
                bot,
                wave,
                strafe_offset,
                move_speed,
                field_margin,
                direction,
            )
        return self._project_position(
            bot,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            direction,
        )

    def _project_position(
        self,
        bot: Bot,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
    ) -> tuple[float, float]:
        movement_bearing = math.radians(bot.direction + body_bearing + strafe_offset * direction)
        distance = move_speed * self.config.lookahead_ticks
        return (
            clamp(bot.x + math.cos(movement_bearing) * distance, field_margin, bot.arena_width - field_margin),
            clamp(bot.y + math.sin(movement_bearing) * distance, field_margin, bot.arena_height - field_margin),
        )

    def _project_surf_position(
        self,
        bot: Bot,
        wave: MovementWave,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
    ) -> tuple[float, float]:
        projected_x = bot.x
        projected_y = bot.y
        speed = max(0.1, abs(move_speed))
        for tick in range(1, self.config.surf_max_ticks + 1):
            move_bearing = self._surf_move_bearing(
                projected_x,
                projected_y,
                wave,
                strafe_offset,
                direction,
                field_margin,
                bot.arena_width,
                bot.arena_height,
            )
            projected_x = clamp(
                projected_x + math.cos(math.radians(move_bearing)) * speed,
                field_margin,
                bot.arena_width - field_margin,
            )
            projected_y = clamp(
                projected_y + math.sin(math.radians(move_bearing)) * speed,
                field_margin,
                bot.arena_height - field_margin,
            )
            wave_radius = wave.bullet_speed * max(0, bot.turn_number + tick - wave.fired_turn)
            distance = math.hypot(projected_x - wave.source_x, projected_y - wave.source_y)
            if wave_radius + self.config.surf_intercept_margin >= distance:
                break
        return projected_x, projected_y

    def _surf_move_bearing(
        self,
        x: float,
        y: float,
        wave: MovementWave,
        strafe_offset: float,
        direction: int,
        field_margin: float,
        arena_width: float,
        arena_height: float,
    ) -> float:
        bearing_to_source = self._absolute_bearing(x, y, wave.source_x, wave.source_y)
        move_bearing = bearing_to_source + strafe_offset * direction
        smoothing_step = -self.config.wall_smoothing_degrees * direction
        for _ in range(self.config.wall_smoothing_attempts):
            stick_x = x + math.cos(math.radians(move_bearing)) * self.config.wall_stick
            stick_y = y + math.sin(math.radians(move_bearing)) * self.config.wall_stick
            if field_margin <= stick_x <= arena_width - field_margin and field_margin <= stick_y <= arena_height - field_margin:
                return move_bearing
            move_bearing += smoothing_step
        return move_bearing

    def _go_to_candidate_points(self, bot: Bot, target: TargetSnapshot, field_margin: float) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        source_to_self = self._absolute_bearing(target.x, target.y, bot.x, bot.y)
        seen: set[tuple[int, int]] = set()
        for distance in self.config.goto_candidate_distances:
            for offset in self.config.goto_candidate_angle_offsets:
                bearing = math.radians(source_to_self + offset)
                x = bot.x + math.cos(bearing) * distance
                y = bot.y + math.sin(bearing) * distance
                if not (field_margin <= x <= bot.arena_width - field_margin):
                    continue
                if not (field_margin <= y <= bot.arena_height - field_margin):
                    continue
                key = (round(x / 8), round(y / 8))
                if key in seen:
                    continue
                seen.add(key)
                points.append((x, y))
        return points

    def _score_go_to_candidate(
        self,
        bot: Bot,
        target: TargetSnapshot,
        wave: MovementWave,
        destination_x: float,
        destination_y: float,
        max_speed: float,
        field_margin: float,
    ) -> GoToSurfDecision | None:
        hit_x, hit_y, hit_turn = self._simulate_go_to_wave_hit(
            bot,
            wave,
            destination_x,
            destination_y,
            max_speed,
            field_margin,
        )
        if hit_turn <= 0:
            return None

        guess_factor = self._guess_factor(wave, hit_x, hit_y)
        bin_index = self._bin_index(guess_factor)
        danger_breakdown = self._danger_breakdown(wave, bin_index)
        evidence = self._evidence_breakdown(wave, bin_index, hit_x, hit_y)
        learned_danger = danger_breakdown.total_danger
        if wave.kind == "expected":
            learned_danger *= self.config.goto_wave_kind_expected_multiplier
        wall_risk = self._go_to_wall_risk(bot, hit_x, hit_y, field_margin)
        distance_risk = self._go_to_target_distance_risk(hit_x, hit_y, target)
        travel_risk = math.hypot(destination_x - bot.x, destination_y - bot.y) * self.config.goto_travel_weight
        danger = learned_danger + wall_risk + distance_risk + travel_risk
        shadow_danger = evidence.shadow_danger + wall_risk + distance_risk + travel_risk
        direction = self._go_to_lateral_direction(bot, target, destination_x, destination_y)
        return GoToSurfDecision(
            x=destination_x,
            y=destination_y,
            danger=danger,
            candidates=0,
            wave_kind=wave.kind,
            hit_guess_factor=guess_factor,
            hit_bin=bin_index,
            hit_turn=hit_turn,
            direction=direction,
            profile_danger=danger_breakdown.profile_danger,
            ensemble_danger=danger_breakdown.ensemble_danger,
            ensemble_samples=danger_breakdown.ensemble_samples,
            ensemble_weight=danger_breakdown.ensemble_weight,
            wall_risk=wall_risk,
            distance_risk=distance_risk,
            travel_risk=travel_risk,
            occupancy_danger=evidence.occupancy_danger,
            hit_danger=evidence.hit_danger,
            hit_profile_support=evidence.hit_profile_support,
            hit_fallback_level=evidence.hit_fallback_level,
            expected_pressure=evidence.expected_pressure,
            shadow_danger=shadow_danger,
        )

    def _simulate_go_to_wave_hit(
        self,
        bot: Bot,
        wave: MovementWave,
        destination_x: float,
        destination_y: float,
        max_speed: float,
        field_margin: float,
    ) -> tuple[float, float, int]:
        state = RobotMovementState(x=bot.x, y=bot.y, direction=bot.direction, speed=bot.speed)
        speed = min(MAX_ROBOT_SPEED, abs(max_speed))
        for tick in range(1, self.config.surf_max_ticks + 1):
            move_bearing = self._absolute_bearing(state.x, state.y, destination_x, destination_y)
            distance_remaining = math.hypot(destination_x - state.x, destination_y - state.y)
            state = predict_robot_movement(
                state,
                move_bearing,
                max_speed=speed,
                distance_remaining=distance_remaining,
                field_margin=field_margin,
                arena_width=bot.arena_width,
                arena_height=bot.arena_height,
            )
            wave_radius = wave.bullet_speed * max(0, bot.turn_number + tick - wave.fired_turn)
            distance_to_wave_source = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
            if wave_radius + self.config.surf_intercept_margin >= distance_to_wave_source:
                return state.x, state.y, tick
            if distance_remaining <= 1.0 and abs(state.speed) <= 0.2:
                return state.x, state.y, tick
        return state.x, state.y, self.config.surf_max_ticks

    def _go_to_wall_risk(self, bot: Bot, x: float, y: float, field_margin: float) -> float:
        margin = min(x, bot.arena_width - x, y, bot.arena_height - y)
        if margin <= field_margin:
            return self.config.goto_wall_weight
        return self.config.goto_wall_weight / max(1.0, margin - field_margin + 1.0)

    def _go_to_target_distance_risk(self, x: float, y: float, target: TargetSnapshot) -> float:
        distance = math.hypot(x - target.x, y - target.y)
        risk = 0.0
        if distance < self.config.goto_min_target_distance:
            close_error = self.config.goto_min_target_distance - distance
            risk += close_error * close_error * self.config.goto_target_distance_weight
            closeness = close_error / max(1.0, self.config.goto_min_target_distance)
            risk += closeness * closeness * self.config.goto_close_enemy_weight
        elif distance > self.config.goto_max_target_distance:
            far_error = distance - self.config.goto_max_target_distance
            risk += far_error * far_error * self.config.goto_target_distance_weight
        else:
            preferred_error = abs(distance - self.config.goto_preferred_target_distance)
            risk += preferred_error * preferred_error * self.config.goto_target_distance_weight * 0.12
        return risk

    @staticmethod
    def _go_to_lateral_direction(
        bot: Bot,
        target: TargetSnapshot,
        destination_x: float,
        destination_y: float,
    ) -> int:
        current_x = bot.x - target.x
        current_y = bot.y - target.y
        destination_vector_x = destination_x - target.x
        destination_vector_y = destination_y - target.y
        cross = current_x * destination_vector_y - current_y * destination_vector_x
        if cross > 0.001:
            return 1
        if cross < -0.001:
            return -1
        return 0

    def _danger(self, wave: MovementWave, bin_index: int, bot: Bot | None = None) -> float:
        danger = self._danger_breakdown(wave, bin_index).total_danger
        if bot is not None and self._has_bullet_shadow(bot, wave, bin_index):
            return danger * self.config.bullet_shadow_danger_multiplier
        return danger

    def _danger_breakdown(self, wave: MovementWave, bin_index: int) -> MovementDangerBreakdown:
        return self._danger_model.breakdown(wave, bin_index)

    def _evidence_breakdown(
        self,
        wave: MovementWave,
        bin_index: int,
        x: float,
        y: float,
    ) -> MovementEvidenceBreakdown:
        occupancy_danger = self._visit_occupancy_profile.smoothed_count(
            wave.target_id,
            wave.distance_bucket,
            bin_index,
        )
        hit_danger = self._enemy_hit_profile.smoothed_count(
            wave.target_id,
            wave.distance_bucket,
            bin_index,
        )
        hit_support = self._enemy_hit_profile.sample_count(wave.target_id, wave.distance_bucket)
        hit_confidence = clamp(
            hit_support / max(1.0, self.config.evidence_shadow_hit_min_samples),
            0.0,
            1.0,
        )
        if hit_support <= 0.0:
            fallback_level = "occupancy"
        elif hit_confidence < 1.0:
            fallback_level = "blended"
        else:
            fallback_level = "hit_profile"
        expected_pressure = self._expected_wave_pressure(wave.target_id, x, y)
        hit_component = min(
            self.config.evidence_shadow_hit_component_cap,
            hit_danger * hit_confidence * self.config.evidence_shadow_hit_weight,
        )
        expected_component = min(
            self.config.evidence_shadow_expected_component_cap,
            expected_pressure * self.config.evidence_shadow_expected_weight,
        )
        shadow_danger = (
            self.config.unvisited_bin_danger
            + occupancy_danger * self.config.evidence_shadow_occupancy_weight
            + hit_component
            + expected_component
        )
        return MovementEvidenceBreakdown(
            occupancy_danger=occupancy_danger,
            hit_danger=hit_danger,
            hit_profile_support=hit_support,
            hit_fallback_level=fallback_level,
            expected_pressure=expected_pressure,
            shadow_danger=shadow_danger,
        )

    def _expected_wave_pressure(self, target_id: int, x: float, y: float) -> float:
        pressure = 0.0
        for expected_wave in self._wave_store.for_target(target_id):
            if expected_wave.kind != "expected":
                continue
            expected_bin = self._bin_index(self._guess_factor(expected_wave, x, y))
            occupancy = self._visit_occupancy_profile.smoothed_count(
                target_id,
                expected_wave.distance_bucket,
                expected_bin,
            )
            pressure += expected_wave.expected_confidence * (self.config.unvisited_bin_danger + occupancy)
        return pressure

    def _has_bullet_shadow(self, bot: Bot, wave: MovementWave, bin_index: int) -> bool:
        if not self.config.bullet_shadow_enabled or not self._shadow_bullets:
            return False
        if wave.kind != "confirmed":
            return False
        start_turn = max(bot.turn_number, wave.fired_turn + 1)
        end_turn = min(
            bot.turn_number + self.config.bullet_shadow_max_ticks,
            wave.fired_turn + self.config.bullet_shadow_max_ticks,
        )
        for bullet in self._shadow_bullets:
            first_turn = max(start_turn, bullet.fired_turn + 1)
            for turn in range(first_turn, end_turn + 1):
                previous_x, previous_y = self._shadow_bullet_position(bullet, turn - 1)
                bullet_x, bullet_y = self._shadow_bullet_position(bullet, turn)
                if not self._point_inside_field(bot, previous_x, previous_y) and not self._point_inside_field(
                    bot, bullet_x, bullet_y
                ):
                    break
                wave_radius = wave.bullet_speed * max(0, turn - wave.fired_turn)
                shadow_x, shadow_y = self._closest_point_on_segment(
                    wave.source_x,
                    wave.source_y,
                    previous_x,
                    previous_y,
                    bullet_x,
                    bullet_y,
                )
                distance_to_wave_source = math.hypot(shadow_x - wave.source_x, shadow_y - wave.source_y)
                if abs(distance_to_wave_source - wave_radius) > self.config.bullet_shadow_radius_margin:
                    continue
                shadow_bin = self._bin_index(self._guess_factor(wave, shadow_x, shadow_y))
                if abs(shadow_bin - bin_index) <= self.config.bullet_shadow_bin_radius:
                    return True
        return False

    def _expire_shadow_bullets(self, bot: Bot) -> None:
        if not self._shadow_bullets:
            return
        remaining: list[ShadowBullet] = []
        for bullet in self._shadow_bullets:
            age = bot.turn_number - bullet.fired_turn
            if age < 0 or age > self.config.bullet_shadow_max_ticks:
                continue
            bullet_x, bullet_y = self._shadow_bullet_position(bullet, bot.turn_number)
            if self._point_inside_field(bot, bullet_x, bullet_y):
                remaining.append(bullet)
        self._shadow_bullets = remaining

    @staticmethod
    def _shadow_bullet_position(bullet: ShadowBullet, turn: int) -> tuple[float, float]:
        age = max(0, turn - bullet.fired_turn)
        bearing = math.radians(bullet.direction)
        return (
            bullet.source_x + math.cos(bearing) * bullet.bullet_speed * age,
            bullet.source_y + math.sin(bearing) * bullet.bullet_speed * age,
        )

    @staticmethod
    def _point_inside_field(bot: Bot, x: float, y: float) -> bool:
        return 0.0 <= x <= bot.arena_width and 0.0 <= y <= bot.arena_height

    @staticmethod
    def _closest_point_on_segment(
        point_x: float,
        point_y: float,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
    ) -> tuple[float, float]:
        segment_x = end_x - start_x
        segment_y = end_y - start_y
        length_squared = segment_x * segment_x + segment_y * segment_y
        if length_squared <= 0.0:
            return start_x, start_y
        projection = ((point_x - start_x) * segment_x + (point_y - start_y) * segment_y) / length_squared
        clamped_projection = clamp(projection, 0.0, 1.0)
        return (
            start_x + segment_x * clamped_projection,
            start_y + segment_y * clamped_projection,
        )

    def _smoothed_count(self, target_id: int, bucket: int, bin_index: int) -> float:
        return self._legacy_behavior_profile.smoothed_count(target_id, bucket, bin_index)

    def _bin_index(self, guess_factor: float) -> int:
        normalized = clamp((guess_factor + 1.0) / 2.0, 0.0, 1.0)
        return round(normalized * (self.config.bin_count - 1))

    def _guess_factor(self, wave: MovementWave, x: float, y: float) -> float:
        bearing = self._absolute_bearing(wave.source_x, wave.source_y, x, y)
        bearing_offset = self._relative_bearing(bearing, wave.direct_bearing)
        return guess_factor_from_offset(
            bearing_offset,
            wave.lateral_direction,
            wave.max_escape_angle_positive,
            wave.max_escape_angle_negative,
        )

    @staticmethod
    def _lateral_direction(bot: Bot, target: TargetSnapshot) -> int:
        target_to_bot = math.atan2(bot.y - target.y, bot.x - target.x)
        bot_heading = math.radians(bot.direction)
        lateral_velocity = bot.speed * math.sin(bot_heading - target_to_bot)
        if lateral_velocity > 0.3:
            return 1
        if lateral_velocity < -0.3:
            return -1
        return 0

    @staticmethod
    def _absolute_bearing(source_x: float, source_y: float, target_x: float, target_y: float) -> float:
        return math.degrees(math.atan2(target_y - source_y, target_x - source_x))

    @staticmethod
    def _relative_bearing(angle: float, reference: float) -> float:
        return ((angle - reference + 180) % 360) - 180

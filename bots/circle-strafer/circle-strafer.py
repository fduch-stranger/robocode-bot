import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    BulletFiredEvent,
    BulletHitBotEvent,
    GameStartedEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from circle_config import (
    FIRE_POLICY,
    GUN_POLICY,
    MOVEMENT_POLICY,
    RADAR_POLICY,
    TARGET_POLICY,
    build_energy_drop_config,
    build_fire_gate,
    build_radar_config,
)
from bot_core.debug import DebugLogger, FiredBulletTracker
from bot_core.energy import (
    EnemyEnergyCorrectionLedger,
    EnemyFireDetector,
    EnemyFirePowerPredictor,
)
from bot_core.gun import (
    AimSolution,
    GunScoringConfig,
    GunSelectorConfig,
    GunSystemConfig,
    TargetMotion,
    VirtualGunSystem,
    should_log_switch_decision,
)
from bot_core.gun.factory import standard_runtime_config
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.movement import MinimumRiskMovement, MovementCommand, MovementFlattener, MovementFlatteningConfig
from bot_core.motion import OwnMotionTracker
from bot_core.radar import lock_priority_radar
from bot_core.geometry.angles import body_bearing_to
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to
from bot_core.movement.navigation import drive_to_destination
from bot_core.target_snapshot import TargetSnapshot, interpolate_target, target_from_hit_bot, target_from_scan
from bot_core.telemetry.energy import EnergyTelemetry
from bot_core.telemetry.fire import (
    FireTelemetry,
    SimpleTrackTick,
)
from bot_core.telemetry.movement import MovementTelemetry
from bot_core.telemetry.targeting import TargetingTelemetry


class CircleStrafer(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Circle Strafer",
                version="1.0",
                authors=["robocode-bot"],
                description="Orbital movement bot with virtual-gun aiming, learned firepower telemetry, wave-hit learning, and conservative bullet shadows.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._move_direction = 1
        self._targets: dict[int, TargetSnapshot] = {}
        self._target_id: int | None = None
        self._collision_escape_until_turn = -1
        self._last_collision_turn = -1000
        self._wall_escape_until_turn = -1
        self._last_wall_hit_turn = -1000
        self._last_turn_number = -1
        self._enemy_energy_corrections = EnemyEnergyCorrectionLedger()
        self._enemy_fire_power = EnemyFirePowerPredictor()
        self._energy_drop_config = build_energy_drop_config()
        self._fire_gate = build_fire_gate()
        self._radar_config = build_radar_config()
        self._enemy_fire_detector = EnemyFireDetector(
            self._energy_drop_config,
            self._enemy_energy_corrections,
            fire_power=self._enemy_fire_power,
        )
        self._evade_until_turn = -1
        self._target_accel: dict[int, float] = {}
        self._last_velocity_change_turn: dict[int, int] = {}
        self._gun = VirtualGunSystem(
            standard_runtime_config(
                system=GunSystemConfig(
                    eval_waves_enabled=GUN_POLICY.eval_waves_enabled,
                    eval_wave_min_interval=GUN_POLICY.eval_wave_min_interval,
                ),
                selector=GunSelectorConfig(
                    selectable_modes=GUN_POLICY.selectable_modes,
                    forced_mode=GUN_POLICY.forced_mode,
                    switch_margin=GUN_POLICY.switch_margin,
                ),
                scoring=GunScoringConfig(selectable_modes=GUN_POLICY.selectable_modes),
                min_visits=GUN_POLICY.min_visits,
                min_switch_score=GUN_POLICY.min_switch_score,
                dynamic_cluster=DynamicClusterGunConfig(
                    min_samples=GUN_POLICY.knn_min_samples,
                    min_switch_visits=GUN_POLICY.min_visits,
                    min_switch_score=GUN_POLICY.min_switch_score,
                ),
                traditional_gf=TraditionalGfGunConfig(
                    min_switch_visits=GUN_POLICY.traditional_gf_min_switch_visits,
                    min_switch_score=GUN_POLICY.traditional_gf_min_switch_score,
                ),
            )
        )
        self._movement = MovementFlattener(
            MovementFlatteningConfig(
                bullet_hit_visit_weight=1.0,
                bullet_shadow_enabled=True,
                bullet_shadow_danger_multiplier=0.65,
            )
        )
        self._own_motion = OwnMotionTracker()
        self._minimum_risk = MinimumRiskMovement()
        self._debug = DebugLogger(self, "circle-strafer")
        self._energy_telemetry = EnergyTelemetry(self._debug)
        self._fire_telemetry = FireTelemetry(self._debug)
        self._movement_telemetry = MovementTelemetry(self._debug)
        self._targeting_telemetry = TargetingTelemetry(self._debug)
        self._fired_bullets = FiredBulletTracker()
        self._last_gun_decision_log_turn: dict[int, int] = {}

    def run(self) -> None:
        self.body_color = Color.from_rgb(214, 75, 54)
        self.turret_color = Color.from_rgb(142, 32, 34)
        self.radar_color = Color.from_rgb(255, 210, 150)
        self.bullet_color = Color.from_rgb(255, 168, 54)
        self.scan_color = Color.from_rgb(255, 225, 145)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 8

        while self.running:
            self._reset_if_new_round()
            self._own_motion.update(self)
            self._forget_stale_targets()
            self._move()
            self._track_target()
            self.go()

    def _move(self) -> None:
        if self._near_wall() or self.turn_number <= self._wall_escape_until_turn:
            center_bearing = body_bearing_to(self, self.arena_width / 2, self.arena_height / 2)
            self.target_speed = MOVEMENT_POLICY.wall_escape_speed
            self.turn_rate = clamp(center_bearing, -10, 10)
            self._movement_telemetry.sample_wall_avoid(self.x, self.y, center_bearing, self._move_direction)
            return

        close_target = self._nearest_target()
        if close_target is not None:
            distance = distance_to(self, close_target.x, close_target.y)
            escaping_collision = self.turn_number <= self._collision_escape_until_turn
            if escaping_collision or distance < MOVEMENT_POLICY.separation_distance:
                away_bearing = body_bearing_to(
                    self,
                    self.x - (close_target.x - self.x),
                    self.y - (close_target.y - self.y),
                )
                lateral_offset = MOVEMENT_POLICY.collision_escape_offset if escaping_collision else (
                    25 if distance < MOVEMENT_POLICY.panic_distance else 55
                )
                turn_limit = MOVEMENT_POLICY.collision_escape_turn_limit if escaping_collision else 10
                self.target_speed = MOVEMENT_POLICY.collision_escape_speed if escaping_collision else MOVEMENT_POLICY.orbit_speed
                self.turn_rate = clamp(
                    away_bearing + lateral_offset * self._move_direction,
                    -turn_limit,
                    turn_limit,
                )
                self._movement_telemetry.sample_separation(
                    close_target.bot_id,
                    distance,
                    away_bearing,
                    self.target_speed,
                    turn_limit,
                    self._move_direction,
                    escaping_collision,
                )
                return

        if len(self._targets) >= 2:
            focus_target = self._targets.get(self._target_id) if self._target_id is not None else None
            focus_target = focus_target or self._nearest_target()
            if focus_target is not None:
                decision = self._minimum_risk.choose(self, list(self._targets.values()), focus_target)
                if decision is not None:
                    turn, speed = self._drive_to_destination(decision.x, decision.y, MOVEMENT_POLICY.orbit_speed)
                    command = MovementCommand("minimum_risk", turn, speed)
                    command.apply(self)
                    self._movement_telemetry.sample_minimum_risk(
                        focus_target.bot_id,
                        decision,
                        command,
                        len(self._targets),
                    )
                    return

        self.target_speed = MOVEMENT_POLICY.orbit_speed * self._move_direction
        evade_boost = 4 if self.turn_number <= self._evade_until_turn else 0
        self.turn_rate = (MOVEMENT_POLICY.orbit_turn_rate + evade_boost) * self._move_direction

    def _near_wall(self) -> bool:
        return (
            self.x < MOVEMENT_POLICY.wall_margin
            or self.x > self.arena_width - MOVEMENT_POLICY.wall_margin
            or self.y < MOVEMENT_POLICY.wall_margin
            or self.y > self.arena_height - MOVEMENT_POLICY.wall_margin
        )

    def on_game_started(self, event: GameStartedEvent) -> None:
        self._clear_opponent_learning()
        self._log(
            "battle.reset",
            rounds=event.game_setup.number_of_rounds,
            game_type=event.game_setup.game_type,
        )

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        self._reset_if_new_round()
        previous = self._targets.get(event.scanned_bot_id)
        previous_age = self.turn_number - previous.seen_turn if previous is not None else None
        if previous is not None:
            self._update_target_motion_stats(event, previous)
            self._detect_enemy_fire(event, previous, previous_age or 0)
        else:
            self._consume_enemy_energy_correction(event.scanned_bot_id, self.turn_number, -1)
        self._targets[event.scanned_bot_id] = target_from_scan(event, self.turn_number)
        target = self._targets[event.scanned_bot_id]
        self._gun.observe_target(target)
        self._log_wave_visits(target)
        if previous is None:
            self._targeting_telemetry.record_scan_new(event.scanned_bot_id, event.energy, event.x, event.y)

    def _detect_enemy_fire(self, event: ScannedBotEvent, previous: TargetSnapshot, scan_gap: int) -> bool:
        distance = distance_to(self, event.x, event.y)
        detection = self._enemy_fire_detector.evaluate_scan(
            event.scanned_bot_id,
            previous.energy,
            event.energy,
            previous.seen_turn,
            self.turn_number,
            scan_gap,
            distance,
            self.energy,
            self.gun_cooling_rate,
        )
        signal = detection.signal
        if not signal.is_fire:
            if signal.raw_energy_drop > 0 or signal.energy_correction:
                self._energy_telemetry.record_drop_ignored(event.scanned_bot_id, signal, scan_gap, distance)
            return False

        actual_fire_power = signal.fire_power or 1.5
        current_target = target_from_scan(event, self.turn_number)
        estimated_fire_turn = max(previous.seen_turn + 1, self.turn_number - max(0, scan_gap - 1))
        fire_source = interpolate_target(previous, current_target, estimated_fire_turn)
        movement_wave = self._movement.record_enemy_fire(
            self,
            fire_source,
            actual_fire_power,
            fired_turn=estimated_fire_turn,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        active_evasion = not self._near_wall()
        if active_evasion:
            self._move_direction *= -1
        self._evade_until_turn = max(self._evade_until_turn, self.turn_number + signal.evade_ticks)
        power_mae = self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id)
        self._energy_telemetry.record_enemy_fire_detected(
            event.scanned_bot_id,
            signal,
            scan_gap,
            distance,
            "active_duel" if active_evasion else "threat_only",
            self._evade_until_turn,
            movement_wave is not None,
            detection.previous_prediction,
            self._enemy_fire_power.sample_count(event.scanned_bot_id),
            power_mae,
            evading=active_evasion,
            move_direction=self._move_direction,
            inferred_fire_turn=estimated_fire_turn,
            fire_source_x=fire_source.x,
            fire_source_y=fire_source.y,
            fire_source_offset=math.hypot(current_target.x - fire_source.x, current_target.y - fire_source.y),
        )
        return True

    def _update_target_motion_stats(self, event: ScannedBotEvent, previous: TargetSnapshot) -> None:
        speed_delta = event.speed - previous.speed
        self._target_accel[event.scanned_bot_id] = speed_delta
        direction_delta = abs(((event.direction - previous.direction + 180) % 360) - 180)
        if abs(speed_delta) > 0.35 or direction_delta > 7:
            self._last_velocity_change_turn[event.scanned_bot_id] = self.turn_number

    def _track_target(self) -> None:
        self._forget_stale_targets()
        target = self._select_target()
        if target is None:
            self.gun_turn_rate = 0
            self.radar_turn_rate = RADAR_POLICY.search_rate
            self._targeting_telemetry.sample_search(known_targets=0)
            return

        distance = distance_to(self, target.x, target.y)
        firepower = self._firepower_for(distance)
        self._log_movement_profile_visits()
        self._apply_movement_flattening(target, distance)
        self._log_wave_visits(target)
        use_segmented_gun_stats = self.enemy_count <= 1
        aim = self._gun.aim(
            self,
            target,
            distance,
            firepower,
            self._target_motion(target),
            MOVEMENT_POLICY.field_margin,
            disabled_modes=frozenset() if use_segmented_gun_stats else frozenset({"traditional_gf"}),
            allow_segmented_stats=use_segmented_gun_stats,
        )
        score_segment = aim.segment_key if use_segmented_gun_stats else None
        if aim.mode_changed:
            self._fire_telemetry.record_gun_switch(target.bot_id, aim, self._gun.score_summary(target.bot_id, score_segment))
        self._maybe_log_gun_switch_decision(target.bot_id, aim)
        radar_command = lock_priority_radar(
            self,
            self._targets.values(),
            target,
            FIRE_POLICY.memory_turns,
            self._radar_config,
        )
        age = self.turn_number - target.seen_turn

        self.set_turn_gun_left(aim.gun_bearing)
        can_fire, hold_reason = self._can_fire(age, distance, aim.gun_bearing, firepower)
        if GUN_POLICY.eval_waves_enabled and age <= 2 and self.gun_heat <= 0 and self.energy > firepower:
            self._gun.maybe_add_eval_wave(self, target, firepower, aim)
        self._fire_telemetry.sample_track(
            SimpleTrackTick(
                target,
                age,
                distance,
                aim,
                radar_command,
                firepower,
                hold_reason,
                self._gun.sample_count,
                self._gun.score_summary(target.bot_id, score_segment),
                len(self._targets),
            )
        )
        if can_fire:
            self._gun.set_pending_wave(self._gun.make_wave(self, target, firepower, aim))
            self.set_fire(firepower)

    def _target_motion(self, target: TargetSnapshot) -> TargetMotion:
        return TargetMotion(
            acceleration=self._target_accel.get(target.bot_id, 0.0),
            velocity_change_age=self.turn_number - self._last_velocity_change_turn.get(target.bot_id, self.turn_number),
        )

    def _log_wave_visits(self, target: TargetSnapshot) -> None:
        for visit in self._gun.update_waves(self, target):
            self._fire_telemetry.record_wave_visit(visit)
        for visit in self._gun.update_eval_waves(self, target):
            self._fire_telemetry.record_eval_wave_visit(visit)

    def _log_movement_profile_visits(self) -> None:
        for visit in self._movement.update(self):
            self._movement_telemetry.record_profile_visit(visit)

    def _apply_movement_flattening(self, target: TargetSnapshot, distance: float) -> None:
        if self.enemy_count > 1:
            return

        body_bearing = body_bearing_to(self, target.x, target.y)
        flattening = self._movement.choose_direction(
            self,
            body_bearing,
            MOVEMENT_POLICY.flattener_strafe_offset,
            MOVEMENT_POLICY.orbit_speed,
            MOVEMENT_POLICY.field_margin,
            target.bot_id,
            distance,
            self._move_direction,
            self.turn_number,
            allow_switch=True,
            use_surfing=True,
        )
        if not flattening.changed:
            return

        self._move_direction = flattening.direction
        self._movement_telemetry.record_flattening(target.bot_id, flattening, distance)

    def _firepower_for(self, distance: float) -> float:
        if self.energy <= FIRE_POLICY.low_energy_hold:
            return 0.8 if distance < 180 else 0.6
        if distance < 170:
            return 1.8
        if distance < 420:
            return 1.0
        return 0.8

    def _can_fire(self, age: int, distance: float, gun_bearing: float, firepower: float) -> tuple[bool, str]:
        decision = self._fire_gate.decide(age, distance, gun_bearing, firepower, self.energy)
        return decision.can_fire, decision.reason

    def _forget_stale_targets(self) -> None:
        stale_ids = [
            bot_id
            for bot_id, target in self._targets.items()
            if self.turn_number - target.seen_turn > TARGET_POLICY.memory_turns
        ]
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
            self._gun.remove_target(bot_id)
            self._movement.remove_target(bot_id, clear_profile=False)
            self._enemy_fire_detector.remove_target(bot_id)
        if self._target_id not in self._targets:
            self._target_id = None

    def _reset_if_new_round(self) -> None:
        if self._last_turn_number >= 0 and self.turn_number < self._last_turn_number:
            self._targets.clear()
            self._target_id = None
            self._collision_escape_until_turn = -1
            self._last_collision_turn = -1000
            self._wall_escape_until_turn = -1
            self._last_wall_hit_turn = -1000
            self._enemy_fire_detector.clear_round_state()
            self._evade_until_turn = -1
            self._target_accel.clear()
            self._last_velocity_change_turn.clear()
            self._own_motion.reset(self.turn_number)
            self._gun.clear_round_state()
            self._movement.clear_round_state()
            self._minimum_risk.clear_round_state()
            self._fired_bullets.clear()
            self._last_gun_decision_log_turn.clear()
            self._log(
                "round.reset",
                previous_turn=self._last_turn_number,
                current_turn=self.turn_number,
            )
        self._last_turn_number = self.turn_number

    def _clear_opponent_learning(self) -> None:
        self._targets.clear()
        self._target_id = None
        self._collision_escape_until_turn = -1
        self._last_collision_turn = -1000
        self._wall_escape_until_turn = -1
        self._last_wall_hit_turn = -1000
        self._enemy_energy_corrections.clear()
        self._enemy_fire_power.clear()
        self._enemy_fire_detector.clear_round_state()
        self._evade_until_turn = -1
        self._gun.clear_battle_state()
        self._movement.clear_battle_state()
        self._minimum_risk.clear_round_state()
        self._fired_bullets.clear()
        self._last_gun_decision_log_turn.clear()
        self._target_accel.clear()
        self._last_velocity_change_turn.clear()
        self._own_motion.reset()
        self._last_turn_number = -1

    def _maybe_log_gun_switch_decision(self, target_id: int, aim: AimSolution) -> None:
        last_turn = self._last_gun_decision_log_turn.get(target_id, -100000)
        if not should_log_switch_decision(aim, self.turn_number, last_turn, GUN_POLICY.switch_diagnostics_interval):
            return
        self._fire_telemetry.record_gun_switch_decision(target_id, aim)
        self._last_gun_decision_log_turn[target_id] = self.turn_number

    def _select_target(self) -> TargetSnapshot | None:
        if not self._targets:
            self._target_id = None
            return None

        previous_id = self._target_id
        candidate = min(self._targets.values(), key=self._target_score)
        target = candidate
        current = self._targets.get(previous_id) if previous_id is not None else None
        current_age = self.turn_number - current.seen_turn if current is not None else 999
        if current is not None and candidate.bot_id != current.bot_id and current_age <= TARGET_POLICY.force_switch_target_age:
            candidate_score = self._target_score(candidate)
            current_score = self._target_score(current)
            if candidate_score + TARGET_POLICY.switch_margin >= current_score:
                target = current

        self._target_id = target.bot_id
        if previous_id != target.bot_id:
            self._targeting_telemetry.record_candidate_selection(
                previous_id,
                target,
                self._target_score(target),
                candidate,
                self._target_score(candidate),
                current_age if current is not None else None,
                len(self._targets),
            )
        return target

    def _nearest_target(self) -> TargetSnapshot | None:
        if not self._targets:
            return None
        return min(self._targets.values(), key=lambda target: distance_to(self, target.x, target.y))

    def _drive_to_destination(self, x: float, y: float, speed: float) -> tuple[float, float]:
        return drive_to_destination(self, x, y, speed)

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = distance_to(self, target.x, target.y)
        age = self.turn_number - target.seen_turn
        current_bonus = TARGET_POLICY.current_target_bonus if target.bot_id == self._target_id else 0
        return distance * 0.5 + target.energy * 1.7 + age * 85 - current_bonus

    def _record_enemy_energy_correction(self, target_id: int, correction: float, reason: str) -> None:
        self._enemy_energy_corrections.record(target_id, self.turn_number, correction, reason)

    def _consume_enemy_energy_correction(self, target_id: int, current_turn: int, after_turn: int) -> float:
        return self._enemy_energy_corrections.consume(target_id, current_turn, after_turn)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._near_wall():
            self._move_direction *= -1
        self.set_turn_left(45)
        movement_visit = None
        if self.enemy_count <= 1:
            movement_visit = self._movement.record_bullet_hit(
                self,
                event.bullet.owner_id,
                event.bullet.power,
            )
        self._log(
            "hit.bullet",
            owner=event.bullet.owner_id,
            power=round(event.bullet.power, 2),
            bullet_direction=round(event.bullet.direction, 1),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            near_wall=self._near_wall(),
            move_direction=self._move_direction,
            movement_wave_match=movement_visit is not None,
            movement_guess_factor=round(movement_visit.guess_factor, 3) if movement_visit is not None else None,
            movement_bin=movement_visit.bin_index if movement_visit is not None else None,
        )

    def on_hit_wall(self, event: HitWallEvent) -> None:
        if self.turn_number - self._last_wall_hit_turn > 8:
            self._move_direction *= -1
        self._last_wall_hit_turn = self.turn_number
        self._wall_escape_until_turn = self.turn_number + MOVEMENT_POLICY.wall_escape_turns
        self.set_turn_left(60)
        self._log(
            "hit.wall",
            move_direction=self._move_direction,
            wall_escape_until=self._wall_escape_until_turn,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._targets[event.victim_id] = target_from_hit_bot(
            event,
            self.turn_number,
            self._targets.get(event.victim_id),
        )
        self._collision_escape_until_turn = self.turn_number + MOVEMENT_POLICY.collision_escape_turns
        if self.turn_number - self._last_collision_turn > 8:
            self._move_direction *= -1
        self._last_collision_turn = self.turn_number
        self._log(
            "hit.bot",
            target=event.victim_id,
            energy=round(event.energy, 1),
            rammed=event.rammed,
            move_direction=self._move_direction,
            collision_escape_until=self._collision_escape_until_turn,
        )

    def on_bullet_hit(self, event: BulletHitBotEvent) -> None:
        self._record_enemy_energy_correction(event.victim_id, event.damage, "our_bullet_damage")
        self._movement.remove_shadow_bullet(event.bullet.bullet_id)
        bullet_fields = self._fired_bullets.fields_for(event.bullet.bullet_id)
        self._fire_telemetry.record_bullet_hit_bot(
            event.victim_id,
            event.bullet.bullet_id,
            event.bullet.power,
            event.damage,
            event.energy,
            bullet_fields,
        )

    def on_bot_death(self, event: BotDeathEvent) -> None:
        self._targets.pop(event.victim_id, None)
        self._gun.remove_target(event.victim_id)
        self._movement.remove_target(event.victim_id, clear_profile=False)
        self._enemy_fire_detector.remove_target(event.victim_id)
        if self._target_id == event.victim_id:
            self._target_id = None
        self._log("target.dead", bot_id=event.victim_id)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        wave = self._gun.record_pending_fire()
        target_id = wave.target_id if wave is not None else self._target_id
        gun_score, gun_visits = self._gun.target_confidence(target_id) if target_id is not None else (0.0, 0)
        selected_gun_score, selected_gun_visits = (
            self._gun.mode_confidence(target_id, wave.aim_mode, wave.segment_key)
            if target_id is not None and wave is not None
            else (0.0, 0)
        )
        self._movement.record_shadow_bullet_state(
            event.bullet.bullet_id,
            event.bullet.x,
            event.bullet.y,
            event.bullet.direction,
            event.bullet.speed,
            self.turn_number,
        )
        bullet_fields = self._fired_bullets.record(
            event.bullet.bullet_id,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
        )
        self._fire_telemetry.record_bullet_fired(
            event.bullet.bullet_id,
            target_id,
            event.bullet.power,
            event.bullet.direction,
            self.energy,
            self._gun.wave_count,
            self._gun.sample_count,
            gun_score,
            gun_visits,
            bullet_fields,
            wave_created=wave is not None,
            shadow_bullets=self._movement.shadow_bullet_count,
            selected_gun_confidence=selected_gun_score,
            selected_gun_confidence_visits=selected_gun_visits,
        )
        if wave is not None:
            self._fire_telemetry.record_fire_drift(
                event.bullet.bullet_id,
                target_id,
                wave.aim_mode,
                wave.source_x,
                wave.source_y,
                wave.virtual_bearings.get(wave.aim_mode, wave.fire_bearing),
                wave.bullet_power,
                wave.bullet_speed,
                event.bullet.x,
                event.bullet.y,
                event.bullet.direction,
                event.bullet.power,
                event.bullet.speed,
            )

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    CircleStrafer().start()

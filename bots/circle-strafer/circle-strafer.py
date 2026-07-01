from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BulletFiredEvent,
    BulletHitBotEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_core.debug import DebugLogger, FiredBulletTracker
from bot_core.energy import (
    EnemyEnergyCorrectionLedger,
    EnemyFirePowerPredictor,
    EnergyDropConfig,
    FireGate,
    FireGateConfig,
    classify_energy_drop,
)
from bot_core.gun import TargetMotion, VirtualGunSystem
from bot_core.movement import MinimumRiskMovement, MovementFlattener, MovementFlatteningConfig
from bot_core.motion import OwnMotionTracker
from bot_core.radar import RadarLockConfig, lock_priority_radar
from bot_core.geometry.angles import body_bearing_to
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to, drive_to_destination
from bot_core.target_snapshot import TargetSnapshot, target_from_hit_bot, target_from_scan


FIRE_ALIGNMENT_DEGREES = 8
TARGET_MEMORY_TURNS = 30
FIRE_MEMORY_TURNS = 5
CURRENT_TARGET_BONUS = 190
TARGET_SWITCH_MARGIN = 110
FORCE_SWITCH_TARGET_AGE = 12
ENEMY_FIRE_MIN_DROP = 0.1
ENEMY_FIRE_MAX_DROP = 3.0
ENEMY_FIRE_SCAN_GAP_TURNS = 4
ENEMY_FIRE_CLOSE_COLLISION_DISTANCE = 75
ENEMY_FIRE_CLOSE_COLLISION_MAX_DROP = 0.8
LOW_ENERGY_HOLD = 18
CRITICAL_ENERGY_HOLD = 10
FIELD_MARGIN = 24
WALL_MARGIN = 110
WALL_ESCAPE_SPEED = 6
ORBIT_SPEED = 8
ORBIT_TURN_RATE = 6
FLATTENER_STRAFE_OFFSET = 92
SEPARATION_DISTANCE = 170
PANIC_DISTANCE = 115
COLLISION_ESCAPE_TURNS = 20
WALL_ESCAPE_TURNS = 18
COLLISION_ESCAPE_SPEED = 4
COLLISION_ESCAPE_OFFSET = 85
COLLISION_ESCAPE_TURN_LIMIT = 20
RADAR_SEARCH_RATE = -16
RADAR_LOCK_RATE = 24
RADAR_REACQUIRE_RATE = 24
RADAR_RESCAN_INTERVAL = 36
RADAR_RESCAN_TURNS = 5
RADAR_REACQUIRE_MIN_ERROR = 8
RADAR_LOCK_OVERSCAN = 12
RADAR_REACQUIRE_OVERSCAN = 22
RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_SEARCH_RATE,
    lock_rate=RADAR_LOCK_RATE,
    reacquire_rate=RADAR_REACQUIRE_RATE,
    rescan_interval=RADAR_RESCAN_INTERVAL,
    rescan_turns=RADAR_RESCAN_TURNS,
    reacquire_min_error=RADAR_REACQUIRE_MIN_ERROR,
    lock_overscan=RADAR_LOCK_OVERSCAN,
    reacquire_overscan=RADAR_REACQUIRE_OVERSCAN,
)
ENERGY_DROP_CONFIG = EnergyDropConfig(
    min_fire_power=ENEMY_FIRE_MIN_DROP,
    max_fire_power=ENEMY_FIRE_MAX_DROP,
    max_scan_gap=ENEMY_FIRE_SCAN_GAP_TURNS,
    close_collision_distance=ENEMY_FIRE_CLOSE_COLLISION_DISTANCE,
    close_collision_max_drop=ENEMY_FIRE_CLOSE_COLLISION_MAX_DROP,
)
FIRE_GATE = FireGate(
    FireGateConfig(
        fire_memory_turns=FIRE_MEMORY_TURNS,
        alignment_degrees=FIRE_ALIGNMENT_DEGREES,
        energy_margin=6,
        critical_energy_hold=CRITICAL_ENERGY_HOLD,
        low_energy_hold=LOW_ENERGY_HOLD,
        low_energy_max_distance=180,
        far_alignment_distance=420,
        far_alignment_degrees=5,
    )
)


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
        self._evade_until_turn = -1
        self._target_accel: dict[int, float] = {}
        self._last_velocity_change_turn: dict[int, int] = {}
        self._gun = VirtualGunSystem()
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
        self._fired_bullets = FiredBulletTracker()

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
            self._move()
            self._track_target()
            self.go()

    def _move(self) -> None:
        if self._near_wall() or self.turn_number <= self._wall_escape_until_turn:
            center_bearing = body_bearing_to(self, self.arena_width / 2, self.arena_height / 2)
            self.target_speed = WALL_ESCAPE_SPEED
            self.turn_rate = clamp(center_bearing, -10, 10)
            self._sample_status(
                "wall.avoid",
                x=round(self.x, 1),
                y=round(self.y, 1),
                center_bearing=round(center_bearing, 2),
                move_direction=self._move_direction,
            )
            return

        close_target = self._nearest_target()
        if close_target is not None:
            distance = distance_to(self, close_target.x, close_target.y)
            escaping_collision = self.turn_number <= self._collision_escape_until_turn
            if escaping_collision or distance < SEPARATION_DISTANCE:
                away_bearing = body_bearing_to(
                    self,
                    self.x - (close_target.x - self.x),
                    self.y - (close_target.y - self.y),
                )
                lateral_offset = COLLISION_ESCAPE_OFFSET if escaping_collision else (
                    25 if distance < PANIC_DISTANCE else 55
                )
                turn_limit = COLLISION_ESCAPE_TURN_LIMIT if escaping_collision else 10
                self.target_speed = COLLISION_ESCAPE_SPEED if escaping_collision else ORBIT_SPEED
                self.turn_rate = clamp(
                    away_bearing + lateral_offset * self._move_direction,
                    -turn_limit,
                    turn_limit,
                )
                self._sample_status(
                    "separate",
                    target=close_target.bot_id,
                    distance=round(distance, 1),
                    away_bearing=round(away_bearing, 2),
                    target_speed=self.target_speed,
                    turn_limit=turn_limit,
                    move_direction=self._move_direction,
                    collision_escape=escaping_collision,
                )
                return

        if len(self._targets) >= 2:
            focus_target = self._targets.get(self._target_id) or self._nearest_target()
            if focus_target is not None:
                decision = self._minimum_risk.choose(self, list(self._targets.values()), focus_target)
                if decision is not None:
                    turn, speed = self._drive_to_destination(decision.x, decision.y, ORBIT_SPEED)
                    self._sample_status(
                        "movement.minimum_risk",
                        target=focus_target.bot_id,
                        destination_x=round(decision.x, 1),
                        destination_y=round(decision.y, 1),
                        risk=round(decision.risk, 3),
                        candidates=decision.candidates,
                        nearest_enemy=decision.nearest_enemy_id,
                        nearest_enemy_distance=round(decision.nearest_enemy_distance, 1),
                        reused_destination=decision.reused,
                        destination_age=decision.age,
                        turn=round(turn, 2),
                        speed=speed,
                        known_targets=len(self._targets),
                    )
                    return

        self.target_speed = ORBIT_SPEED * self._move_direction
        evade_boost = 4 if self.turn_number <= self._evade_until_turn else 0
        self.turn_rate = (ORBIT_TURN_RATE + evade_boost) * self._move_direction

    def _near_wall(self) -> bool:
        return (
            self.x < WALL_MARGIN
            or self.x > self.arena_width - WALL_MARGIN
            or self.y < WALL_MARGIN
            or self.y > self.arena_height - WALL_MARGIN
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
        self._gun.observe_target(self._targets[event.scanned_bot_id])
        if previous is None:
            self._log(
                "scan.new",
                bot_id=event.scanned_bot_id,
                energy=round(event.energy, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )

    def _detect_enemy_fire(self, event: ScannedBotEvent, previous: TargetSnapshot, scan_gap: int) -> bool:
        distance = distance_to(self, event.x, event.y)
        energy_correction = self._consume_enemy_energy_correction(
            event.scanned_bot_id,
            self.turn_number,
            previous.seen_turn,
        )
        signal = classify_energy_drop(
            previous.energy,
            event.energy,
            scan_gap,
            distance,
            ENERGY_DROP_CONFIG,
            energy_correction=energy_correction,
        )
        if not signal.is_fire:
            if signal.raw_energy_drop > 0 or signal.energy_correction:
                self._log(
                    "enemy.energy_drop_ignored",
                    bot_id=event.scanned_bot_id,
                    reason=signal.reason,
                    raw_drop=round(signal.raw_energy_drop, 2),
                    corrected_drop=round(signal.energy_drop, 2),
                    correction=round(signal.energy_correction, 2),
                    scan_gap=scan_gap,
                    distance=round(distance, 1),
                )
            return False

        actual_fire_power = signal.fire_power or 1.5
        prediction = self._enemy_fire_power.predict(
            event.scanned_bot_id,
            enemy_energy=previous.energy,
            our_energy=self.energy,
            distance=distance,
        )
        self._enemy_fire_power.record(
            event.scanned_bot_id,
            enemy_energy=previous.energy,
            our_energy=self.energy,
            distance=distance,
            fire_power=actual_fire_power,
            previous_prediction=prediction,
        )
        movement_wave = self._movement.record_enemy_fire(
            self,
            target_from_scan(event, self.turn_number),
            actual_fire_power,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        active_evasion = not self._near_wall()
        if active_evasion:
            self._move_direction *= -1
        self._evade_until_turn = max(self._evade_until_turn, self.turn_number + signal.evade_ticks)
        self._log(
            "enemy.fire_detected",
            bot_id=event.scanned_bot_id,
            power=round(signal.fire_power or 0.0, 2),
            raw_drop=round(signal.raw_energy_drop, 2),
            corrected_drop=round(signal.energy_drop, 2),
            correction=round(signal.energy_correction, 2),
            scan_gap=scan_gap,
            distance=round(distance, 1),
            bullet_travel_ticks=signal.bullet_travel_ticks,
            evasion="active_duel" if active_evasion else "threat_only",
            evading=active_evasion,
            move_direction=self._move_direction,
            evade_until=self._evade_until_turn,
            movement_wave=movement_wave is not None,
            predicted_power=round(prediction.fire_power, 2),
            prediction_confidence=round(prediction.confidence, 3),
            prediction_reason=prediction.reason,
            prediction_error=round(abs(prediction.fire_power - actual_fire_power), 2),
            power_samples=self._enemy_fire_power.sample_count(event.scanned_bot_id),
            power_mae=round(self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id), 3)
            if self._enemy_fire_power.mean_absolute_error(event.scanned_bot_id) is not None
            else None,
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
            self.radar_turn_rate = RADAR_SEARCH_RATE
            self._sample_status("search", known_targets=0)
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
            FIELD_MARGIN,
            allow_traditional_gf=use_segmented_gun_stats,
            allow_segmented_stats=use_segmented_gun_stats,
        )
        score_segment = aim.segment_key if use_segmented_gun_stats else None
        if aim.mode_changed:
            self._log(
                "gun.switch",
                target=target.bot_id,
                previous=aim.previous_mode,
                selected=aim.mode,
                scores=self._gun.score_summary(target.bot_id, score_segment),
            )
        radar_command = lock_priority_radar(
            self,
            self._targets.values(),
            target,
            FIRE_MEMORY_TURNS,
            RADAR_CONFIG,
        )
        age = self.turn_number - target.seen_turn

        self.set_turn_gun_left(aim.gun_bearing)
        can_fire, hold_reason = self._can_fire(age, distance, aim.gun_bearing, firepower)
        if can_fire:
            self._gun.set_pending_wave(self._gun.make_wave(self, target, firepower, aim))
            self.set_fire(firepower)
        else:
            self._sample_status(
                "track",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                gun_bearing=round(aim.gun_bearing, 2),
                radar_turn=round(radar_command.turn, 2),
                radar_mode=radar_command.mode,
                radar_target=radar_command.target.bot_id,
                radar_age=radar_command.age,
                firepower=firepower,
                hold_reason=hold_reason,
                predicted_x=round(aim.predicted_x, 1),
                predicted_y=round(aim.predicted_y, 1),
                aim_mode=aim.mode,
                aim_guess_factor=round(aim.guess_factor, 3) if aim.guess_factor is not None else None,
                gun_samples=self._gun.sample_count,
                gun_scores=self._gun.score_summary(target.bot_id, score_segment),
                known_targets=len(self._targets),
            )

    def _target_motion(self, target: TargetSnapshot) -> TargetMotion:
        return TargetMotion(
            acceleration=self._target_accel.get(target.bot_id, 0.0),
            velocity_change_age=self.turn_number - self._last_velocity_change_turn.get(target.bot_id, self.turn_number),
        )

    def _log_wave_visits(self, target: TargetSnapshot) -> None:
        for visit in self._gun.update_waves(self, target):
            self._log(
                "gun.wave_visit",
                target=visit.target_id,
                guess_factor=round(visit.guess_factor, 3),
                samples=visit.samples,
                traveled=round(visit.traveled, 1),
                distance=round(visit.distance, 1),
                selected_gun=visit.selected_gun,
                virtual_scores=visit.virtual_scores,
                gun_scores=visit.gun_scores,
            )

    def _log_movement_profile_visits(self) -> None:
        for visit in self._movement.update(self):
            self._log(
                "movement.profile_visit",
                target=visit.target_id,
                guess_factor=round(visit.guess_factor, 3),
                bin=visit.bin_index,
                bucket=visit.bucket,
                visits=round(visit.visits, 1),
                wave_age=visit.wave_age,
                ensemble_danger=round(visit.ensemble_danger, 3),
                ensemble_samples=round(visit.ensemble_samples, 1),
            )

    def _apply_movement_flattening(self, target: TargetSnapshot, distance: float) -> None:
        if self.enemy_count > 1:
            return

        body_bearing = body_bearing_to(self, target.x, target.y)
        flattening = self._movement.choose_direction(
            self,
            body_bearing,
            FLATTENER_STRAFE_OFFSET,
            ORBIT_SPEED,
            FIELD_MARGIN,
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
        self._log(
            "movement.flatten",
            target=target.bot_id,
            suggested_direction=flattening.direction,
            bucket=flattening.bucket,
            current_count=round(flattening.current_count, 1),
            alternative_count=round(flattening.alternative_count, 1),
            distance=round(distance, 1),
        )

    def _firepower_for(self, distance: float) -> float:
        if self.energy <= LOW_ENERGY_HOLD:
            return 0.8 if distance < 180 else 0.6
        if distance < 170:
            return 1.8
        if distance < 420:
            return 1.0
        return 0.8

    def _can_fire(self, age: int, distance: float, gun_bearing: float, firepower: float) -> tuple[bool, str]:
        decision = FIRE_GATE.decide(age, distance, gun_bearing, firepower, self.energy)
        return decision.can_fire, decision.reason

    def _forget_stale_targets(self) -> None:
        stale_ids = [
            bot_id
            for bot_id, target in self._targets.items()
            if self.turn_number - target.seen_turn > TARGET_MEMORY_TURNS
        ]
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
            self._gun.remove_target(bot_id)
            self._movement.remove_target(bot_id)
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
            self._enemy_energy_corrections.clear()
            self._evade_until_turn = -1
            self._target_accel.clear()
            self._last_velocity_change_turn.clear()
            self._own_motion.reset(self.turn_number)
            self._gun.clear_round_state()
            self._movement.clear_round_state()
            self._minimum_risk.clear_round_state()
            self._log(
                "round.reset",
                previous_turn=self._last_turn_number,
                current_turn=self.turn_number,
            )
        self._last_turn_number = self.turn_number

    def _select_target(self) -> TargetSnapshot | None:
        if not self._targets:
            self._target_id = None
            return None

        previous_id = self._target_id
        candidate = min(self._targets.values(), key=self._target_score)
        target = candidate
        current = self._targets.get(previous_id)
        current_age = self.turn_number - current.seen_turn if current is not None else 999
        if current is not None and candidate.bot_id != current.bot_id and current_age <= FORCE_SWITCH_TARGET_AGE:
            candidate_score = self._target_score(candidate)
            current_score = self._target_score(current)
            if candidate_score + TARGET_SWITCH_MARGIN >= current_score:
                target = current

        self._target_id = target.bot_id
        if previous_id != target.bot_id:
            self._log(
                "target.select",
                previous=previous_id,
                selected=target.bot_id,
                score=round(self._target_score(target), 1),
                candidate=candidate.bot_id,
                candidate_score=round(self._target_score(candidate), 1),
                previous_age=current_age if current is not None else None,
                known_targets=len(self._targets),
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
        current_bonus = CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
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
        self._wall_escape_until_turn = self.turn_number + WALL_ESCAPE_TURNS
        self.set_turn_left(60)
        self._log(
            "hit.wall",
            move_direction=self._move_direction,
            wall_escape_until=self._wall_escape_until_turn,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._targets[event.victim_id] = target_from_hit_bot(event, self.turn_number)
        self._collision_escape_until_turn = self.turn_number + COLLISION_ESCAPE_TURNS
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
        self._log(
            "bullet.hit_bot",
            victim=event.victim_id,
            bullet_id=event.bullet.bullet_id,
            power=round(event.bullet.power, 2),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            **bullet_fields,
        )

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        target = self._targets.get(self._target_id)
        gun_score, gun_visits = self._gun.target_confidence(target.bot_id) if target is not None else (0.0, 0)
        wave = self._gun.record_pending_fire()
        self._movement.record_shadow_bullet(
            self,
            event.bullet.bullet_id,
            event.bullet.power,
            event.bullet.direction,
        )
        bullet_fields = self._fired_bullets.record(
            event.bullet.bullet_id,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
        )
        self._log(
            "bullet.fired",
            bullet_id=event.bullet.bullet_id,
            target=self._target_id,
            power=event.bullet.power,
            direction=round(event.bullet.direction, 1),
            energy=round(self.energy, 1),
            wave=wave is not None,
            gun_waves=self._gun.wave_count,
            shadow_bullets=self._movement.shadow_bullet_count,
            gun_samples=self._gun.sample_count,
            gun_confidence=round(gun_score, 3),
            gun_confidence_visits=gun_visits,
            **bullet_fields,
        )

    def _sample_status(self, event: str, **fields: object) -> None:
        self._debug.sample(event, **fields)

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    CircleStrafer().start()

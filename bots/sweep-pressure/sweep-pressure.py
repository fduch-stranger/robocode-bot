import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BulletFiredEvent,
    BulletHitBotEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_utils.debug import DebugLogger, FiredBulletTracker
from bot_utils.energy import EnergyDropConfig, classify_energy_drop
from bot_utils.gun import TargetMotion, VirtualGunSystem
from bot_utils.movement import MinimumRiskMovement, MovementFlattener
from bot_utils.motion import OwnMotionTracker
from bot_utils.radar import RadarLockConfig, lock_priority_radar
from bot_utils.tank_math import (
    TargetSnapshot,
    body_bearing_to,
    clamp,
    distance_to,
    target_from_scan,
)


FIRE_ALIGNMENT_DEGREES = 8
TARGET_MEMORY_TURNS = 30
FIRE_MEMORY_TURNS = 4
CURRENT_TARGET_BONUS = 160
TARGET_SWITCH_MARGIN = 95
FORCE_SWITCH_TARGET_AGE = 10
ENEMY_FIRE_MIN_DROP = 0.1
ENEMY_FIRE_MAX_DROP = 3.0
ENEMY_FIRE_SCAN_GAP_TURNS = 4
ENEMY_FIRE_CLOSE_COLLISION_DISTANCE = 75
ENEMY_FIRE_CLOSE_COLLISION_MAX_DROP = 0.8
LOW_ENERGY_HOLD = 18
CRITICAL_ENERGY_HOLD = 10
FIELD_MARGIN = 18
WALL_MARGIN = 45
WALL_LOOKAHEAD_TICKS = 12
WALL_ESCAPE_SPEED = 7
SWEEP_SPEED = 7
SWEEP_TURN_RATE = 3.5
FLATTENER_STRAFE_OFFSET = 92
RADAR_SEARCH_RATE = 16
RADAR_LOCK_RATE = 24
RADAR_REACQUIRE_RATE = 24
RADAR_RESCAN_INTERVAL = 30
RADAR_RESCAN_TURNS = 5
RADAR_REACQUIRE_MIN_ERROR = 8
RADAR_LOCK_OVERSCAN = 12
RADAR_REACQUIRE_OVERSCAN = 24
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


class SweepPressure(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Sweep Pressure",
                version="1.0",
                authors=["robocode-bot"],
                description="Basic sweeping ram-pressure bot.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._move_direction = 1
        self._targets: dict[int, TargetSnapshot] = {}
        self._target_id: int | None = None
        self._last_turn_number = -1
        self._enemy_energy_corrections: dict[int, list[tuple[int, float, str]]] = {}
        self._evade_until_turn = -1
        self._target_accel: dict[int, float] = {}
        self._last_velocity_change_turn: dict[int, int] = {}
        self._gun = VirtualGunSystem()
        self._movement = MovementFlattener()
        self._own_motion = OwnMotionTracker()
        self._minimum_risk = MinimumRiskMovement()
        self._debug = DebugLogger(self, "sweep-pressure")
        self._fired_bullets = FiredBulletTracker()

    def run(self) -> None:
        self.body_color = Color.from_rgb(42, 120, 210)
        self.turret_color = Color.from_rgb(12, 64, 144)
        self.radar_color = Color.from_rgb(190, 225, 255)
        self.bullet_color = Color.from_rgb(80, 180, 255)
        self.scan_color = Color.from_rgb(120, 220, 255)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 7

        while self.running:
            self._reset_if_new_round()
            self._own_motion.update(self)
            self._move()
            self._track_target()
            self.go()

    def _move(self) -> None:
        if self._wall_risk():
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

        if len(self._targets) >= 2:
            focus_target = self._targets.get(self._target_id) or self._nearest_target()
            if focus_target is not None:
                decision = self._minimum_risk.choose(self, list(self._targets.values()), focus_target)
                if decision is not None:
                    turn, speed = self._drive_to_destination(decision.x, decision.y, SWEEP_SPEED)
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

        self.target_speed = SWEEP_SPEED * self._move_direction
        self.turn_rate = -SWEEP_TURN_RATE * self._move_direction if self.turn_number <= self._evade_until_turn else SWEEP_TURN_RATE

    def _wall_risk(self) -> bool:
        heading = math.radians(self.direction)
        projected_x = self.x + math.cos(heading) * SWEEP_SPEED * self._move_direction * WALL_LOOKAHEAD_TICKS
        projected_y = self.y + math.sin(heading) * SWEEP_SPEED * self._move_direction * WALL_LOOKAHEAD_TICKS
        return (
            projected_x < WALL_MARGIN
            or projected_x > self.arena_width - WALL_MARGIN
            or projected_y < WALL_MARGIN
            or projected_y > self.arena_height - WALL_MARGIN
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

        movement_wave = self._movement.record_enemy_fire(
            self,
            target_from_scan(event, self.turn_number),
            signal.fire_power or 1.5,
            **self._own_motion.movement_wave_kwargs(self.turn_number),
        )
        active_evasion = not self._wall_risk()
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
            target,
            body_bearing,
            FLATTENER_STRAFE_OFFSET,
            SWEEP_SPEED,
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
            return 0.8 if distance < 220 else 0.6
        if distance < 180:
            return 2.0
        if distance < 360:
            return 1.2
        return 0.8

    def _can_fire(self, age: int, distance: float, gun_bearing: float, firepower: float) -> tuple[bool, str]:
        if age > FIRE_MEMORY_TURNS:
            return False, "stale"
        if self.energy <= CRITICAL_ENERGY_HOLD:
            return False, "critical_energy"
        if self.energy <= LOW_ENERGY_HOLD and distance > 220:
            return False, "low_energy_range"
        alignment_limit = 5 if distance > 360 else FIRE_ALIGNMENT_DEGREES
        if abs(gun_bearing) > alignment_limit:
            return False, "gun_alignment"
        if self.energy <= firepower + 6:
            return False, "energy_margin"
        return True, "ready"

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
            self._move_direction = 1
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
        absolute_bearing = math.degrees(math.atan2(y - self.y, x - self.x))
        turn = ((absolute_bearing - self.direction + 180) % 360) - 180
        target_speed = speed
        if turn > 90:
            turn -= 180
            target_speed = -speed
        elif turn < -90:
            turn += 180
            target_speed = -speed
        self.target_speed = target_speed
        self.set_turn_left(turn)
        return turn, target_speed

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = distance_to(self, target.x, target.y)
        age = self.turn_number - target.seen_turn
        current_bonus = CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
        return distance * 0.45 + target.energy * 2.0 + age * 80 - current_bonus

    def _record_enemy_energy_correction(self, target_id: int, correction: float, reason: str) -> None:
        corrections = self._enemy_energy_corrections.setdefault(target_id, [])
        corrections.append((self.turn_number, correction, reason))
        if len(corrections) > 8:
            del corrections[: len(corrections) - 8]

    def _consume_enemy_energy_correction(self, target_id: int, current_turn: int, after_turn: int) -> float:
        corrections = self._enemy_energy_corrections.get(target_id)
        if not corrections:
            return 0.0

        correction = 0.0
        remaining: list[tuple[int, float, str]] = []
        for turn, value, reason in corrections:
            if turn > current_turn:
                remaining.append((turn, value, reason))
            elif turn > after_turn:
                correction += value

        if remaining:
            self._enemy_energy_corrections[target_id] = remaining
        else:
            self._enemy_energy_corrections.pop(target_id, None)
        return correction

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(35)
        self._log("hit.wall", move_direction=self._move_direction)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._wall_risk():
            self._move_direction *= -1
        self.set_turn_left(25 * self._move_direction)
        self._log(
            "hit.bullet",
            owner=event.bullet.owner_id,
            power=round(event.bullet.power, 2),
            bullet_direction=round(event.bullet.direction, 1),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            wall_risk=self._wall_risk(),
            move_direction=self._move_direction,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._move_direction *= -1
        self._log(
            "hit.bot",
            target=event.victim_id,
            energy=round(event.energy, 1),
            rammed=event.rammed,
            move_direction=self._move_direction,
        )

    def on_bullet_hit(self, event: BulletHitBotEvent) -> None:
        self._record_enemy_energy_correction(event.victim_id, event.damage, "our_bullet_damage")
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
    SweepPressure().start()

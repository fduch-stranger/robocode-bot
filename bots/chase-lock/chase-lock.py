import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    BulletFiredEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_utils.debug import DebugLogger
from bot_utils.gun import TargetMotion, VirtualGunSystem
from bot_utils.radar import RadarLockConfig, lock_radar_to_target
from bot_utils.tank_math import (
    TargetSnapshot,
    bearing_to,
    clamp,
    distance_to,
    target_from_hit_bot,
    target_from_scan,
)


FIRE_ALIGNMENT_DEGREES = 7
TARGET_MEMORY_TURNS = 24
FIRE_MEMORY_TURNS = 1
REACQUIRE_TARGET_TURNS = 4
DROP_LOST_TARGET_TURNS = 9
CHASE_DISTANCE = 210
RETREAT_DISTANCE = 115
ENEMY_FIRE_MIN_DROP = 0.1
ENEMY_FIRE_MAX_DROP = 3.0
RADAR_LOCK_RATE = 24
RADAR_SEARCH_RATE = 18
RADAR_REACQUIRE_RATE = 24
RADAR_LOST_SWEEP_RATE = 24
GUN_SEARCH_RATE = 18
RADAR_REACQUIRE_MIN_ERROR = 8
RADAR_REACQUIRE_OVERSHOOT = 8
RADAR_REACQUIRE_WIDEN_PER_TURN = 2
RADAR_REACQUIRE_MAX_OVERSHOOT = 42
RADAR_LOCK_OVERSCAN = 12
RADAR_VISIBLE_REACQUIRE_OVERSCAN = 18
CURRENT_TARGET_BONUS = 80
RECENT_THREAT_BONUS = 120
THREAT_MEMORY_TURNS = 35
FIELD_MARGIN = 18
WALL_MARGIN = 90
WALL_LOOKAHEAD_TICKS = 11
WALL_ESCAPE_SPEED = 6
CHASE_STRAFE_OFFSET = 48
EVADE_STRAFE_OFFSET = 88
RETREAT_STRAFE_OFFSET = 120
EVADE_TURNS = 36
RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_SEARCH_RATE,
    lock_rate=RADAR_LOCK_RATE,
    reacquire_rate=RADAR_REACQUIRE_RATE,
    reacquire_min_error=RADAR_REACQUIRE_MIN_ERROR,
    lock_overscan=RADAR_LOCK_OVERSCAN,
    reacquire_overscan=RADAR_VISIBLE_REACQUIRE_OVERSCAN,
)


class ChaseLock(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Chase Lock",
                version="1.0",
                authors=["robocode-bot"],
                description="Locks radar and gun to the latest scan, then chases the target.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._targets: dict[int, TargetSnapshot] = {}
        self._target_id: int | None = None
        self._recent_threat_id: int | None = None
        self._recent_threat_turn = -1000
        self._evade_direction = 1
        self._evade_until_turn = -1
        self._radar_sweep_direction = 1
        self._last_turn_number = -1
        self._last_enemy_fire_turn = -1000
        self._last_enemy_fire_power = 0.0
        self._target_accel: dict[int, float] = {}
        self._last_velocity_change_turn: dict[int, int] = {}
        self._gun = VirtualGunSystem()
        self._debug = DebugLogger(self, "chase-lock")

    def run(self) -> None:
        self.body_color = Color.from_rgb(70, 170, 105)
        self.turret_color = Color.from_rgb(26, 105, 62)
        self.radar_color = Color.from_rgb(185, 255, 205)
        self.bullet_color = Color.from_rgb(110, 255, 145)
        self.scan_color = Color.from_rgb(165, 255, 200)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 8

        while self.running:
            self._track_or_search()
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        self._reset_if_new_round()
        previous = self._targets.get(event.scanned_bot_id)
        previous_age = self.turn_number - previous.seen_turn if previous is not None else None
        if previous is not None:
            self._update_target_motion_stats(event, previous)
            self._detect_enemy_fire(event, previous)
        self._targets[event.scanned_bot_id] = target_from_scan(event, self.turn_number)
        self._log_wave_visits(self._targets[event.scanned_bot_id])
        if previous is None:
            self._log(
                "scan.new",
                bot_id=event.scanned_bot_id,
                energy=round(event.energy, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )
        elif previous_age is not None and previous_age > REACQUIRE_TARGET_TURNS:
            self._log(
                "scan.reacquired",
                bot_id=event.scanned_bot_id,
                previous_age=previous_age,
                previous_x=round(previous.x, 1),
                previous_y=round(previous.y, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )

    def _update_target_motion_stats(self, event: ScannedBotEvent, previous: TargetSnapshot) -> None:
        speed_delta = event.speed - previous.speed
        self._target_accel[event.scanned_bot_id] = speed_delta
        direction_delta = abs(((event.direction - previous.direction + 180) % 360) - 180)
        if abs(speed_delta) > 0.35 or direction_delta > 7:
            self._last_velocity_change_turn[event.scanned_bot_id] = self.turn_number

    def _detect_enemy_fire(self, event: ScannedBotEvent, previous: TargetSnapshot) -> None:
        energy_drop = previous.energy - event.energy
        if not (ENEMY_FIRE_MIN_DROP <= energy_drop <= ENEMY_FIRE_MAX_DROP):
            return

        self._recent_threat_id = event.scanned_bot_id
        self._recent_threat_turn = self.turn_number
        self._last_enemy_fire_turn = self.turn_number
        self._last_enemy_fire_power = energy_drop
        self._log(
            "enemy.fire_detected",
            bot_id=event.scanned_bot_id,
            power=round(energy_drop, 2),
            previous_energy=round(previous.energy, 1),
            energy=round(event.energy, 1),
            evade_direction=self._evade_direction,
        )

    def _track_or_search(self) -> None:
        self._reset_if_new_round()
        self._forget_stale_targets()
        target = self._select_target()
        if target is None:
            self._search()
            self._sample_status("search", known_targets=0)
            return

        distance = distance_to(self, target.x, target.y)
        body_bearing = bearing_to(self, target.x, target.y, self.direction)
        radar_bearing = bearing_to(self, target.x, target.y, self.radar_direction)
        firepower = self._select_firepower(target, distance)
        aim = self._gun.aim(self, target, distance, firepower, self._target_motion(target), FIELD_MARGIN)
        if aim.mode_changed:
            self._log(
                "gun.switch",
                target=target.bot_id,
                previous=aim.previous_mode,
                selected=aim.mode,
                scores=self._gun.score_summary(target.bot_id),
            )
        age = self.turn_number - target.seen_turn

        if age > REACQUIRE_TARGET_TURNS:
            if age > DROP_LOST_TARGET_TURNS:
                self._drop_lost_target(target, age, distance)
                return

            radar_turn, radar_mode = self._set_lost_target_radar(radar_bearing, age)
            self._set_gun_for_search()
            self._set_search_movement()
            self._sample_status(
                "target.reacquire",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                radar_bearing=round(radar_bearing, 2),
                radar_direction=round(self.radar_direction, 2),
                radar_turn=round(radar_turn, 2),
                radar_mode=radar_mode,
                radar_sweep=self._radar_sweep_direction,
                x=round(self.x, 1),
                y=round(self.y, 1),
                known_targets=len(self._targets),
            )
            return

        radar_command = lock_radar_to_target(self, target, RADAR_CONFIG)
        if abs(radar_command.turn) >= 1:
            self._radar_sweep_direction = 1 if radar_command.turn > 0 else -1
        self.set_turn_gun_left(aim.gun_bearing)

        if self._wall_risk(8):
            center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
            self.target_speed = WALL_ESCAPE_SPEED
            self.set_turn_left(clamp(center_bearing, -35, 35))
            self._sample_status(
                "wall.avoid",
                x=round(self.x, 1),
                y=round(self.y, 1),
                center_bearing=round(center_bearing, 2),
                target=target.bot_id,
            )
        else:
            movement_mode, strafe_offset = self._set_chase_movement(distance, body_bearing)

        if (
            age <= FIRE_MEMORY_TURNS
            and abs(aim.gun_bearing) <= FIRE_ALIGNMENT_DEGREES
            and self.energy > firepower + 5
        ):
            self._gun.set_pending_wave(self._gun.make_wave(self, target, firepower, aim))
            self.set_fire(firepower)
        else:
            self._sample_status(
                "track",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                gun_bearing=round(aim.gun_bearing, 2),
                radar_bearing=round(radar_command.bearing, 2),
                radar_turn=round(radar_command.turn, 2),
                radar_mode=radar_command.mode,
                radar_age=radar_command.age,
                predicted_x=round(aim.predicted_x, 1),
                predicted_y=round(aim.predicted_y, 1),
                aim_mode=aim.mode,
                aim_guess_factor=round(aim.guess_factor, 3) if aim.guess_factor is not None else None,
                gun_samples=self._gun.sample_count,
                gun_scores=self._gun.score_summary(target.bot_id),
                evade_direction=self._evade_direction,
                evading=self.turn_number <= self._evade_until_turn,
                movement_mode=movement_mode if "movement_mode" in locals() else "wall",
                strafe_offset=round(strafe_offset, 1) if "strafe_offset" in locals() else None,
                last_enemy_fire_age=self.turn_number - self._last_enemy_fire_turn,
                known_targets=len(self._targets),
            )

    def _set_chase_movement(
        self,
        distance: float,
        body_bearing: float,
    ) -> tuple[str, float]:
        evading = self.turn_number <= self._evade_until_turn
        if distance < RETREAT_DISTANCE:
            self.target_speed = -6
            self.set_turn_left(body_bearing + RETREAT_STRAFE_OFFSET * self._evade_direction)
            return "panic_retreat", RETREAT_STRAFE_OFFSET

        strafe_offset = EVADE_STRAFE_OFFSET if evading else CHASE_STRAFE_OFFSET
        if distance > CHASE_DISTANCE:
            self.target_speed = 8
            self.set_turn_left(body_bearing + strafe_offset * self._evade_direction)
            return "close_lateral", strafe_offset

        self.target_speed = 6 if evading else 5
        self.set_turn_left(body_bearing + strafe_offset * self._evade_direction)
        return "chase_orbit", strafe_offset

    def _select_firepower(self, target: TargetSnapshot, distance: float) -> float:
        return 2.0 if distance < 220 else 1.2

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

    def _set_lost_target_radar(self, radar_bearing: float, age: int) -> tuple[float, str]:
        if abs(radar_bearing) > RADAR_REACQUIRE_MIN_ERROR:
            overshoot = min(
                RADAR_REACQUIRE_MAX_OVERSHOOT,
                RADAR_REACQUIRE_OVERSHOOT + age * RADAR_REACQUIRE_WIDEN_PER_TURN,
            )
            direction = 1 if radar_bearing > 0 else -1
            radar_turn = clamp(
                radar_bearing + overshoot * direction,
                -RADAR_LOST_SWEEP_RATE,
                RADAR_LOST_SWEEP_RATE,
            )
            self._radar_sweep_direction = direction
            self.set_turn_radar_left(radar_turn)
            return radar_turn, "cached_bearing"

        radar_turn = RADAR_LOST_SWEEP_RATE * self._radar_sweep_direction
        self.set_turn_radar_left(radar_turn)
        return radar_turn, "widen"

    def _sample_status(self, event: str, **fields: object) -> None:
        self._debug.sample(event, **fields)

    def _reset_if_new_round(self) -> None:
        if self._last_turn_number >= 0 and self.turn_number < self._last_turn_number:
            self._targets.clear()
            self._target_id = None
            self._recent_threat_id = None
            self._recent_threat_turn = -1000
            self._evade_until_turn = -1
            self._last_enemy_fire_turn = -1000
            self._last_enemy_fire_power = 0.0
            self._gun.clear_round_state()
            self._target_accel.clear()
            self._last_velocity_change_turn.clear()
            self._log(
                "round.reset",
                previous_turn=self._last_turn_number,
                current_turn=self.turn_number,
            )
        self._last_turn_number = self.turn_number

    def _drop_lost_target(self, target: TargetSnapshot, age: int, distance: float) -> None:
        self._targets.pop(target.bot_id, None)
        if self._target_id == target.bot_id:
            self._target_id = None
        self._search()
        self._log(
            "target.drop_lost",
            bot_id=target.bot_id,
            age=age,
            cached_x=round(target.x, 1),
            cached_y=round(target.y, 1),
            cached_distance=round(distance, 1),
            known_targets=len(self._targets),
        )

    def _forget_stale_targets(self) -> None:
        stale_ids = [
            bot_id
            for bot_id, target in self._targets.items()
            if self.turn_number - target.seen_turn > TARGET_MEMORY_TURNS
        ]
        for bot_id in stale_ids:
            self._log("target.stale", bot_id=bot_id)
            del self._targets[bot_id]
        if self._target_id not in self._targets:
            self._target_id = None

    def _select_target(self) -> TargetSnapshot | None:
        if not self._targets:
            self._target_id = None
            return None

        previous_id = self._target_id
        fresh_targets = [
            target
            for target in self._targets.values()
            if self.turn_number - target.seen_turn <= REACQUIRE_TARGET_TURNS
        ]
        candidates = fresh_targets if fresh_targets else list(self._targets.values())
        target = min(candidates, key=self._target_score)
        self._target_id = target.bot_id
        if previous_id != target.bot_id:
            self._log(
                "target.select",
                previous=previous_id,
                selected=target.bot_id,
                score=round(self._target_score(target), 1),
                fresh_candidates=len(fresh_targets),
                known_targets=len(self._targets),
            )
        return target

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = distance_to(self, target.x, target.y)
        age = self.turn_number - target.seen_turn
        current_bonus = CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
        recent_threat_bonus = (
            RECENT_THREAT_BONUS
            if target.bot_id == self._recent_threat_id
            and self.turn_number - self._recent_threat_turn <= THREAT_MEMORY_TURNS
            else 0
        )
        return distance * 0.7 + target.energy * 2.5 + age * 60 - current_bonus - recent_threat_bonus

    def _search(self) -> None:
        self._set_search_movement()
        self._set_gun_for_search()
        self.radar_turn_rate = RADAR_SEARCH_RATE

    def _set_gun_for_search(self) -> None:
        gun_to_radar = ((self.radar_direction - self.gun_direction + 180) % 360) - 180
        if abs(gun_to_radar) > 5:
            self.set_turn_gun_left(clamp(gun_to_radar, -GUN_SEARCH_RATE, GUN_SEARCH_RATE))
        else:
            self.gun_turn_rate = GUN_SEARCH_RATE * self._radar_sweep_direction

    def _set_search_movement(self) -> None:
        if self._near_wall() or self._wall_risk(6):
            center_bearing = bearing_to(self, self.arena_width / 2, self.arena_height / 2, self.direction)
            self.target_speed = WALL_ESCAPE_SPEED
            self.set_turn_left(clamp(center_bearing, -35, 35))
            self._sample_status(
                "search.wall_avoid",
                x=round(self.x, 1),
                y=round(self.y, 1),
                center_bearing=round(center_bearing, 2),
                evade_direction=self._evade_direction,
                near_wall=self._near_wall(),
            )
            return

        self.target_speed = 4 * self._evade_direction
        self.turn_rate = 3 * self._evade_direction

    def _wall_risk(self, speed: float) -> bool:
        heading = math.radians(self.direction)
        projected_x = self.x + math.cos(heading) * speed * WALL_LOOKAHEAD_TICKS
        projected_y = self.y + math.sin(heading) * speed * WALL_LOOKAHEAD_TICKS
        return (
            projected_x < WALL_MARGIN
            or projected_x > self.arena_width - WALL_MARGIN
            or projected_y < WALL_MARGIN
            or projected_y > self.arena_height - WALL_MARGIN
        )

    def _near_wall(self) -> bool:
        return (
            self.x < WALL_MARGIN
            or self.x > self.arena_width - WALL_MARGIN
            or self.y < WALL_MARGIN
            or self.y > self.arena_height - WALL_MARGIN
        )

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        self.set_turn_left(70)
        self._log("hit.wall", evade_direction=self._evade_direction)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._wall_risk(8):
            self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        if event.bullet.owner_id in self._targets:
            self._recent_threat_id = event.bullet.owner_id
            self._recent_threat_turn = self.turn_number
            self._target_id = event.bullet.owner_id
        self._log(
            "hit.bullet",
            owner=event.bullet.owner_id,
            power=round(event.bullet.power, 2),
            bullet_direction=round(event.bullet.direction, 1),
            damage=round(event.damage, 2),
            energy=round(event.energy, 1),
            wall_risk=self._wall_risk(8),
            evade_direction=self._evade_direction,
            evade_until=self._evade_until_turn,
        )

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._targets[event.victim_id] = target_from_hit_bot(event, self.turn_number)
        self._target_id = event.victim_id
        self._evade_direction *= -1
        self._evade_until_turn = self.turn_number + EVADE_TURNS
        self.target_speed = -4
        self._log(
            "hit.bot",
            target=event.victim_id,
            energy=round(event.energy, 1),
            rammed=event.rammed,
            evade_direction=self._evade_direction,
        )

    def on_bot_death(self, event: BotDeathEvent) -> None:
        self._targets.pop(event.victim_id, None)
        self._gun.remove_target(event.victim_id)
        if self._target_id == event.victim_id:
            self._target_id = None
        self._log("target.dead", bot_id=event.victim_id)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        target = self._targets.get(self._target_id)
        target_age = self.turn_number - target.seen_turn if target is not None else None
        wave = self._gun.record_pending_fire()
        self._log(
            "bullet.fired",
            bullet_id=event.bullet.bullet_id,
            target=self._target_id,
            target_age=target_age,
            target_x=round(target.x, 1) if target is not None else None,
            target_y=round(target.y, 1) if target is not None else None,
            power=event.bullet.power,
            direction=round(event.bullet.direction, 1),
            energy=round(self.energy, 1),
            gun_waves=self._gun.wave_count,
            gun_samples=self._gun.sample_count,
            aim_mode=wave.aim_mode if wave is not None else None,
            aim_guess_factor=round(wave.aim_guess_factor, 3)
            if wave is not None and wave.aim_guess_factor is not None
            else None,
        )

    def _log(self, event: str, **fields: object) -> None:
        self._debug.log(event, **fields)

if __name__ == "__main__":
    ChaseLock().start()

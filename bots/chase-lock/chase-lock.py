import math
import os
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    BulletFiredEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_utils.tank_math import TargetSnapshot, bearing_to, clamp, distance_to, predicted_position


FIRE_ALIGNMENT_DEGREES = 7
TARGET_MEMORY_TURNS = 24
FIRE_MEMORY_TURNS = 1
REACQUIRE_TARGET_TURNS = 4
CHASE_DISTANCE = 140
RETREAT_DISTANCE = 75
RADAR_LOCK_RATE = 24
RADAR_SEARCH_RATE = 18
RADAR_REACQUIRE_RATE = 24
RADAR_LOST_SWEEP_RATE = 24
RADAR_REACQUIRE_MIN_ERROR = 8
CURRENT_TARGET_BONUS = 80
RECENT_THREAT_BONUS = 120
THREAT_MEMORY_TURNS = 35
FIELD_MARGIN = 18
WALL_MARGIN = 90
WALL_LOOKAHEAD_TICKS = 11
WALL_ESCAPE_SPEED = 6
CHASE_STRAFE_OFFSET = 30
EVADE_STRAFE_OFFSET = 58
RETREAT_STRAFE_OFFSET = 105
EVADE_TURNS = 28


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
        self._debug_log = self._open_debug_log()
        self._last_status_turn = -1

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
        previous = self._targets.get(event.scanned_bot_id)
        self._targets[event.scanned_bot_id] = TargetSnapshot(
            bot_id=event.scanned_bot_id,
            energy=event.energy,
            x=event.x,
            y=event.y,
            direction=event.direction,
            speed=event.speed,
            seen_turn=self.turn_number,
        )
        if previous is None:
            self._log(
                "scan.new",
                bot_id=event.scanned_bot_id,
                energy=round(event.energy, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )

    def _track_or_search(self) -> None:
        self._forget_stale_targets()
        target = self._select_target()
        if target is None:
            self._search()
            if self.turn_number - self._last_status_turn >= 25:
                self._log("search", known_targets=0)
                self._last_status_turn = self.turn_number
            return

        distance = distance_to(self, target.x, target.y)
        body_bearing = bearing_to(self, target.x, target.y, self.direction)
        radar_bearing = bearing_to(self, target.x, target.y, self.radar_direction)
        firepower = 2.0 if distance < 220 else 1.2
        predicted_x, predicted_y = predicted_position(self, target, firepower, FIELD_MARGIN)
        gun_bearing = bearing_to(self, predicted_x, predicted_y, self.gun_direction)
        age = self.turn_number - target.seen_turn

        if age > REACQUIRE_TARGET_TURNS:
            self._set_lost_target_radar()
            self.set_turn_gun_left(gun_bearing)
            self._set_search_movement()
            self._sample_status(
                "target.reacquire",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                radar_bearing=round(radar_bearing, 2),
                radar_direction=round(self.radar_direction, 2),
                radar_sweep=self._radar_sweep_direction,
                x=round(self.x, 1),
                y=round(self.y, 1),
                known_targets=len(self._targets),
            )
            return

        self._set_radar_for_target(radar_bearing, age)
        self.set_turn_gun_left(gun_bearing)

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
        elif distance < RETREAT_DISTANCE:
            self.target_speed = -6
            self.set_turn_left(body_bearing + RETREAT_STRAFE_OFFSET * self._evade_direction)
        else:
            evading = self.turn_number <= self._evade_until_turn
            strafe_offset = EVADE_STRAFE_OFFSET if evading else CHASE_STRAFE_OFFSET
            self.target_speed = 8 if distance > CHASE_DISTANCE else 4
            self.set_turn_left(body_bearing + strafe_offset * self._evade_direction)

        if (
            age <= FIRE_MEMORY_TURNS
            and abs(gun_bearing) <= FIRE_ALIGNMENT_DEGREES
            and self.energy > firepower + 5
        ):
            self.set_fire(firepower)
        elif self.turn_number - self._last_status_turn >= 25:
            self._log(
                "track",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                gun_bearing=round(gun_bearing, 2),
                radar_bearing=round(radar_bearing, 2),
                predicted_x=round(predicted_x, 1),
                predicted_y=round(predicted_y, 1),
                evade_direction=self._evade_direction,
                evading=self.turn_number <= self._evade_until_turn,
                known_targets=len(self._targets),
            )
            self._last_status_turn = self.turn_number

    def _set_radar_for_target(self, radar_bearing: float, age: int) -> None:
        if age <= 1:
            radar_turn = clamp(radar_bearing * 1.8, -RADAR_LOCK_RATE, RADAR_LOCK_RATE)
            if abs(radar_turn) >= 1:
                self._radar_sweep_direction = 1 if radar_turn > 0 else -1
            self.set_turn_radar_left(radar_turn)
            return

        if abs(radar_bearing) > RADAR_REACQUIRE_MIN_ERROR:
            radar_turn = clamp(radar_bearing * 1.8, -RADAR_REACQUIRE_RATE, RADAR_REACQUIRE_RATE)
            self._radar_sweep_direction = 1 if radar_turn > 0 else -1
        else:
            radar_turn = RADAR_REACQUIRE_RATE * self._radar_sweep_direction
        self.set_turn_radar_left(radar_turn)

    def _set_lost_target_radar(self) -> None:
        self.radar_turn_rate = RADAR_LOST_SWEEP_RATE * self._radar_sweep_direction

    def _sample_status(self, event: str, **fields: object) -> None:
        if self.turn_number - self._last_status_turn < 25:
            return
        self._log(event, **fields)
        self._last_status_turn = self.turn_number

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
        target = min(self._targets.values(), key=self._target_score)
        self._target_id = target.bot_id
        if previous_id != target.bot_id:
            self._log(
                "target.select",
                previous=previous_id,
                selected=target.bot_id,
                score=round(self._target_score(target), 1),
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
        self.gun_turn_rate = 0
        self.radar_turn_rate = RADAR_SEARCH_RATE

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
        self._targets[event.victim_id] = TargetSnapshot(
            bot_id=event.victim_id,
            energy=event.energy,
            x=event.x,
            y=event.y,
            direction=0,
            speed=0,
            seen_turn=self.turn_number,
        )
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
        if self._target_id == event.victim_id:
            self._target_id = None
        self._log("target.dead", bot_id=event.victim_id)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        self._log(
            "bullet.fired",
            bullet_id=event.bullet.bullet_id,
            target=self._target_id,
            power=event.bullet.power,
            direction=round(event.bullet.direction, 1),
            energy=round(self.energy, 1),
        )

    def _open_debug_log(self) -> TextIO | None:
        if os.environ.get("ROBOCODE_DEBUG") != "1":
            return None
        log_dir = Path(os.environ.get("ROBOCODE_LOG_DIR", "."))
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / f"chase-lock-{os.getpid()}.log").open("w", encoding="utf-8")

    def _log(self, event: str, **fields: object) -> None:
        if self._debug_log is None:
            return
        payload = " ".join(f"{key}={value}" for key, value in fields.items())
        self._debug_log.write(f"turn={self.turn_number} event={event} {payload}\n")
        self._debug_log.flush()

if __name__ == "__main__":
    ChaseLock().start()

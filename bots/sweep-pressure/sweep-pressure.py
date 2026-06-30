import math
import os
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BulletFiredEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)

from bot_utils.tank_math import (
    TargetSnapshot,
    body_bearing_to,
    clamp,
    distance_to,
    gun_bearing_to,
    predicted_position,
)


FIRE_ALIGNMENT_DEGREES = 8
TARGET_MEMORY_TURNS = 30
FIRE_MEMORY_TURNS = 4
CURRENT_TARGET_BONUS = 160
LOW_ENERGY_HOLD = 18
CRITICAL_ENERGY_HOLD = 10
FIELD_MARGIN = 18
WALL_MARGIN = 45
WALL_LOOKAHEAD_TICKS = 12
WALL_ESCAPE_SPEED = 7
SWEEP_SPEED = 7
SWEEP_TURN_RATE = 3.5


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
        self._debug_log = self._open_debug_log()
        self._last_status_turn = -1

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
            self._move()
            self._track_target()
            self.radar_turn_rate = 14
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

        self.target_speed = SWEEP_SPEED * self._move_direction
        self.turn_rate = SWEEP_TURN_RATE

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

    def _track_target(self) -> None:
        self._forget_stale_targets()
        target = self._select_target()
        if target is None:
            self.gun_turn_rate = 0
            self._sample_status("search", known_targets=0)
            return

        distance = distance_to(self, target.x, target.y)
        firepower = self._firepower_for(distance)
        predicted_x, predicted_y = predicted_position(self, target, firepower, FIELD_MARGIN)
        gun_bearing = gun_bearing_to(self, predicted_x, predicted_y)
        age = self.turn_number - target.seen_turn

        self.set_turn_gun_left(gun_bearing)
        can_fire, hold_reason = self._can_fire(age, distance, gun_bearing, firepower)
        if (
            can_fire
        ):
            self.set_fire(firepower)
        else:
            self._sample_status(
                "track",
                target=target.bot_id,
                age=age,
                distance=round(distance, 1),
                gun_bearing=round(gun_bearing, 2),
                firepower=firepower,
                hold_reason=hold_reason,
                predicted_x=round(predicted_x, 1),
                predicted_y=round(predicted_y, 1),
                known_targets=len(self._targets),
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
        return distance * 0.45 + target.energy * 2.0 + age * 80 - current_bonus

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(35)
        self._log("hit.wall", move_direction=self._move_direction)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._wall_risk():
            self._move_direction *= -1
        self.set_turn_left(25 * self._move_direction)
        self._log("hit.bullet", wall_risk=self._wall_risk(), move_direction=self._move_direction)

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._move_direction *= -1
        self._log(
            "hit.bot",
            target=event.victim_id,
            energy=round(event.energy, 1),
            rammed=event.rammed,
            move_direction=self._move_direction,
        )

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        self._log(
            "bullet.fired",
            bullet_id=event.bullet.bullet_id,
            target=self._target_id,
            power=event.bullet.power,
            direction=round(event.bullet.direction, 1),
            energy=round(self.energy, 1),
        )

    def _sample_status(self, event: str, **fields: object) -> None:
        if self.turn_number - self._last_status_turn < 25:
            return
        self._log(event, **fields)
        self._last_status_turn = self.turn_number

    def _open_debug_log(self) -> TextIO | None:
        if os.environ.get("ROBOCODE_DEBUG") != "1":
            return None
        log_dir = Path(os.environ.get("ROBOCODE_LOG_DIR", "."))
        log_dir.mkdir(parents=True, exist_ok=True)
        return (log_dir / f"sweep-pressure-{os.getpid()}.log").open("w", encoding="utf-8")

    def _log(self, event: str, **fields: object) -> None:
        if self._debug_log is None:
            return
        payload = " ".join(f"{key}={value}" for key, value in fields.items())
        self._debug_log.write(f"turn={self.turn_number} event={event} {payload}\n")
        self._debug_log.flush()

if __name__ == "__main__":
    SweepPressure().start()

import math
import os
from pathlib import Path
from typing import TextIO

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import BulletFiredEvent, HitBotEvent, HitWallEvent, ScannedBotEvent


FIRE_ALIGNMENT_DEGREES = 8
TARGET_MEMORY_TURNS = 12


def gun_bearing_to(bot: Bot, x: float, y: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - bot.gun_direction + 180) % 360) - 180


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
        self._target_id: int | None = None
        self._target_x: float | None = None
        self._target_y: float | None = None
        self._target_turn = -1
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
            self.target_speed = 7 * self._move_direction
            self.turn_rate = 3.5
            self._track_scanned_target()
            self.radar_turn_rate = 14
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        previous_id = self._target_id
        self._target_id = event.scanned_bot_id
        self._target_x = event.x
        self._target_y = event.y
        self._target_turn = self.turn_number
        if previous_id != event.scanned_bot_id:
            self._log(
                "target.select",
                previous=previous_id,
                selected=event.scanned_bot_id,
                energy=round(event.energy, 1),
                x=round(event.x, 1),
                y=round(event.y, 1),
            )

    def _track_scanned_target(self) -> None:
        if self._target_x is None or self._target_y is None:
            self.gun_turn_rate = 0
            self._sample_status("search", known_target=False)
            return
        if self.turn_number - self._target_turn > TARGET_MEMORY_TURNS:
            self.gun_turn_rate = 0
            self._sample_status("target.stale", target=self._target_id)
            return

        dx = self._target_x - self.x
        dy = self._target_y - self.y
        gun_bearing = gun_bearing_to(self, self._target_x, self._target_y)
        distance = math.hypot(dx, dy)
        firepower = 2.5 if distance < 250 else 1.5

        self.set_turn_gun_left(gun_bearing)
        if abs(gun_bearing) <= FIRE_ALIGNMENT_DEGREES and self.energy > firepower + 1:
            self.set_fire(firepower)
        else:
            self._sample_status(
                "track",
                target=self._target_id,
                distance=round(distance, 1),
                gun_bearing=round(gun_bearing, 2),
            )

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(35)
        self._log("hit.wall", move_direction=self._move_direction)

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

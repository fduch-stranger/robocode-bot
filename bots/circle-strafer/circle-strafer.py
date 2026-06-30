import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import HitBotEvent, HitByBulletEvent, HitWallEvent, ScannedBotEvent


FIRE_ALIGNMENT_DEGREES = 8
TARGET_MEMORY_TURNS = 12


def gun_bearing_to(bot: Bot, x: float, y: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - bot.gun_direction + 180) % 360) - 180


class CircleStrafer(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Circle Strafer",
                version="1.0",
                authors=["robocode-bot"],
                description="Basic evasive circle-strafer bot.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._move_direction = 1
        self._target_x: float | None = None
        self._target_y: float | None = None
        self._target_turn = -1

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
            self.target_speed = 8 * self._move_direction
            self.turn_rate = 6 * self._move_direction
            self._track_scanned_target()
            self.radar_turn_rate = -16
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        self._target_x = event.x
        self._target_y = event.y
        self._target_turn = self.turn_number

    def _track_scanned_target(self) -> None:
        if self._target_x is None or self._target_y is None:
            self.gun_turn_rate = 0
            return
        if self.turn_number - self._target_turn > TARGET_MEMORY_TURNS:
            self.gun_turn_rate = 0
            return

        dx = self._target_x - self.x
        dy = self._target_y - self.y
        gun_bearing = gun_bearing_to(self, self._target_x, self._target_y)
        distance = math.hypot(dx, dy)
        firepower = 3.0 if distance < 180 else 1.0

        self.set_turn_gun_left(gun_bearing)
        if abs(gun_bearing) <= FIRE_ALIGNMENT_DEGREES and self.energy > firepower + 1:
            self.set_fire(firepower)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(45)

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(60)

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._move_direction *= -1


if __name__ == "__main__":
    CircleStrafer().start()

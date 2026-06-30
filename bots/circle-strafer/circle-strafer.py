import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import HitBotEvent, HitByBulletEvent, HitWallEvent, ScannedBotEvent


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
            self.gun_turn_rate = -16
            self.radar_turn_rate = -45
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        dx = event.x - self.x
        dy = event.y - self.y
        self.set_turn_gun_left(gun_bearing_to(self, event.x, event.y))

        distance = math.hypot(dx, dy)
        firepower = 3.0 if distance < 180 else 1.0
        if self.energy > firepower + 1:
            self.set_fire(firepower)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(45)

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(60)

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._move_direction *= -1
        if self.energy > 2:
            self.set_fire(2)


if __name__ == "__main__":
    CircleStrafer().start()

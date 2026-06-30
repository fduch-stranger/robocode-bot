import math

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import HitBotEvent, HitWallEvent, ScannedBotEvent


def gun_bearing_to(bot: Bot, x: float, y: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - bot.gun_direction + 180) % 360) - 180


class TestBot1(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="test-bot-1",
                version="1.0",
                authors=["robocode-bot"],
                description="Basic sweeping ram-pressure bot.",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self._move_direction = 1

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
            self.gun_turn_rate = 14
            self.radar_turn_rate = 45
            self.go()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        dx = event.x - self.x
        dy = event.y - self.y
        self.set_turn_gun_left(gun_bearing_to(self, event.x, event.y))

        distance = math.hypot(dx, dy)
        firepower = 2.5 if distance < 250 else 1.5
        if self.energy > firepower + 1:
            self.set_fire(firepower)

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._move_direction *= -1
        self.set_turn_left(35)

    def on_hit_bot(self, event: HitBotEvent) -> None:
        self._move_direction *= -1
        if self.energy > 3:
            self.set_fire(3)


if __name__ == "__main__":
    TestBot1().start()

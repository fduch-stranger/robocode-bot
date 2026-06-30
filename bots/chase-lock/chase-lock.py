import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    BotDeathEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
)


FIRE_ALIGNMENT_DEGREES = 7
TARGET_MEMORY_TURNS = 24
CHASE_DISTANCE = 140
RETREAT_DISTANCE = 75
RADAR_LOCK_RATE = 24
RADAR_SEARCH_RATE = 18
CURRENT_TARGET_BONUS = 80


@dataclass
class TargetSnapshot:
    bot_id: int
    energy: float
    x: float
    y: float
    direction: float
    speed: float
    seen_turn: int


def bearing_to(bot: Bot, x: float, y: float, direction: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - direction + 180) % 360) - 180


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
        self._evade_direction = 1

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
        self._targets[event.scanned_bot_id] = TargetSnapshot(
            bot_id=event.scanned_bot_id,
            energy=event.energy,
            x=event.x,
            y=event.y,
            direction=event.direction,
            speed=event.speed,
            seen_turn=self.turn_number,
        )

    def _track_or_search(self) -> None:
        self._forget_stale_targets()
        target = self._select_target()
        if target is None:
            self._search()
            return

        dx = target.x - self.x
        dy = target.y - self.y
        distance = math.hypot(dx, dy)
        body_bearing = bearing_to(self, target.x, target.y, self.direction)
        gun_bearing = bearing_to(self, target.x, target.y, self.gun_direction)
        radar_bearing = bearing_to(self, target.x, target.y, self.radar_direction)

        self.set_turn_radar_left(clamp(radar_bearing * 1.8, -RADAR_LOCK_RATE, RADAR_LOCK_RATE))
        self.set_turn_gun_left(gun_bearing)

        if distance < RETREAT_DISTANCE:
            self.target_speed = -5
            self.set_turn_left(body_bearing)
        else:
            self.target_speed = 8 if distance > CHASE_DISTANCE else 3
            self.set_turn_left(body_bearing)

        if abs(gun_bearing) <= FIRE_ALIGNMENT_DEGREES and self.energy > 2:
            firepower = 2.4 if distance < 220 else 1.2
            self.set_fire(firepower)

    def _forget_stale_targets(self) -> None:
        stale_ids = [
            bot_id
            for bot_id, target in self._targets.items()
            if self.turn_number - target.seen_turn > TARGET_MEMORY_TURNS
        ]
        for bot_id in stale_ids:
            del self._targets[bot_id]
        if self._target_id not in self._targets:
            self._target_id = None

    def _select_target(self) -> TargetSnapshot | None:
        if not self._targets:
            self._target_id = None
            return None

        target = min(self._targets.values(), key=self._target_score)
        self._target_id = target.bot_id
        return target

    def _target_score(self, target: TargetSnapshot) -> float:
        distance = math.hypot(target.x - self.x, target.y - self.y)
        age = self.turn_number - target.seen_turn
        current_bonus = CURRENT_TARGET_BONUS if target.bot_id == self._target_id else 0
        return distance * 0.7 + target.energy * 2.5 + age * 60 - current_bonus

    def _search(self) -> None:
        self.target_speed = 4 * self._evade_direction
        self.turn_rate = 3 * self._evade_direction
        self.gun_turn_rate = 0
        self.radar_turn_rate = RADAR_SEARCH_RATE

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._evade_direction *= -1
        self.set_turn_left(70)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        self._evade_direction *= -1

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
        self.target_speed = -4

    def on_bot_death(self, event: BotDeathEvent) -> None:
        self._targets.pop(event.victim_id, None)
        if self._target_id == event.victim_id:
            self._target_id = None


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


if __name__ == "__main__":
    ChaseLock().start()

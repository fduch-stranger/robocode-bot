import math
from collections.abc import Iterable
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot
from robocode_tank_royale.bot_api.events import HitBotEvent, ScannedBotEvent


@dataclass
class TargetSnapshot:
    bot_id: int
    energy: float
    x: float
    y: float
    direction: float
    speed: float
    seen_turn: int


def target_age(turn_number: int, target: TargetSnapshot) -> int:
    return turn_number - target.seen_turn


def oldest_seen_target(targets: Iterable[TargetSnapshot], turn_number: int) -> TargetSnapshot | None:
    oldest: TargetSnapshot | None = None
    oldest_age = -1
    for target in targets:
        age = target_age(turn_number, target)
        if age > oldest_age:
            oldest = target
            oldest_age = age
    return oldest


def target_from_scan(event: ScannedBotEvent, turn_number: int) -> TargetSnapshot:
    return TargetSnapshot(
        bot_id=event.scanned_bot_id,
        energy=event.energy,
        x=event.x,
        y=event.y,
        direction=event.direction,
        speed=event.speed,
        seen_turn=turn_number,
    )


def target_from_hit_bot(event: HitBotEvent, turn_number: int) -> TargetSnapshot:
    return TargetSnapshot(
        bot_id=event.victim_id,
        energy=event.energy,
        x=event.x,
        y=event.y,
        direction=0,
        speed=0,
        seen_turn=turn_number,
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def distance_to(bot: Bot, x: float, y: float) -> float:
    return math.hypot(x - bot.x, y - bot.y)


def bearing_to(bot: Bot, x: float, y: float, direction: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - direction + 180) % 360) - 180


def gun_bearing_to(bot: Bot, x: float, y: float) -> float:
    return bearing_to(bot, x, y, bot.gun_direction)


def body_bearing_to(bot: Bot, x: float, y: float) -> float:
    return bearing_to(bot, x, y, bot.direction)


def predicted_position(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> tuple[float, float]:
    distance = distance_to(bot, target.x, target.y)
    bullet_speed = max(0.1, 20 - 3 * firepower)
    travel_ticks = distance / bullet_speed
    heading = math.radians(target.direction)
    predicted_x = target.x + math.cos(heading) * target.speed * travel_ticks
    predicted_y = target.y + math.sin(heading) * target.speed * travel_ticks
    return (
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
    )

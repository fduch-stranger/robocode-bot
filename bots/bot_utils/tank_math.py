import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot


@dataclass
class TargetSnapshot:
    bot_id: int
    energy: float
    x: float
    y: float
    direction: float
    speed: float
    seen_turn: int


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

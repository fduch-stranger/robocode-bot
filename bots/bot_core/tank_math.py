import math
from collections.abc import Iterable
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot
from robocode_tank_royale.bot_api.events import HitBotEvent, ScannedBotEvent

from bot_core.physics import bullet_speed_for_power


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


def drive_to_destination(bot: Bot, x: float, y: float, speed: float) -> tuple[float, float]:
    absolute_bearing = math.degrees(math.atan2(y - bot.y, x - bot.x))
    turn = ((absolute_bearing - bot.direction + 180) % 360) - 180
    target_speed = speed
    if turn > 90:
        turn -= 180
        target_speed = -speed
    elif turn < -90:
        turn += 180
        target_speed = -speed
    bot.target_speed = target_speed
    bot.set_turn_left(turn)
    return turn, target_speed


def predicted_position(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    field_margin: float,
) -> tuple[float, float]:
    heading = math.radians(target.direction)
    velocity_x = math.cos(heading) * target.speed
    velocity_y = math.sin(heading) * target.speed
    bullet_speed = bullet_speed_for_power(firepower)
    predicted_x = target.x
    predicted_y = target.y
    max_ticks = max(1, min(90, math.ceil(distance_to(bot, target.x, target.y) / max(0.1, bullet_speed)) + 32))

    for tick in range(1, max_ticks + 1):
        predicted_x = clamp(target.x + velocity_x * tick, field_margin, bot.arena_width - field_margin)
        predicted_y = clamp(target.y + velocity_y * tick, field_margin, bot.arena_height - field_margin)
        if bullet_speed * tick >= distance_to(bot, predicted_x, predicted_y):
            break

    return (
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
    )

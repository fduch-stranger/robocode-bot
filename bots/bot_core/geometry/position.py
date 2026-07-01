import math

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.numeric import clamp
from bot_core.physics import bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


def distance_to(bot: Bot, x: float, y: float) -> float:
    return math.hypot(x - bot.x, y - bot.y)


def drive_command_to_destination(bot: Bot, x: float, y: float, speed: float) -> tuple[float, float]:
    absolute_bearing = math.degrees(math.atan2(y - bot.y, x - bot.x))
    turn = ((absolute_bearing - bot.direction + 180) % 360) - 180
    target_speed = speed
    if turn > 90:
        turn -= 180
        target_speed = -speed
    elif turn < -90:
        turn += 180
        target_speed = -speed
    return turn, target_speed


def drive_to_destination(bot: Bot, x: float, y: float, speed: float) -> tuple[float, float]:
    turn, target_speed = drive_command_to_destination(bot, x, y, speed)
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

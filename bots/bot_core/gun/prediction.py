import math

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to
from bot_core.physics import bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


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

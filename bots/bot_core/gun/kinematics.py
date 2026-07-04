import math

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.numeric import clamp
from bot_core.target_snapshot import TargetSnapshot


def lateral_direction(target: TargetSnapshot, absolute_bearing: float) -> int:
    heading = math.radians(target.direction)
    bearing = math.radians(absolute_bearing)
    velocity_x = math.cos(heading) * target.speed
    velocity_y = math.sin(heading) * target.speed
    lateral_velocity = velocity_x * -math.sin(bearing) + velocity_y * math.cos(bearing)
    return 1 if lateral_velocity >= 0 else -1


def point_on_bearing(bot: Bot, aim_bearing: float, distance: float, field_margin: float) -> tuple[float, float]:
    aim_radians = math.radians(aim_bearing)
    predicted_x = bot.x + math.cos(aim_radians) * distance
    predicted_y = bot.y + math.sin(aim_radians) * distance
    return (
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
    )


__all__ = ["lateral_direction", "point_on_bearing"]

import math

from robocode_tank_royale.bot_api import Bot


def bearing_to(bot: Bot, x: float, y: float, direction: float) -> float:
    absolute_angle = math.degrees(math.atan2(y - bot.y, x - bot.x))
    return ((absolute_angle - direction + 180) % 360) - 180


def body_bearing_to(bot: Bot, x: float, y: float) -> float:
    return bearing_to(bot, x, y, bot.direction)


def absolute_bearing_between(source_x: float, source_y: float, target_x: float, target_y: float) -> float:
    return math.degrees(math.atan2(target_y - source_y, target_x - source_x))


def relative_bearing(angle: float, reference: float) -> float:
    return ((angle - reference + 180) % 360) - 180

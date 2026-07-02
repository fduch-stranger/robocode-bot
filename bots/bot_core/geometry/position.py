import math

from robocode_tank_royale.bot_api import Bot


def distance_to(bot: Bot, x: float, y: float) -> float:
    return math.hypot(x - bot.x, y - bot.y)

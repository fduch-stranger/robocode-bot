import math

from robocode_tank_royale.bot_api import Bot


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

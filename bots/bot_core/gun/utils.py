import math

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.numeric import clamp
from bot_core.target_snapshot import TargetSnapshot


def feature_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    weights = (2.0, 1.2, 1.8, 1.3, 0.8, 0.7, 0.9)
    return math.sqrt(sum(weight * (a - b) ** 2 for weight, a, b in zip(weights, left, right)))


def segment_features(features: tuple[float, ...]) -> tuple[int, ...]:
    distance, firepower, lateral_speed, advancing_speed, acceleration, velocity_change_age, wall_margin = features
    return (
        bucket(distance, 0.30, 0.55),
        bucket(firepower, 0.42, 0.62),
        bucket(lateral_speed, 0.25, 0.70),
        signed_bucket(advancing_speed, -0.25, 0.25),
        0 if abs(acceleration) >= 0.18 or velocity_change_age <= 0.15 else 1,
        bucket(wall_margin, 0.12, 0.25),
    )


def bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value < high:
        return 1
    return 2


def signed_bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value > high:
        return 2
    return 1


def guess_factor_to_bin(guess_factor: float, bins: int) -> int:
    return round((clamp(guess_factor, -1.0, 1.0) + 1.0) * (bins - 1) / 2.0)


def bin_to_guess_factor(index: int, bins: int) -> float:
    return -1.0 + 2.0 * index / (bins - 1)


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

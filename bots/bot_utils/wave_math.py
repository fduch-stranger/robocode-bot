import math

from robocode_tank_royale.bot_api import Bot

from bot_utils.physics import bullet_speed_for_power, max_escape_angle_for_bullet_speed
from bot_utils.tank_math import TargetSnapshot, clamp


def max_escape_angle_for_speed(bullet_speed: float) -> float:
    return max_escape_angle_for_bullet_speed(bullet_speed)


def wall_limited_escape_angle(
    bot: Bot,
    target: TargetSnapshot,
    bullet_speed: float,
    orbit_direction: int,
    ticks: int = 64,
    field_margin: float = 18.0,
) -> float:
    return wall_limited_escape_angle_from_state(
        bot.arena_width,
        bot.arena_height,
        bot.x,
        bot.y,
        target.x,
        target.y,
        bullet_speed,
        orbit_direction,
        ticks,
        field_margin,
    )


def wall_limited_escape_angle_from_state(
    arena_width: float,
    arena_height: float,
    source_x: float,
    source_y: float,
    start_x: float,
    start_y: float,
    bullet_speed: float,
    orbit_direction: int,
    ticks: int = 64,
    field_margin: float = 18.0,
) -> float:
    x = start_x
    y = start_y
    theoretical = max_escape_angle_for_speed(bullet_speed)
    max_offset = 0.0

    for tick in range(1, ticks + 1):
        source_bearing = math.atan2(y - source_y, x - source_x)
        move_bearing = source_bearing + orbit_direction * math.pi / 2
        next_x = x + math.cos(move_bearing) * 8
        next_y = y + math.sin(move_bearing) * 8
        if not _inside_field(arena_width, arena_height, next_x, next_y, field_margin):
            smoothed = _smoothed_wall_bearing(
                arena_width,
                arena_height,
                x,
                y,
                move_bearing,
                orbit_direction,
                field_margin,
            )
            next_x = x + math.cos(smoothed) * 8
            next_y = y + math.sin(smoothed) * 8

        x = clamp(next_x, field_margin, arena_width - field_margin)
        y = clamp(next_y, field_margin, arena_height - field_margin)
        bullet_radius = bullet_speed * tick
        if bullet_radius > math.hypot(x - source_x, y - source_y) + 18:
            break

        current_bearing = absolute_bearing_between(source_x, source_y, x, y)
        direct_bearing = absolute_bearing_between(source_x, source_y, start_x, start_y)
        max_offset = max(max_offset, abs(relative_bearing(current_bearing, direct_bearing)))

    return clamp(max_offset or theoretical, 0.1, theoretical)


def guess_factor_from_offset(
    bearing_offset: float,
    lateral_direction_value: int,
    positive_escape_angle: float,
    negative_escape_angle: float,
) -> float:
    signed_offset = bearing_offset * lateral_direction_value
    escape_angle = positive_escape_angle if signed_offset >= 0 else negative_escape_angle
    return clamp(signed_offset / max(0.1, escape_angle), -1.0, 1.0)


def escape_angle_for_guess_factor(
    bot: Bot,
    target: TargetSnapshot,
    bullet_speed: float,
    lateral_direction_value: int,
    guess_factor: float,
) -> float:
    orbit_direction = lateral_direction_value if guess_factor >= 0 else -lateral_direction_value
    return wall_limited_escape_angle(bot, target, bullet_speed, orbit_direction)


def absolute_bearing_between(source_x: float, source_y: float, target_x: float, target_y: float) -> float:
    return math.degrees(math.atan2(target_y - source_y, target_x - source_x))


def relative_bearing(angle: float, reference: float) -> float:
    return ((angle - reference + 180) % 360) - 180


def _inside_field(arena_width: float, arena_height: float, x: float, y: float, field_margin: float) -> bool:
    return field_margin <= x <= arena_width - field_margin and field_margin <= y <= arena_height - field_margin


def _smoothed_wall_bearing(
    arena_width: float,
    arena_height: float,
    x: float,
    y: float,
    move_bearing: float,
    orbit_direction: int,
    field_margin: float,
) -> float:
    step = math.radians(8) * orbit_direction
    for _ in range(16):
        next_x = x + math.cos(move_bearing) * 8
        next_y = y + math.sin(move_bearing) * 8
        if _inside_field(arena_width, arena_height, next_x, next_y, field_margin):
            return move_bearing
        move_bearing += step
    return move_bearing

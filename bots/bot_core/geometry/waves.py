import math

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.angles import absolute_bearing_between, relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.physics import MAX_ROBOT_SPEED, RobotMovementState, max_escape_angle_for_bullet_speed, predict_robot_movement
from bot_core.target_snapshot import TargetSnapshot


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
        start_direction=target.direction,
        start_speed=target.speed,
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
    start_direction: float | None = None,
    start_speed: float = 0.0,
) -> float:
    theoretical = max_escape_angle_for_speed(bullet_speed)
    max_offset = 0.0
    direct_bearing = absolute_bearing_between(source_x, source_y, start_x, start_y)
    state = RobotMovementState(
        x=start_x,
        y=start_y,
        direction=start_direction if start_direction is not None else direct_bearing + orbit_direction * 90.0,
        speed=start_speed,
    )

    for tick in range(1, ticks + 1):
        source_bearing = math.atan2(state.y - source_y, state.x - source_x)
        move_bearing = source_bearing + orbit_direction * math.pi / 2
        lookahead_x = state.x + math.cos(move_bearing) * MAX_ROBOT_SPEED
        lookahead_y = state.y + math.sin(move_bearing) * MAX_ROBOT_SPEED
        if not _inside_field(arena_width, arena_height, lookahead_x, lookahead_y, field_margin):
            smoothed = _smoothed_wall_bearing(
                arena_width,
                arena_height,
                state.x,
                state.y,
                move_bearing,
                orbit_direction,
                field_margin,
            )
            move_bearing = smoothed

        state = predict_robot_movement(
            state,
            math.degrees(move_bearing),
            max_speed=MAX_ROBOT_SPEED,
            field_margin=field_margin,
            arena_width=arena_width,
            arena_height=arena_height,
        )
        bullet_radius = bullet_speed * tick
        if bullet_radius > math.hypot(state.x - source_x, state.y - source_y) + 18:
            break

        current_bearing = absolute_bearing_between(source_x, source_y, state.x, state.y)
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

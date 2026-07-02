import math
from dataclasses import dataclass

from bot_core.physics.rules import (
    MAX_ROBOT_SPEED,
    ROBOT_ACCELERATION,
    ROBOT_DECELERATION,
    clamp,
    max_robot_turn_rate_for_speed,
)


@dataclass(frozen=True)
class RobotMovementState:
    x: float
    y: float
    direction: float
    speed: float
    turn: int = 0


def predict_robot_movement(
    state: RobotMovementState,
    move_bearing: float,
    max_speed: float = MAX_ROBOT_SPEED,
    distance_remaining: float | None = None,
    field_margin: float | None = None,
    arena_width: float | None = None,
    arena_height: float | None = None,
) -> RobotMovementState:
    relative_bearing = normalize_relative_angle(move_bearing - state.direction)
    target_speed = abs(max_speed)
    if math.cos(math.radians(relative_bearing)) < 0:
        relative_bearing = normalize_relative_angle(relative_bearing + 180.0)
        target_speed = -target_speed

    speed = next_robot_speed(state.speed, target_speed, distance_remaining)
    turn_speed = speed
    x = state.x + math.cos(math.radians(state.direction)) * speed
    y = state.y + math.sin(math.radians(state.direction)) * speed

    wall_hit = False
    if field_margin is not None and arena_width is not None and arena_height is not None:
        x, y, wall_hit = _clip_movement_line(
            state.x,
            state.y,
            x,
            y,
            field_margin,
            arena_width - field_margin,
            field_margin,
            arena_height - field_margin,
        )
        if wall_hit:
            speed = 0.0

    max_turn = max_robot_turn_rate_for_speed(turn_speed)
    direction = state.direction + clamp(relative_bearing, -max_turn, max_turn)
    return RobotMovementState(x=x, y=y, direction=direction, speed=speed, turn=state.turn + 1)


def calc_new_bot_speed(current_speed: float, target_speed: float) -> float:
    target_speed = clamp(target_speed, -MAX_ROBOT_SPEED, MAX_ROBOT_SPEED)
    if current_speed < 0.0:
        return -calc_new_bot_speed(-current_speed, -target_speed)

    if current_speed > 0.0:
        if _sign(current_speed) == _sign(target_speed):
            diff = target_speed - current_speed
            if diff >= 0.0:
                acceleration = min(diff, ROBOT_ACCELERATION)
                return min(current_speed + acceleration, MAX_ROBOT_SPEED)
            acceleration = max(diff, -ROBOT_DECELERATION)
            return max(current_speed + acceleration, -MAX_ROBOT_SPEED)
        if target_speed == 0.0:
            return 0.0
        deceleration_time = current_speed / ROBOT_DECELERATION
        return (1.0 - deceleration_time) * -ROBOT_ACCELERATION

    diff = target_speed - current_speed
    acceleration = min(abs(diff), ROBOT_ACCELERATION)
    if diff >= 0.0:
        return min(current_speed + acceleration, MAX_ROBOT_SPEED)
    return max(current_speed - acceleration, -MAX_ROBOT_SPEED)


def next_robot_speed(
    current_speed: float,
    target_speed: float,
    distance_remaining: float | None = None,
) -> float:
    target_speed = clamp(target_speed, -MAX_ROBOT_SPEED, MAX_ROBOT_SPEED)
    if distance_remaining is not None:
        signed_remaining = abs(distance_remaining) if target_speed >= 0 else -abs(distance_remaining)
        return _next_robot_speed_for_distance(current_speed, abs(target_speed), signed_remaining)

    return calc_new_bot_speed(current_speed, target_speed)


def _next_robot_speed_for_distance(current_speed: float, max_speed: float, distance_remaining: float) -> float:
    if distance_remaining < 0:
        return -_next_robot_speed_for_distance(-current_speed, max_speed, -distance_remaining)

    max_speed = abs(clamp(max_speed, 0.0, MAX_ROBOT_SPEED))
    current_velocity = current_speed
    current_abs_speed = abs(current_speed)

    if current_velocity < 0 or current_abs_speed > max_speed:
        new_speed = current_abs_speed - ROBOT_DECELERATION
        if new_speed < 0:
            decel_time = current_abs_speed / ROBOT_DECELERATION
            accel_time = 1.0 - decel_time
            new_speed = min(
                max_speed,
                ROBOT_DECELERATION * decel_time * decel_time
                + ROBOT_ACCELERATION * accel_time * accel_time,
                distance_remaining,
            )
            current_velocity *= -1
    else:
        decel_time = current_abs_speed / ROBOT_DECELERATION
        decel_distance = 0.5 * ROBOT_DECELERATION * decel_time * decel_time + decel_time
        if distance_remaining <= decel_distance:
            time = distance_remaining / (decel_time + 1.0)
            if time <= 1.0:
                new_speed = max(current_abs_speed - ROBOT_DECELERATION, distance_remaining)
            else:
                new_speed = time * ROBOT_DECELERATION
                if current_abs_speed < new_speed:
                    new_speed = current_abs_speed
                elif current_abs_speed - new_speed > ROBOT_DECELERATION:
                    new_speed = current_abs_speed - ROBOT_DECELERATION
        else:
            new_speed = min(current_abs_speed + ROBOT_ACCELERATION, max_speed)

    return -new_speed if current_velocity < 0 else new_speed


def normalize_relative_angle(angle: float) -> float:
    return ((angle + 180.0) % 360.0) - 180.0


def _clip_movement_line(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    min_x: float,
    max_x: float,
    min_y: float,
    max_y: float,
) -> tuple[float, float, bool]:
    if min_x <= end_x <= max_x and min_y <= end_y <= max_y:
        return end_x, end_y, False

    dx = end_x - start_x
    dy = end_y - start_y
    if dx == 0.0 and dy == 0.0:
        return clamp(end_x, min_x, max_x), clamp(end_y, min_y, max_y), True

    new_x = end_x
    new_y = end_y
    if end_x < min_x:
        new_x = min_x
        if dx != 0.0:
            new_y = start_y + dy * (new_x - start_x) / dx
    elif end_x > max_x:
        new_x = max_x
        if dx != 0.0:
            new_y = start_y + dy * (new_x - start_x) / dx

    if end_y < min_y:
        new_y = min_y
        if dy != 0.0:
            new_x = start_x + dx * (new_y - start_y) / dy
    elif end_y > max_y:
        new_y = max_y
        if dy != 0.0:
            new_x = start_x + dx * (new_y - start_y) / dy

    return new_x, new_y, True


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0

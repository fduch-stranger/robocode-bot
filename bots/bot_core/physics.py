import math
from dataclasses import dataclass


MAX_ROBOT_SPEED = 8.0
ROBOT_ACCELERATION = 1.0
ROBOT_DECELERATION = 2.0


@dataclass(frozen=True)
class RobotMovementState:
    x: float
    y: float
    direction: float
    speed: float
    turn: int = 0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def bullet_speed_for_power(firepower: float) -> float:
    return 20.0 - 3.0 * clamp(firepower, 0.1, 3.0)


def gun_heat_for_power(firepower: float) -> float:
    return 1.0 + clamp(firepower, 0.1, 3.0) / 5.0


def bullet_damage_for_power(firepower: float) -> float:
    power = clamp(firepower, 0.1, 3.0)
    return 4.0 * power + max(0.0, 2.0 * (power - 1.0))


def bullet_hit_bonus_for_power(firepower: float) -> float:
    return 3.0 * clamp(firepower, 0.1, 3.0)


def max_robot_turn_rate_for_speed(speed: float) -> float:
    return 10.0 - 0.75 * abs(clamp(speed, -MAX_ROBOT_SPEED, MAX_ROBOT_SPEED))


def wall_collision_damage_for_speed(speed: float) -> float:
    return max(0.0, abs(speed) * 0.5 - 1.0)


def max_escape_angle_for_bullet_speed(bullet_speed: float) -> float:
    return math.degrees(math.asin(min(1.0, MAX_ROBOT_SPEED / max(0.1, bullet_speed))))


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

    max_turn = max_robot_turn_rate_for_speed(state.speed)
    direction = state.direction + clamp(relative_bearing, -max_turn, max_turn)
    speed = next_robot_speed(state.speed, target_speed, distance_remaining)
    x = state.x + math.cos(math.radians(direction)) * speed
    y = state.y + math.sin(math.radians(direction)) * speed

    if field_margin is not None and arena_width is not None and arena_height is not None:
        x = clamp(x, field_margin, arena_width - field_margin)
        y = clamp(y, field_margin, arena_height - field_margin)

    return RobotMovementState(x=x, y=y, direction=direction, speed=speed, turn=state.turn + 1)


def next_robot_speed(
    current_speed: float,
    target_speed: float,
    distance_remaining: float | None = None,
) -> float:
    target_speed = clamp(target_speed, -MAX_ROBOT_SPEED, MAX_ROBOT_SPEED)
    if distance_remaining is not None:
        signed_remaining = abs(distance_remaining) if target_speed >= 0 else -abs(distance_remaining)
        return _next_robot_speed_for_distance(current_speed, abs(target_speed), signed_remaining)

    if current_speed < target_speed:
        acceleration = ROBOT_DECELERATION if current_speed < 0 else ROBOT_ACCELERATION
        return min(current_speed + acceleration, target_speed)
    if current_speed > target_speed:
        deceleration = ROBOT_DECELERATION if current_speed > 0 else ROBOT_ACCELERATION
        return max(current_speed - deceleration, target_speed)
    return current_speed


def _next_robot_speed_for_distance(current_speed: float, max_speed: float, distance_remaining: float) -> float:
    if distance_remaining < 0:
        return -_next_robot_speed_for_distance(-current_speed, max_speed, -distance_remaining)

    max_speed = abs(clamp(max_speed, 0.0, MAX_ROBOT_SPEED))
    current_velocity = current_speed
    current_abs_speed = abs(current_speed)
    new_speed = current_abs_speed

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

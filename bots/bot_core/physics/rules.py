import math

MAX_ROBOT_SPEED = 8.0
ROBOT_ACCELERATION = 1.0
ROBOT_DECELERATION = 2.0


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

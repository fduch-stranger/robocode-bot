"""Ported from ``voidious.utils``: ``DiaUtils``, ``BattleField``, ``RobotState``,
``RobotStateLog``, ``Interpolator``, ``MaxEscapeTarget``, the timestamped data
records, ``DistanceFormula`` and the ``geom`` package, plus the ``robocode.Rules``
and ``robocode.util.Utils`` helpers Diamond relies on.

All angles are classic Robocode radians: 0 points up (positive y) and angles
grow clockwise.
"""
from __future__ import annotations

import math

HALF_PI = math.pi / 2
TWO_PI = math.pi * 2
QUARTER_PI = math.pi / 4

# robocode.Rules
MAX_VELOCITY = 8.0
ACCELERATION = 1.0
DECELERATION = 2.0
MAX_TURN_RATE = 10.0
MIN_BULLET_POWER = 0.1
MAX_BULLET_POWER = 3.0
BOT_HALF_WIDTH = 18.0
BOT_WIDTH = 36.0

# Java Long.MIN_VALUE / MAX_VALUE stand-ins for the "never" timestamps.
LONG_MIN = -(2**63)
LONG_MAX = 2**63 - 1
INT_MAX = 2**31 - 1


def get_turn_rate_radians(velocity: float) -> float:
    return math.radians(MAX_TURN_RATE - 0.75 * abs(velocity))


def get_bullet_damage(bullet_power: float) -> float:
    damage = 4 * bullet_power
    if bullet_power > 1:
        damage += 2 * (bullet_power - 1)
    return damage


def get_bullet_hit_bonus(bullet_power: float) -> float:
    return 3 * bullet_power


def get_gun_heat(bullet_power: float) -> float:
    return 1 + (bullet_power / 5)


def get_wall_hit_damage(velocity: float) -> float:
    return max(abs(velocity) / 2 - 1, 0.0)


def get_bullet_speed(bullet_power: float) -> float:
    return 20 - (3 * bullet_power)


# robocode.util.Utils
def normal_relative_angle(angle: float) -> float:
    angle = math.fmod(angle, TWO_PI)
    if angle >= 0:
        return angle if angle < math.pi else angle - TWO_PI
    return angle if angle >= -math.pi else angle + TWO_PI


def normal_absolute_angle(angle: float) -> float:
    angle = math.fmod(angle, TWO_PI)
    return angle if angle >= 0 else angle + TWO_PI


def signum(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def java_round(value: float) -> int:
    """``Math.round``: round half up."""
    return int(math.floor(value + 0.5))


def java_div(numerator: float, denominator: float) -> float:
    """Floating-point division with Java semantics for a zero denominator."""
    if denominator == 0:
        if numerator == 0 or math.isnan(numerator):
            return math.nan
        return math.inf if (numerator > 0) == (math.copysign(1.0, denominator) > 0) else -math.inf
    return numerator / denominator


def inverse_sqrt(value: float) -> float:
    """``1 / Math.sqrt(value)`` including Java's infinity for a zero distance."""
    if value <= 0:
        return math.inf
    return 1.0 / math.sqrt(value)


class Point:
    """``java.awt.geom.Point2D.Double``."""

    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x = x
        self.y = y

    def distance(self, other: "Point") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def distance_sq(self, other: "Point") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def clone(self) -> "Point":
        return Point(self.x, self.y)

    def __repr__(self) -> str:
        return f"Point({self.x:.2f}, {self.y:.2f})"


ORIGIN = Point(0.0, 0.0)


# DiaUtils ------------------------------------------------------------------
def project(source: Point, angle: float, length: float) -> Point:
    return Point(source.x + math.sin(angle) * length, source.y + math.cos(angle) * length)


def project_sin_cos(source: Point, sin_angle: float, cos_angle: float, length: float) -> Point:
    return Point(source.x + sin_angle * length, source.y + cos_angle * length)


def absolute_bearing(source: Point, target: Point) -> float:
    return math.atan2(target.x - source.x, target.y - source.y)


def non_zero_sign(value: float) -> int:
    return -1 if value < 0 else 1


def square(value: float) -> float:
    return value * value


def cube(value: float) -> float:
    return value * value * value


def power(value: float, exponent: int) -> float:
    result = 1.0
    for _ in range(exponent):
        result *= value
    return result


def limit(minimum: float, value: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def bot_width_aim_angle(distance: float) -> float:
    return abs(java_div(18.0, distance))


def bullet_ticks_from_power(distance: float, bullet_power: float) -> int:
    return int(math.ceil(distance / (20 - (3 * bullet_power))))


def bullet_ticks_from_speed(distance: float, speed: float) -> int:
    return int(math.ceil(distance / speed))


def rolling_average(previous_value: float, new_value: float, depth: float) -> float:
    return ((previous_value * depth) + new_value) / (depth + 1)


def round_to(value: float, digits: int) -> float:
    power_ten = 1
    for _ in range(digits):
        power_ten *= 10
    return float(java_round(value * power_ten)) / power_ten


def standard_deviation(values: list[float]) -> float:
    avg = average(values)
    sum_squares = 0.0
    for value in values:
        sum_squares += square(avg - value)
    return math.sqrt(sum_squares / len(values))


def average(values: list[float]) -> float:
    return sum(values) / len(values)


def accel(velocity: float, previous_velocity: float) -> float:
    acceleration = velocity - previous_velocity
    if previous_velocity == 0.0:
        acceleration = abs(acceleration)
    else:
        acceleration *= signum(previous_velocity)
    return acceleration


def pt_seg_dist(x1: float, y1: float, x2: float, y2: float, px: float, py: float) -> float:
    """``java.awt.geom.Line2D.ptSegDist``."""
    x2 -= x1
    y2 -= y1
    px -= x1
    py -= y1
    dot_prod = px * x2 + py * y2
    if dot_prod <= 0.0:
        proj_len_sq = 0.0
    else:
        px = x2 - px
        py = y2 - py
        dot_prod = px * x2 + py * y2
        if dot_prod <= 0.0:
            proj_len_sq = 0.0
        else:
            proj_len_sq = dot_prod * dot_prod / (x2 * x2 + y2 * y2)
    len_sq = px * px + py * py - proj_len_sq
    if len_sq < 0:
        len_sq = 0.0
    return math.sqrt(len_sq)


def distance_point_to_bot(source: Point, bot_location: Point, bot_sides: list[tuple[float, float, float, float]]) -> float:
    if (
        bot_location.x - 18 < source.x < bot_location.x + 18
        and bot_location.y - 18 < source.y < bot_location.y + 18
    ):
        return 0.0
    distance = math.inf
    for x1, y1, x2, y2 in bot_sides:
        distance = min(distance, pt_seg_dist(x1, y1, x2, y2, source.x, source.y))
    return distance


def distance_point_to_bot_state(source: Point, robot_state: "RobotState") -> float:
    return distance_point_to_bot(source, robot_state.location, robot_state.bot_sides())


def normalize_angle(angle: float, reference: float) -> float:
    norm_diff = reference - angle
    while abs(norm_diff) > math.pi:
        angle += signum(norm_diff) * TWO_PI
        norm_diff = reference - angle
    return angle


def generate_firing_angles(num_angles: int, max_escape_angle: float) -> list[float]:
    gf_zero = (num_angles - 1) // 2
    return [(float(x - gf_zero) / gf_zero) * max_escape_angle for x in range(num_angles)]


def distance_to_wall(enemy_location: Point, battle_field: "BattleField") -> float:
    return abs(
        min(
            min(enemy_location.x - 18, battle_field.width - 18 - enemy_location.x),
            min(enemy_location.y - 18, battle_field.height - 18 - enemy_location.y),
        )
    )


def margin_of_error(probability: float, num_data_points: int) -> float:
    return 1.96 * math.sqrt(java_div(probability * (1 - probability), num_data_points))


# BattleField ---------------------------------------------------------------
class BattleField:
    """``voidious.utils.BattleField``: the arena minus the 18 px bot half-width."""

    __slots__ = ("width", "height", "min_x", "min_y", "max_x", "max_y")

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        self.min_x = 18.0
        self.min_y = 18.0
        self.max_x = width - 18.0
        self.max_y = height - 18.0

    def contains(self, x: float, y: float) -> bool:
        """``Rectangle2D.contains``: closed at the low edge, open at the high edge."""
        return self.min_x <= x < self.max_x and self.min_y <= y < self.max_y

    def contains_point(self, point: Point) -> bool:
        return self.min_x <= point.x < self.max_x and self.min_y <= point.y < self.max_y

    def translate_to_field(self, point: Point) -> Point:
        return Point(limit(18.0, point.x, self.width - 18), limit(18.0, point.y, self.height - 18))

    def orbital_wall_distance(self, source: Point, target: Point, bullet_power: float, direction: int) -> float:
        abs_bearing = absolute_bearing(source, target)
        distance = source.distance(target)
        max_escape_angle = math.asin(8.0 / (20 - 3.0 * bullet_power))
        wall_distance = 2.0
        for x in range(200):
            angle = abs_bearing + (direction * (x / 100.0) * max_escape_angle)
            if not self.contains(source.x + math.sin(angle) * distance, source.y + math.cos(angle) * distance):
                wall_distance = x / 100.0
                break
        return wall_distance

    def direct_to_wall_distance(self, target: Point, distance: float, heading: float, bullet_power: float) -> float:
        bullet_ticks = bullet_ticks_from_power(distance, bullet_power)
        wall_distance = 2.0
        sin_heading = math.sin(heading)
        cos_heading = math.cos(heading)
        for x in range(2 * bullet_ticks):
            if not self.contains(target.x + sin_heading * 8.0 * x, target.y + cos_heading * 8.0 * x):
                wall_distance = float(x) / bullet_ticks
                break
        return wall_distance

    def wall_smoothing(self, start: Point, start_angle: float, orientation: int, wall_stick: float) -> float:
        width = self.width
        height = self.height
        wall_distance_x = min(start.x - 18, width - start.x - 18)
        wall_distance_y = min(start.y - 18, height - start.y - 18)
        if wall_distance_x > wall_stick and wall_distance_y > wall_stick:
            return start_angle

        angle = start_angle
        test_x = start.x + math.sin(angle) * wall_stick
        test_y = start.y + math.cos(angle) * wall_stick
        test_distance_x = min(test_x - 18, width - test_x - 18)
        test_distance_y = min(test_y - 18, height - test_y - 18)
        adjacent = 0.0
        g = 0
        while (test_distance_x < 0 or test_distance_y < 0) and g < 25:
            g += 1
            if test_distance_y < 0 and test_distance_y < test_distance_x:
                angle = math.pi if test_y < 18 else 0.0
                adjacent = wall_distance_y
            elif test_distance_x < 0 and test_distance_x <= test_distance_y:
                angle = (3 * HALF_PI) if test_x < 18 else HALF_PI
                adjacent = wall_distance_x

            if adjacent < 0:
                if -adjacent > wall_stick:
                    wall_stick += -adjacent
                angle += math.pi - orientation * (abs(math.acos(-adjacent / wall_stick)) - 0.0005)
            else:
                angle += orientation * (abs(math.acos(min(1.0, adjacent / wall_stick))) + 0.0005)
            test_x = start.x + math.sin(angle) * wall_stick
            test_y = start.y + math.cos(angle) * wall_stick
            test_distance_x = min(test_x - 18, width - test_x - 18)
            test_distance_y = min(test_y - 18, height - test_y - 18)
        return angle


# RobotState / RobotStateLog -------------------------------------------------
class RobotState:
    """``voidious.utils.RobotState``: an immutable position sample."""

    __slots__ = ("location", "heading", "velocity", "time", "interpolated", "_corners", "_sides")

    def __init__(
        self,
        location: Point | None = None,
        heading: float = 0.0,
        velocity: float = 0.0,
        time: int = -1,
        interpolated: bool = False,
    ) -> None:
        self.location = location
        self.heading = heading
        self.velocity = velocity
        self.time = time
        self.interpolated = interpolated
        self._corners: list[Point] | None = None
        self._sides: list[tuple[float, float, float, float]] | None = None

    def bot_corners(self) -> list[Point]:
        if self._corners is None:
            x = self.location.x
            y = self.location.y
            self._corners = [
                Point(x - BOT_HALF_WIDTH, y - BOT_HALF_WIDTH),
                Point(x - BOT_HALF_WIDTH, y + BOT_HALF_WIDTH),
                Point(x + BOT_HALF_WIDTH, y - BOT_HALF_WIDTH),
                Point(x + BOT_HALF_WIDTH, y + BOT_HALF_WIDTH),
            ]
        return self._corners

    def bot_sides(self) -> list[tuple[float, float, float, float]]:
        if self._sides is None:
            x = self.location.x
            y = self.location.y
            self._sides = [
                (x - 18, y - 18, x + 18, y - 18),
                (x + 18, y - 18, x + 18, y + 18),
                (x + 18, y + 18, x - 18, y + 18),
                (x - 18, y + 18, x - 18, y - 18),
            ]
        return self._sides


class RobotStateLog:
    """``voidious.utils.RobotStateLog``: states by time with linear interpolation."""

    __slots__ = ("_robot_states",)

    def __init__(self) -> None:
        self._robot_states: dict[int, RobotState] = {}

    def clear(self) -> None:
        self._robot_states.clear()

    def add_state(self, state: RobotState) -> None:
        self._robot_states[state.time] = state

    def get_state(self, time: int, interpolate: bool = True) -> RobotState | None:
        states = self._robot_states
        state = states.get(time)
        if state is not None:
            return state if (interpolate or not state.interpolated) else None
        if not interpolate:
            return None
        before_state = None
        after_state = None
        for candidate in states.values():
            if candidate.interpolated:
                continue
            if candidate.time < time and (before_state is None or candidate.time > before_state.time):
                before_state = candidate
            if candidate.time > time and (after_state is None or candidate.time < after_state.time):
                after_state = candidate
        if before_state is None or after_state is None:
            return None
        interpolator = Interpolator(time, before_state.time, after_state.time)
        interpolated = RobotState(
            interpolator.get_location(before_state.location, after_state.location),
            interpolator.get_heading(before_state.heading, after_state.heading),
            interpolator.avg(before_state.velocity, after_state.velocity),
            time,
            True,
        )
        states[time] = interpolated
        return interpolated

    def get_displacement_distance(self, location: Point, current_time: int, ticks_ago: int) -> float:
        past_state = self.get_state(current_time - ticks_ago)
        if past_state is None:
            past_state = self.get_oldest_state()
        return location.distance(past_state.location)

    def get_oldest_state(self) -> RobotState:
        return self._robot_states[min(self._robot_states)]

    def all_states(self) -> list[RobotState]:
        return list(self._robot_states.values())

    def size(self) -> int:
        return len(self._robot_states)

    def clone(self) -> "RobotStateLog":
        new_log = RobotStateLog()
        new_log._robot_states = dict(self._robot_states)
        return new_log


class Interpolator:
    __slots__ = ("fire_time", "before_time", "after_time", "weight1", "weight2")

    def __init__(self, fire_time: int, before_time: int, after_time: int) -> None:
        if fire_time <= before_time or fire_time >= after_time or before_time >= after_time:
            raise ValueError("Time values must be: beforeTime < fireTime < afterTime")
        self.fire_time = fire_time
        self.before_time = before_time
        self.after_time = after_time
        raw_weight1 = abs(after_time - fire_time)
        raw_weight2 = abs(before_time - fire_time)
        self.weight1 = raw_weight1 / (raw_weight1 + raw_weight2)
        self.weight2 = raw_weight2 / (raw_weight1 + raw_weight2)

    def avg(self, value1: float, value2: float) -> float:
        return (value1 * self.weight1) + (value2 * self.weight2)

    def get_location(self, location1: Point, location2: Point) -> Point:
        return Point(self.avg(location1.x, location2.x), self.avg(location1.y, location2.y))

    def get_heading(self, heading1: float, heading2: float) -> float:
        return self.avg(heading1, normalize_angle(heading2, heading1))

    def get_timer(self, value1: int, value2: int) -> int:
        new_value = value2 - (self.after_time - self.fire_time)
        if new_value < 0:
            new_value = value1 + (self.fire_time - self.before_time)
        return new_value


class MaxEscapeTarget:
    __slots__ = ("angle", "location", "time", "hit_wall")

    def __init__(self, angle: float, location: Point, time: int, hit_wall: bool) -> None:
        self.angle = angle
        self.location = location
        self.time = time
        self.hit_wall = hit_wall


# Timestamped data -------------------------------------------------------------
class Timestamped:
    __slots__ = ("round", "time")

    def __init__(self, round_num: int, time: int) -> None:
        self.round = round_num
        self.time = time

    def sort_key(self) -> tuple[int, int]:
        return (self.round, self.time)


class TimestampedFiringAngle(Timestamped):
    __slots__ = ("guess_factor", "displacement_vector")

    def __init__(self, round_num: int, time: int, guess_factor: float, displacement_vector: Point) -> None:
        super().__init__(round_num, time)
        self.guess_factor = guess_factor
        self.displacement_vector = displacement_vector


class TimestampedGuessFactor(Timestamped):
    __slots__ = ("guess_factor",)

    def __init__(self, round_num: int, tick: int, guess_factor: float) -> None:
        super().__init__(round_num, tick)
        self.guess_factor = guess_factor


class DistanceFormula:
    """``voidious.utils.DistanceFormula``: turns a wave into a weighted data point."""

    weights: list[float]

    def data_point_from_wave(self, wave, aiming: bool = False) -> list[float]:
        raise NotImplementedError


# geom ----------------------------------------------------------------------
class LineSeg:
    """``voidious.utils.geom.LineSeg``: y = mx + b, with the segment bounds."""

    __slots__ = ("m", "b", "x_min", "x_max", "y_min", "y_max", "x1", "y1", "x2", "y2")

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        if x1 == x2:
            self.m = math.inf
            self.b = math.nan
            self.x_min = self.x_max = x1
        else:
            self.m = (y2 - y1) / (x2 - x1)
            self.b = y1 - (self.m * x1)
            self.x_min = min(x1, x2)
            self.x_max = max(x1, x2)
        self.y_min = min(y1, y2)
        self.y_max = max(y1, y2)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2


class Circle:
    """``voidious.utils.geom.Circle``: (x-h)^2 + (y-k)^2 = r^2."""

    __slots__ = ("h", "k", "r")

    def __init__(self, x: float, y: float, r: float) -> None:
        self.h = x
        self.k = y
        self.r = r

    def intersects(self, seg: LineSeg) -> list[Point | None]:
        a = (seg.m * seg.m) + 1
        solutions: list[Point | None] = [None, None]
        if a == math.inf:
            inv_seg = LineSeg(seg.y1, seg.x1, seg.y2, seg.x2)
            inv_circle = Circle(self.k, self.h, self.r)
            inv_solutions = inv_circle.intersects(inv_seg)
            for solution in inv_solutions:
                if solution is not None:
                    solution.x, solution.y = solution.y, solution.x
            return inv_solutions

        b = 2 * ((seg.b * seg.m) - (self.k * seg.m) - self.h)
        c = (self.h * self.h) + (self.k * self.k) + (seg.b * seg.b) - (2 * seg.b * self.k) - (self.r * self.r)
        discrim = (b * b) - (4 * a * c)
        if discrim < 0:
            return solutions
        sqrt_discrim = math.sqrt(discrim)
        i = 0
        x1 = (-b + sqrt_discrim) / (2 * a)
        y1 = (seg.m * x1) + seg.b
        if seg.x_min < x1 < seg.x_max:
            solutions[i] = Point(x1, y1)
            i += 1
        if sqrt_discrim > 0:
            x2 = (-b - sqrt_discrim) / (2 * a)
            y2 = (seg.m * x2) + seg.b
            if seg.x_min < x2 < seg.x_max:
                solutions[i] = Point(x2, y2)
                i += 1
        return solutions

    def contains(self, p: Point) -> bool:
        z = square(p.x - self.h) + square(p.y - self.k)
        return z < self.r * self.r

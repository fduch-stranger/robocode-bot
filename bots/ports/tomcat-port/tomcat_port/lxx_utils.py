"""Geometry, rules, and small value helpers ported from Tomcat's ``lxx.utils``.

All angles are classic Robocode radians: 0 points up (+y), and angles grow
clockwise. Positions use the arena coordinates shared by Robocode and Tank
Royale (origin bottom-left, y up). Tank Royale's own degree convention is
converted only at the bot boundary in ``tomcat-port.py``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

TWO_PI = math.pi * 2.0
HALF_PI = math.pi / 2.0
NEAR_DELTA = 0.00001

# LXXConstants
RADIANS_0_1 = math.radians(0.1)
RADIANS_0_5 = math.radians(0.5)
RADIANS_1 = math.radians(1)
RADIANS_4 = math.radians(4)
RADIANS_5 = math.radians(5)
RADIANS_10 = math.radians(10)
RADIANS_15 = math.radians(15)
RADIANS_30 = math.radians(30)
RADIANS_45 = math.radians(45)
RADIANS_50 = math.radians(50)
RADIANS_80 = math.radians(80)
RADIANS_90 = math.radians(90)
RADIANS_100 = math.radians(100)
RADIANS_135 = math.radians(135)
RADIANS_180 = math.radians(180)
RADIANS_270 = math.radians(270)
RADIANS_360 = math.radians(360)

ROBOT_SIDE_SIZE = 36
ROBOT_SIDE_HALF_SIZE = ROBOT_SIDE_SIZE // 2
ROBOT_SQUARE_DIAGONAL = ROBOT_SIDE_SIZE * math.sqrt(2)
INITIAL_GUN_HEAT = 3.0
ROBOT_HIT_DAMAGE = 0.6
INACTIVITY_TIMER = 450

# robocode.Rules
MAX_VELOCITY = 8.0
ACCELERATION = 1.0
DECELERATION = 2.0
MAX_TURN_RATE_RADIANS = math.radians(10.0)
GUN_TURN_RATE_RADIANS = math.radians(20.0)
RADAR_TURN_RATE_RADIANS = math.radians(45.0)
MAX_BULLET_POWER = 3.0
MIN_BULLET_POWER = 0.1


def turn_rate_radians(velocity: float) -> float:
    return math.radians(10.0 - 0.75 * abs(velocity))


def bullet_speed(power: float) -> float:
    return 20.0 - 3.0 * power


def min_bullet_speed() -> float:
    return bullet_speed(MAX_BULLET_POWER)


def gun_heat_for(power: float) -> float:
    return 1.0 + power / 5.0


def bullet_damage(power: float) -> float:
    damage = 4.0 * power
    if power > 1.0:
        damage += 2.0 * (power - 1.0)
    return damage


def wall_hit_damage(velocity: float) -> float:
    return max(abs(velocity) / 2.0 - 1.0, 0.0)


def bullet_power(speed: float) -> float:
    return (20.0 - speed) / 3.0


def returned_energy(power: float) -> float:
    return 3.0 * power


# robocode.util.Utils
def normal_absolute_angle(angle: float) -> float:
    angle = math.fmod(angle, TWO_PI)
    return angle if angle >= 0.0 else angle + TWO_PI


def normal_relative_angle(angle: float) -> float:
    angle = math.fmod(angle, TWO_PI)
    if angle >= math.pi:
        return angle - TWO_PI
    if angle < -math.pi:
        return angle + TWO_PI
    return angle


def normal_near_absolute_angle(angle: float) -> float:
    angle = normal_absolute_angle(angle)
    if is_near(angle, TWO_PI) or is_near(angle, 0.0):
        return 0.0
    return angle


def is_near(a: float, b: float) -> bool:
    return abs(a - b) < NEAR_DELTA


def sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def limit(minimum: float, value: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def angle(base_x: float, base_y: float, x: float, y: float) -> float:
    """Absolute Robocode bearing from (base_x, base_y) to (x, y) in [0, 2pi)."""
    return normal_absolute_angle(math.atan2(x - base_x, y - base_y))


def angles_diff(alpha1: float, alpha2: float) -> float:
    return abs(normal_relative_angle(alpha1 - alpha2))


class PointLike:
    """Mixin giving Tomcat's ``APoint`` operations to anything with ``x`` and ``y``."""

    x: float
    y: float

    def a_distance(self, other: PointLike) -> float:
        return math.hypot(other.x - self.x, other.y - self.y)

    def a_distance_sq(self, other: PointLike) -> float:
        dx = other.x - self.x
        dy = other.y - self.y
        return dx * dx + dy * dy

    def angle_to(self, other: PointLike) -> float:
        return angle(self.x, self.y, other.x, other.y)

    def project(self, alpha: float, distance: float) -> LXXPoint:
        return LXXPoint(self.x + math.sin(alpha) * distance, self.y + math.cos(alpha) * distance)

    def project_vector(self, vector: DeltaVector) -> LXXPoint:
        return self.project(vector.alpha_radians, vector.length)


class LXXPoint(PointLike):
    __slots__ = ("x", "y")

    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)

    @classmethod
    def of(cls, point: PointLike) -> LXXPoint:
        return cls(point.x, point.y)

    def distance_to_wall(self, battle_field: BattleField, direction: float) -> float:
        wall = battle_field.get_wall(self, direction)
        return battle_field.distance_to_wall(wall, self) / abs(math.cos(direction - wall.wall_type.from_center_angle))

    def __repr__(self) -> str:
        return f"[{self.x:.2f}, {self.y:.2f}]"


@dataclass(frozen=True)
class DeltaVector:
    alpha_radians: float
    length: float


class IntervalDouble:
    __slots__ = ("a", "b")

    def __init__(self, a: float | None = None, b: float | None = None) -> None:
        # Java's default constructor starts inverted (Long.MAX_VALUE, Long.MIN_VALUE).
        self.a = float(9223372036854775807) if a is None else float(a)
        self.b = float(-9223372036854775808) if b is None else float(b)

    @classmethod
    def of(cls, other: IntervalDouble) -> IntervalDouble:
        return cls(other.a, other.b)

    @property
    def length(self) -> float:
        return self.b - self.a

    def center(self) -> float:
        return (self.a + self.b) / 2.0

    def contains(self, x: float) -> bool:
        return self.a <= x <= self.b

    def extend(self, x: float) -> None:
        if self.a > x:
            self.a = x
        if self.b < x:
            self.b = x

    def intersects(self, other: IntervalDouble) -> bool:
        return (self.a <= other.a <= self.b) or (other.a <= self.a <= other.b)

    def intersection(self, other: IntervalDouble) -> float:
        return min(self.b, other.b) - max(self.a, other.a)

    def merge(self, other: IntervalDouble) -> None:
        self.a = min(self.a, other.a)
        self.b = max(self.b, other.b)

    def __repr__(self) -> str:
        return f"[{self.a}, {self.b}]"


class IntervalDoubleDanger(IntervalDouble):
    __slots__ = ("danger",)

    def __init__(self, a: float, b: float, danger: float) -> None:
        super().__init__(a, b)
        self.danger = danger


class IntervalLong:
    __slots__ = ("a", "b")

    def __init__(self, a: int, b: int) -> None:
        self.a = a
        self.b = b

    @property
    def length(self) -> int:
        return self.b - self.a

    def contains(self, x: int) -> bool:
        return self.a <= x <= self.b

    def extend(self, x: int) -> None:
        if self.a > x:
            self.a = x
        if self.b < x:
            self.b = x


class AvgValue:
    def __init__(self, depth: int) -> None:
        self.depth = depth
        self.values = [0.0] * depth
        self.values_count = 0
        self.current_sum = 0.0
        self.current_value = 0.0

    def add_value(self, value: float) -> None:
        index = self.values_count % self.depth
        self.current_sum = self.current_sum - self.values[index] + value
        self.values[index] = value
        self.values_count += 1
        self.current_value = self.current_sum / min(self.values_count, self.depth)


class Median:
    def __init__(self, limit_size: int) -> None:
        self.limit = limit_size
        self.values: list[float] = []

    def add_value(self, value: float) -> None:
        if len(self.values) == self.limit:
            if value < self.get_median():
                self.values.pop(0)
            else:
                self.values.pop()
        import bisect

        bisect.insort(self.values, value)

    def get_median(self) -> float:
        if not self.values:
            return 0.0
        if len(self.values) == 1:
            return self.values[0]
        index = len(self.values) // 2 - 1
        return (self.values[index] + self.values[index + 1]) / 2.0


class HitRate:
    def __init__(self) -> None:
        self.hit_count = 0
        self.miss_count = 0

    def hit(self) -> None:
        self.hit_count += 1

    def miss(self) -> None:
        self.miss_count += 1

    def get_hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total else 0.0

    def get_fire_count(self) -> int:
        return self.hit_count + self.miss_count

    def __repr__(self) -> str:
        return f"({self.hit_count}/{self.get_fire_count()}) = {self.get_hit_rate() * 100:.1f}%"


class WallType:
    __slots__ = ("name", "from_center_angle")

    def __init__(self, name: str, from_center_angle: float) -> None:
        self.name = name
        self.from_center_angle = from_center_angle


TOP = WallType("TOP", 0.0)
RIGHT = WallType("RIGHT", RADIANS_90)
BOTTOM = WallType("BOTTOM", RADIANS_180)
LEFT = WallType("LEFT", RADIANS_270)


class Wall:
    __slots__ = ("wall_type", "ccw", "cw", "clockwise_wall", "counter_clockwise_wall")

    def __init__(self, wall_type: WallType, ccw: LXXPoint, cw: LXXPoint) -> None:
        self.wall_type = wall_type
        self.ccw = ccw
        self.cw = cw
        self.clockwise_wall: Wall | None = None
        self.counter_clockwise_wall: Wall | None = None


class BattleField:
    WALL_STICK = 140.0

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.available_bottom_y = y
        self.available_top_y = y + height
        self.available_left_x = x
        self.available_right_x = x + width

        self.available_left_bottom = LXXPoint(self.available_left_x, self.available_bottom_y)
        self.available_left_top = LXXPoint(self.available_left_x, self.available_top_y)
        self.available_right_top = LXXPoint(self.available_right_x, self.available_top_y)
        self.available_right_bottom = LXXPoint(self.available_right_x, self.available_bottom_y)

        top_y = y * 2 + height
        right_x = x * 2 + width
        self._left_top = LXXPoint(0, top_y)
        self._right_top = LXXPoint(right_x, top_y)
        self._right_bottom = LXXPoint(right_x, 0)

        self.bottom = Wall(BOTTOM, self.available_right_bottom, self.available_left_bottom)
        self.left = Wall(LEFT, self.available_left_bottom, self.available_left_top)
        self.top = Wall(TOP, self.available_left_top, self.available_right_top)
        self.right = Wall(RIGHT, self.available_right_top, self.available_right_bottom)
        self.bottom.clockwise_wall = self.left
        self.bottom.counter_clockwise_wall = self.right
        self.left.clockwise_wall = self.top
        self.left.counter_clockwise_wall = self.bottom
        self.top.clockwise_wall = self.right
        self.top.counter_clockwise_wall = self.left
        self.right.clockwise_wall = self.bottom
        self.right.counter_clockwise_wall = self.top

        self._rect_x = x - 1
        self._rect_y = y - 1
        self._rect_w = width + 2
        self._rect_h = height + 2

        self.center = LXXPoint(right_x // 2, top_y // 2)
        self.width = width
        self.height = height
        self.no_smooth_x = IntervalDouble(self.WALL_STICK, width - self.WALL_STICK)
        self.no_smooth_y = IntervalDouble(self.WALL_STICK, height - self.WALL_STICK)

    def get_wall(self, pos: PointLike, heading: float) -> Wall:
        normal_heading_tg = math.tan(math.fmod(heading, RADIANS_90))
        if heading < RADIANS_90:
            right_top_tg = (self._right_top.x - pos.x) / (self._right_top.y - pos.y)
            return self.top if normal_heading_tg < right_top_tg else self.right
        if heading < RADIANS_180:
            right_bottom_tg = pos.y / (self._right_bottom.x - pos.x)
            return self.right if normal_heading_tg < right_bottom_tg else self.bottom
        if heading < RADIANS_270:
            left_bottom_tg = pos.x / pos.y
            return self.bottom if normal_heading_tg < left_bottom_tg else self.left
        if heading < RADIANS_360:
            left_top_tg = (self._left_top.y - pos.y) / pos.x
            return self.left if normal_heading_tg < left_top_tg else self.top
        raise ValueError(f"Invalid heading: {heading}")

    def bearing_offset_to_wall(self, pnt: PointLike, heading: float) -> float:
        return normal_relative_angle(self.get_wall(pnt, heading).wall_type.from_center_angle - heading)

    def distance_to_wall(self, wall: Wall, pnt: PointLike) -> float:
        wall_type = wall.wall_type
        if wall_type is TOP:
            return self.available_top_y - pnt.y
        if wall_type is RIGHT:
            return self.available_right_x - pnt.x
        if wall_type is BOTTOM:
            return pnt.y - self.available_bottom_y
        return pnt.x - self.available_left_x

    def smooth_walls(self, pnt: PointLike, desired_heading: float, is_clockwise: bool) -> float:
        return self._smooth_wall(self.get_wall(pnt, desired_heading), pnt, desired_heading, is_clockwise)

    def _smooth_wall(self, wall: Wall, pnt: PointLike, desired_heading: float, is_clockwise: bool) -> float:
        adjacent_leg = max(0.0, self.distance_to_wall(wall, pnt) - 4.0)
        if self.WALL_STICK < adjacent_leg:
            return desired_heading
        smooth_angle = (math.acos(adjacent_leg / self.WALL_STICK) + RADIANS_4) * (1 if is_clockwise else -1)
        smoothed_angle = normal_absolute_angle(wall.wall_type.from_center_angle + smooth_angle)
        second_wall = wall.clockwise_wall if is_clockwise else wall.counter_clockwise_wall
        assert second_wall is not None
        return self._smooth_wall(second_wall, pnt, smoothed_angle, is_clockwise)

    def contains(self, point: PointLike) -> bool:
        return (
            self._rect_x <= point.x <= self._rect_x + self._rect_w
            and self._rect_y <= point.y <= self._rect_y + self._rect_h
        )


def lateral_direction(center: PointLike, robot_state) -> float:
    return _lateral_direction(center, robot_state, robot_state.speed, robot_state.absolute_heading_radians)


def _lateral_direction(center: PointLike, pos: PointLike, velocity: float, heading: float) -> float:
    if is_near(0.0, velocity):
        return 1.0
    return sign(_lateral_velocity(center, pos, velocity, heading))


def lateral_velocity(center: PointLike, robot_state) -> float:
    return _lateral_velocity(center, robot_state, robot_state.speed, robot_state.absolute_heading_radians)


def _lateral_velocity(center: PointLike, pos: PointLike, velocity: float, heading: float) -> float:
    return velocity * math.sin(normal_relative_angle(heading - center.angle_to(pos)))


def bearing_offset(source: PointLike, dest1: PointLike, dest2: PointLike) -> float:
    return normal_relative_angle(angle(source.x, source.y, dest2.x, dest2.y) - angle(source.x, source.y, dest1.x, dest1.y))


def robot_width_in_radians(angle_value: float, distance: float) -> float:
    alpha = abs(RADIANS_45 - math.fmod(angle_value, RADIANS_90))
    if distance < ROBOT_SQUARE_DIAGONAL:
        distance = ROBOT_SQUARE_DIAGONAL
    return math.asin(math.cos(alpha) * ROBOT_SQUARE_DIAGONAL / distance)


def robot_width_in_radians_between(center: PointLike, robot_pos: PointLike) -> float:
    return robot_width_in_radians(center.angle_to(robot_pos), center.a_distance(robot_pos))


def max_escape_angle(bullet_speed_value: float) -> float:
    return math.asin(MAX_VELOCITY / bullet_speed_value)


def max_escape_angle_precise(center: PointLike, state, bullet_speed_value: float) -> float:
    """The robowiki quadratic escape angle, assuming the enemy stops at walls."""
    e_abs_bearing = center.angle_to(state)
    r_x = center.x
    r_y = center.y
    e_x = state.x
    e_y = state.y
    e_v = state.velocity
    e_hd = state.heading_radians
    a_coef = (e_x - r_x) / bullet_speed_value
    b_coef = e_v / bullet_speed_value * math.sin(e_hd)
    c_coef = (e_y - r_y) / bullet_speed_value
    d_coef = e_v / bullet_speed_value * math.cos(e_hd)
    a = a_coef * a_coef + c_coef * c_coef
    b = 2 * (a_coef * b_coef + c_coef * d_coef)
    c = b_coef * b_coef + d_coef * d_coef - 1
    discrim = b * b - 4 * a * c
    if discrim >= 0:
        root = math.sqrt(discrim)
        denominator1 = -b - root
        denominator2 = -b + root
        t1 = 2 * a / denominator1 if denominator1 else float("inf")
        t2 = 2 * a / denominator2 if denominator2 else float("inf")
        t = min(t1, t2) if min(t1, t2) >= 0 else max(t1, t2)
        battle_field = state.battle_field
        end_x = limit(battle_field.available_left_x, e_x + e_v * t * math.sin(e_hd), battle_field.available_right_x)
        end_y = limit(battle_field.available_bottom_y, e_y + e_v * t * math.cos(e_hd), battle_field.available_top_y)
        return abs(normal_relative_angle(center.angle_to(LXXPoint(end_x, end_y)) - e_abs_bearing))
    return 0.0


def calculate_acceleration(prev_state, cur_state) -> float:
    if prev_state is None:
        return 0.0
    if sign(cur_state.velocity) == sign(prev_state.velocity) or abs(cur_state.velocity) < 0.001:
        acceleration = abs(cur_state.velocity) - abs(prev_state.velocity)
    else:
        acceleration = abs(cur_state.velocity)
    return limit(-MAX_VELOCITY, acceleration, ACCELERATION)


def stop_distance(speed: float) -> float:
    distance = 0.0
    while speed > 0:
        speed -= DECELERATION
        distance += speed
    return distance


def stop_time(speed: float) -> int:
    time = 0
    while speed > 0:
        speed -= DECELERATION
        time += 1
    return time


def intersection(pnt1: PointLike, pnt2: PointLike, center: PointLike, r: float) -> list[LXXPoint]:
    """Intersections of segment pnt1-pnt2 with the circle (center, r), farthest end first."""
    if center.a_distance(pnt1) > center.a_distance(pnt2):
        farthest, closest = pnt1, pnt2
    else:
        farthest, closest = pnt2, pnt1
    segment_alpha = farthest.angle_to(closest)
    segment_dist = farthest.a_distance(closest)
    new_circle_center = LXXPoint().project(
        abs(normal_relative_angle(farthest.angle_to(center) - segment_alpha)), farthest.a_distance(center)
    )
    if r < new_circle_center.x:
        return []
    half_chord = math.sqrt(max(0.0, r * r - new_circle_center.x * new_circle_center.x))
    y1 = half_chord + new_circle_center.y
    y2 = -half_chord + new_circle_center.y
    result: list[LXXPoint] = []
    if 0 < y2 < segment_dist:
        result.append(farthest.project(segment_alpha, y2))
    if 0 < y1 < segment_dist:
        result.append(farthest.project(segment_alpha, y1))
    return result


FIFTEEN_BITS = 0x7FFF


def round_time(time: int, round_number: int) -> int:
    return ((round_number & FIFTEEN_BITS) << 15) | (time & FIFTEEN_BITS)


def bounding_rect_contains(point: PointLike, x: float, y: float, side_half_size: int = ROBOT_SIDE_HALF_SIZE) -> bool:
    """``LXXUtils.getBoundingRectangleAt(point).contains(x, y)`` with Java's half-open edges."""
    left = point.x - side_half_size
    bottom = point.y - side_half_size
    size = side_half_size * 2
    return left <= x < left + size and bottom <= y < bottom + size


def robot_rect_contains(target, x: float, y: float) -> bool:
    """``Wave.check`` builds an int rectangle around the target before testing the bullet."""
    width = target.width
    height = target.height
    rect_x = int(target.x - width / 2)
    rect_y = int(target.y - height / 2)
    rect_w = int(width)
    rect_h = int(height)
    return rect_x <= x < rect_x + rect_w and rect_y <= y < rect_y + rect_h


def sorted_by(items: Iterable, key) -> list:
    return sorted(items, key=key)

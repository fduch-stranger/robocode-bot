"""Turn snapshot log and attributes ported from ``lxx.ts_log``."""
from __future__ import annotations

import math

from tomcat_port.lxx_utils import (
    MAX_VELOCITY,
    IntervalDouble,
    lateral_velocity,
    limit,
    normal_relative_angle,
    round_time,
)
from tomcat_port.snapshots import EnemySnapshot, MySnapshot

_LARGE = float(2147483647)


class Attribute:
    _id_sequence = 0

    def __init__(self, name: str, min_value: float, max_value: float, extractor) -> None:
        self.name = name
        self.max_range = IntervalDouble(min_value, max_value)
        self.extractor = extractor
        self.id = Attribute._id_sequence
        Attribute._id_sequence += 1
        self.actual_range = IntervalDouble(_LARGE, -_LARGE - 1)

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Attribute) and self.id == other.id

    def __hash__(self) -> int:
        return self.id


class TurnSnapshot:
    __slots__ = ("time", "round", "my_snapshot", "enemy_snapshot", "next", "round_time")

    def __init__(self, time: int, round_number: int, my_snapshot: MySnapshot, enemy_snapshot: EnemySnapshot) -> None:
        self.time = time
        self.round = round_number
        self.my_snapshot = my_snapshot
        self.enemy_snapshot = enemy_snapshot
        self.next: TurnSnapshot | None = None
        self.round_time = round_time(time, round_number)

    def get_attr_value(self, attribute: Attribute) -> float:
        value = attribute.extractor(self.enemy_snapshot, self.my_snapshot)
        attribute.actual_range.extend(value)
        return value

    def set_next(self, next_snapshot: TurnSnapshot) -> None:
        if self.time + 1 != next_snapshot.time:
            raise RuntimeError("Snapshot skipped")
        self.next = next_snapshot

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TurnSnapshot) and self.round_time == other.round_time

    def __hash__(self) -> int:
        return self.round_time


# Attribute extractors (``AttributeValueExtractor`` implementations).
def _first_bullet_and_flight_time(enemy: EnemySnapshot, me: MySnapshot):
    bullets = me.bullets_in_air
    index = 0
    while True:
        if index == len(bullets):
            return None, 0.0, index
        bullet = bullets[index]
        index += 1
        flight_time = bullet.flight_time(enemy)
        if flight_time >= 1:
            return bullet, flight_time, index


def distance_between(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return me.a_distance(enemy)


def fire_time_diff(enemy: EnemySnapshot, me: MySnapshot) -> float:
    bullets = me.bullets_in_air
    time_till_fire = me.turns_to_gun_cool()
    time_since_fire = (me.snapshot_time - bullets[-1].launch_time) if bullets else 2147483647
    return min(time_till_fire, time_since_fire)


def enemy_acceleration(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return enemy.acceleration


def enemy_bearing_offset_on_first_bullet(enemy: EnemySnapshot, me: MySnapshot) -> float:
    if not me.bullets_in_air:
        return 0.0
    bullet, flight_time, _ = _first_bullet_and_flight_time(enemy, me)
    if bullet is None:
        return 0.0
    from tomcat_port.lxx_utils import lateral_direction

    intercept = enemy.project(enemy.absolute_heading_radians, enemy.speed * flight_time)
    direction = lateral_direction(bullet.owner_state, bullet.target_state)
    return math.degrees(bullet.bearing_offset_radians(intercept)) * direction


def enemy_bearing_offset_on_second_bullet(enemy: EnemySnapshot, me: MySnapshot) -> float:
    bullets = me.bullets_in_air
    if len(bullets) < 2:
        return 0.0
    bullet, flight_time, index = _first_bullet_and_flight_time(enemy, me)
    if bullet is None or index == len(bullets):
        return 0.0
    from tomcat_port.lxx_utils import lateral_direction

    second = bullets[index]
    intercept = enemy.project(enemy.absolute_heading_radians, enemy.speed * flight_time)
    direction = lateral_direction(second.owner_state, second.target_state)
    return math.degrees(second.bearing_offset_radians(intercept)) * direction


def enemy_bearing_to_ho_wall(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return math.degrees(enemy.battle_field.bearing_offset_to_wall(enemy.position, enemy.absolute_heading_radians))


def enemy_bearing_to_me(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return math.degrees(normal_relative_angle(enemy.angle_to(me) - enemy.absolute_heading_radians))


def enemy_distance_to_forward_wall(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return limit(0.0, enemy.position.distance_to_wall(enemy.battle_field, enemy.absolute_heading_radians), _LARGE)


def enemy_heading(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return math.degrees(enemy.absolute_heading_radians)


def enemy_speed(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return enemy.speed


def enemy_time_since_dir_change(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return enemy.snapshot_time - enemy.last_dir_change_time


def enemy_turn_rate(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return math.degrees(enemy.turn_rate_radians)


def enemy_x(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return enemy.x


def enemy_y(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return enemy.y


def first_bullet_flight_time_to_enemy(enemy: EnemySnapshot, me: MySnapshot) -> float:
    bullets = me.bullets_in_air
    if not bullets:
        return 0.0
    index = 0
    while True:
        if index == len(bullets):
            return 0.0
        bullet = bullets[index]
        index += 1
        flight_time = (bullet.owner_state.a_distance(enemy) - bullet.traveled_distance) / bullet.speed
        if flight_time >= 1:
            return flight_time


def last_visited_gf(offset: int):
    def extractor(enemy: EnemySnapshot, me: MySnapshot) -> float:
        visits = enemy.visited_guess_factors
        if len(visits) < offset:
            return 0.0
        return visits[len(visits) - offset]

    return extractor


def my_acceleration(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return me.acceleration


def my_distance_last_10_ticks(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return me.last10_ticks_dist


def my_distance_to_forward_wall(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return limit(0.0, me.position.distance_to_wall(me.battle_field, me.absolute_heading_radians), _LARGE)


def my_lateral_speed(enemy: EnemySnapshot, me: MySnapshot) -> float:
    return abs(lateral_velocity(enemy, me))


# AttributesManager: battle-persistent attribute singletons.
dist_between = Attribute("Distance between", 0, 1700, distance_between)
enemy_x_attr = Attribute("Enemy x", 0, 1200, enemy_x)
enemy_y_attr = Attribute("Enemy y", 0, 1200, enemy_y)
enemy_speed_attr = Attribute("Enemy speed", 0, 8, enemy_speed)
enemy_absolute_heading = Attribute("Enemy heading", 0, 360, enemy_heading)
enemy_acceleration_attr = Attribute("Enemy acceleration", -8, 1, enemy_acceleration)
enemy_turn_rate_attr = Attribute("Enemy turn rate", -10.2, 10.2, enemy_turn_rate)
enemy_distance_to_forward_wall_attr = Attribute("Enemy forward wall distance", 0, 1700, enemy_distance_to_forward_wall)
enemy_bearing_to_forward_wall = Attribute("Enemy bearing to head on wall", -90, 90, enemy_bearing_to_ho_wall)
first_bullet_flight_time_to_enemy_attr = Attribute("First bullet flight time", 0, 75, first_bullet_flight_time_to_enemy)
enemy_bearing_offset_on_first_bullet_attr = Attribute("Enemy bearing offset on first bullet", -50, 50, enemy_bearing_offset_on_first_bullet)
enemy_bearing_offset_on_second_bullet_attr = Attribute("Enemy bearing offset on second bullet", -50, 50, enemy_bearing_offset_on_second_bullet)
enemy_time_since_last_dir_change = Attribute("Enemy time since last direction change", 0, 2000, enemy_time_since_dir_change)
enemy_bearing_to_me_attr = Attribute("Enemy bearing to me", -180, 180, enemy_bearing_to_me)
last_visited_gf1 = Attribute("Enemy last visited gf", -1.1, 1.1, last_visited_gf(1))
last_visited_gf2 = Attribute("Enemy last visited gf", -1.1, 1.1, last_visited_gf(2))
my_lateral_speed_attr = Attribute("My lateral speed", 0, 8, my_lateral_speed)
my_acceleration_attr = Attribute("My acceleration", -2, 1, my_acceleration)
my_dist_to_forward_wall = Attribute("My distance to forward wall", 0, 1700, my_distance_to_forward_wall)
my_dist_last_10_ticks = Attribute("My dist last 10 ticks", 0, MAX_VELOCITY * 10 + 1, my_distance_last_10_ticks)
fire_time_diff_attr = Attribute("Fire time diff", 0, 40, fire_time_diff)


class AttributesManager:
    def __init__(self, robot) -> None:
        self.robot = robot

    def get_turn_snapshot(self, target) -> TurnSnapshot:
        self.robot.current_snapshot.set_bullets(self.robot.bullets_in_air)
        return TurnSnapshot(self.robot.time, self.robot.round, self.robot.current_snapshot, target.current_snapshot)


class TurnSnapshotsLog:
    """Per-round log of one snapshot per turn and target, with gap interpolation."""

    def __init__(self, office) -> None:
        self.office = office
        self.factory: AttributesManager = office.attributes_manager
        self._logs: dict[object, list[TurnSnapshot | None]] = {}

    def get_last_snapshots(self, robot, *indexes: int) -> list[TurnSnapshot | None] | None:
        log = self._logs.get(robot.name)
        if log is None:
            return None
        result: list[TurnSnapshot | None] = []
        for index in indexes:
            idx = len(log) - 1 - index
            result.append(log[idx] if 0 <= idx < len(log) else None)
        return result

    def get_last_snapshot(self, robot, time_delta: int = 0) -> TurnSnapshot | None:
        snapshots = self.get_last_snapshots(robot, time_delta)
        return snapshots[0] if snapshots else None

    def _interpolate(self, log: list, snapshot1: TurnSnapshot, snapshot2: TurnSnapshot) -> None:
        steps = int(self.office.time - snapshot1.time)
        start_time = snapshot1.time
        round_number = snapshot1.round
        for i in range(1, steps):
            # Java computes ``1 / steps * i`` in integer arithmetic, so the factor is 0.
            k = (1 // steps) * i
            interpolated = TurnSnapshot(
                start_time + i,
                round_number,
                MySnapshot(state1=snapshot1.my_snapshot, state2=snapshot2.my_snapshot, interpolation_k=k),
                EnemySnapshot(state1=snapshot1.enemy_snapshot, state2=snapshot2.enemy_snapshot, interpolation_k=k),
            )
            if log and log[-1] is not None:
                log[-1].set_next(interpolated)
            log.append(interpolated)

    def target_updated(self, target) -> None:
        if target.update_time == 0:
            return
        log = self._logs.get(target.name)
        if log is None:
            log = []
            self._logs[target.name] = log
        if not log:
            for _ in range(int(self.office.time)):
                log.append(None)
        snapshot = self.factory.get_turn_snapshot(target)
        if log and log[-1] is not None and log[-1].time + 1 < self.office.time:
            self._interpolate(log, log[-1], snapshot)
        if log and log[-1] is not None:
            if log[-1].time + 1 == snapshot.time:
                log[-1].set_next(snapshot)
            elif log[-1].time == snapshot.time:
                # Two updates in one turn: keep the newest snapshot in the same slot.
                log.pop()
                if log and log[-1] is not None:
                    log[-1].set_next(snapshot)
        log.append(snapshot)

"""The Tomcat Claws gun (``lxx.targeting.tomcat_claws``) and Tomcat Eyes
(``lxx.targeting.tomcat_eyes``).

Tomcat Claws replays the enemy's own past movement from turn snapshots that
are similar to the current one (five kd-tree "data views"), turns each replayed
end position into a bearing-offset interval, and fires at the densest offset.
"""
from __future__ import annotations

import math
from enum import Enum

from tomcat_port.bullets import BearingOffsetDanger, TCPredictionData
from tomcat_port.data_analysis import GunKdTreeEntry, KdTreeAdapter
from tomcat_port.lxx_utils import (
    MAX_VELOCITY,
    RADIANS_0_1,
    RADIANS_0_5,
    RADIANS_10,
    RADIANS_15,
    RADIANS_45,
    DeltaVector,
    IntervalDouble,
    IntervalDoubleDanger,
    IntervalLong,
    LXXPoint,
    Median,
    angle,
    bounding_rect_contains,
    bullet_speed,
    lateral_velocity,
    normal_absolute_angle,
    normal_relative_angle,
    robot_width_in_radians,
    ROBOT_SIDE_HALF_SIZE,
)
from tomcat_port.targeting import GunType
from tomcat_port.ts_log import (
    dist_between,
    enemy_acceleration_attr,
    enemy_bearing_offset_on_first_bullet_attr,
    enemy_bearing_offset_on_second_bullet_attr,
    enemy_bearing_to_forward_wall,
    enemy_bearing_to_me_attr,
    enemy_distance_to_forward_wall_attr,
    enemy_speed_attr,
    enemy_time_since_last_dir_change,
    enemy_turn_rate_attr,
    first_bullet_flight_time_to_enemy_attr,
    last_visited_gf1,
    last_visited_gf2,
)


class SingleSourceDataView:
    def __init__(self, attributes: tuple, weights: tuple[float, float], name: str) -> None:
        self.attributes = attributes
        self.weights = weights
        self.name = name
        self._data_source = KdTreeAdapter(attributes, 50000)

    def get_data_set(self, ts) -> list:
        similar = self._data_source.get_nearest_neighbours(ts)
        if not similar:
            return []
        time_interval = IntervalLong(2147483647, -2147483648)
        dist_interval = IntervalDouble(2147483647, -2147483648)
        for entry in similar:
            time_interval.extend(ts.round_time - entry.ts.round_time)
            dist_interval.extend(entry.distance)
        time_length = time_interval.length
        dist_length = dist_interval.length
        for entry in similar:
            # The Java code mixes an absolute round time with an interval of differences; kept as is.
            time_dist = ((entry.ts.round_time - time_interval.a) / time_length * self.weights[0]) if time_length else 0.0
            loc_dist = ((entry.distance - dist_interval.a) / dist_length * self.weights[1]) if dist_length else 0.0
            entry.normal_weighted_distance = math.sqrt(time_dist * time_dist + loc_dist * loc_dist)
        similar.sort(key=lambda entry: entry.normal_weighted_distance)
        covered: list[IntervalLong] = []
        data_set: list = []
        for entry in similar:
            entry_round_time = entry.ts.round_time
            if any(interval.contains(entry_round_time) for interval in covered):
                continue
            data_set.append(entry.ts)
            covered.append(IntervalLong(entry_round_time - 10, entry_round_time + 10))
            if len(data_set) > 15:
                break
        return data_set

    def add_entry(self, ts) -> None:
        self._data_source.add_entry(GunKdTreeEntry(ts, self.attributes))


# Battle-persistent data views, like the Java statics.
MAIN_DATA_VIEW = SingleSourceDataView(
    (enemy_acceleration_attr, enemy_speed_attr, enemy_distance_to_forward_wall_attr, enemy_bearing_to_forward_wall),
    (0.25, 0.75),
    "Main",
)
AS_DATA_VIEW = SingleSourceDataView(
    (
        enemy_acceleration_attr,
        enemy_speed_attr,
        enemy_distance_to_forward_wall_attr,
        enemy_bearing_to_me_attr,
        first_bullet_flight_time_to_enemy_attr,
        enemy_bearing_offset_on_first_bullet_attr,
        enemy_bearing_offset_on_second_bullet_attr,
    ),
    (0.75, 0.25),
    "Anti-surfer #1",
)
AS_DATA_VIEW2 = SingleSourceDataView(
    (
        enemy_acceleration_attr,
        enemy_speed_attr,
        enemy_distance_to_forward_wall_attr,
        enemy_bearing_to_me_attr,
        first_bullet_flight_time_to_enemy_attr,
        last_visited_gf1,
        last_visited_gf2,
    ),
    (0.75, 0.25),
    "Anti-surfer #2",
)
DISTANCE_DATA_VIEW = SingleSourceDataView(
    (
        enemy_acceleration_attr,
        enemy_speed_attr,
        enemy_distance_to_forward_wall_attr,
        enemy_bearing_to_me_attr,
        dist_between,
        enemy_turn_rate_attr,
    ),
    (0.5, 0.5),
    "Distance",
)
TIME_SINCE_DIR_CHANGE_DATA_VIEW = SingleSourceDataView(
    (
        enemy_acceleration_attr,
        enemy_speed_attr,
        enemy_distance_to_forward_wall_attr,
        enemy_bearing_to_me_attr,
        enemy_time_since_last_dir_change,
        enemy_turn_rate_attr,
    ),
    (0.5, 0.5),
    "Time since dir change",
)
DUEL_VIEWS = (MAIN_DATA_VIEW, AS_DATA_VIEW, AS_DATA_VIEW2, DISTANCE_DATA_VIEW, TIME_SINCE_DIR_CHANGE_DATA_VIEW)


def reset_battle_persistent_state() -> None:
    for view in DUEL_VIEWS:
        view._data_source = KdTreeAdapter(view.attributes, 50000)


class DataViewManager:
    def __init__(self, target_manager, turn_snapshots_log) -> None:
        self.target_manager = target_manager
        self.turn_snapshots_log = turn_snapshots_log

    def on_tick(self) -> None:
        for target in self.target_manager.get_alive_targets():
            last = self.turn_snapshots_log.get_last_snapshot(target)
            if last is None:
                continue
            for view in DUEL_VIEWS:
                view.add_entry(last)

    @staticmethod
    def get_duel_data_views() -> tuple:
        return DUEL_VIEWS


class GunDecision:
    __slots__ = ("gun_turn_angle_radians", "aim_prediction_data")

    def __init__(self, gun_turn_angle_radians: float, aim_prediction_data) -> None:
        self.gun_turn_angle_radians = gun_turn_angle_radians
        self.aim_prediction_data = aim_prediction_data


class _BulletState(Enum):
    COMING = 0
    HITTING = 1
    PASSED = 2


class TomcatClaws:
    BEARING_OFFSET_STEP = RADIANS_0_5
    MAX_BEARING_OFFSET = RADIANS_45
    AIMING_TIME = 2

    def __init__(self, robot, log, data_view_manager: DataViewManager) -> None:
        self.robot = robot
        self.log = log
        self.data_view_manager = data_view_manager
        self.robot_pos_at_fire_time: LXXPoint | None = None
        self.future_poses: list | None = None
        self.bearing_offset_dangers: dict | None = None
        self.best_bearing_offset = 0.0
        self.data_views_predictions: dict = {}

    def get_gun_decision(self, target, fire_power: float) -> GunDecision:
        angle_to_target = self.robot.angle_to(target)
        initial_pos = target.position
        snapshot = self.robot.current_snapshot
        self.robot_pos_at_fire_time = self.robot.project(snapshot.absolute_heading_radians, self.robot.speed * self.AIMING_TIME)
        if self.robot.turns_to_gun_cool() > self.AIMING_TIME or target.energy == 0:
            self.future_poses = None
            return GunDecision(
                self._get_gun_turn_angle(angle_to_target),
                TCPredictionData(self.bearing_offset_dangers, None, self.robot_pos_at_fire_time, initial_pos, {}),
            )
        if self.future_poses is None:
            self.best_bearing_offset = self._get_bearing_offset(target, bullet_speed(fire_power), self.log.get_last_snapshot(target))
        return GunDecision(
            self._get_gun_turn_angle(normal_absolute_angle(self.robot_pos_at_fire_time.angle_to(target) + self.best_bearing_offset)),
            TCPredictionData(self.bearing_offset_dangers, self.future_poses, self.robot_pos_at_fire_time, initial_pos, self.data_views_predictions),
        )

    def _get_gun_turn_angle(self, angle_to_predicted_pos: float) -> float:
        return normal_relative_angle(angle_to_predicted_pos - self.robot.gun_heading_radians)

    def _get_bearing_offset(self, target, speed: float, snapshot) -> float:
        self.data_views_predictions = {}
        self.future_poses = []
        if snapshot is None:
            self.bearing_offset_dangers = {}
            return 0.0
        assert self.robot_pos_at_fire_time is not None
        robot_pos = self.robot_pos_at_fire_time
        bot_intervals: list[IntervalDoubleDanger] = []
        interval_cache: dict[tuple[float, float], IntervalDoubleDanger] = {}
        future_poses_cache: dict = {}
        angle_to_target = robot_pos.angle_to(target)
        for view in self.data_view_manager.get_duel_data_views():
            view_future_poses = self._get_future_poses(target, view.get_data_set(snapshot), speed, future_poses_cache)
            view_intervals = []
            for pnt in view_future_poses:
                key = (pnt.x, pnt.y)
                cached = interval_cache.get(key)
                if cached is None:
                    angle_to_pnt = robot_pos.angle_to(pnt)
                    bearing_offset = normal_relative_angle(angle_to_pnt - angle_to_target)
                    bot_width = robot_width_in_radians(angle_to_pnt, robot_pos.a_distance(pnt)) * 0.75
                    bo1 = bearing_offset - bot_width
                    bo2 = bearing_offset + bot_width
                    cached = IntervalDoubleDanger(min(bo1, bo2), max(bo1, bo2), 1.0)
                    interval_cache[key] = cached
                bot_intervals.append(cached)
                view_intervals.append(cached)
            self.data_views_predictions[view] = view_intervals
        bot_intervals.sort(key=lambda interval: interval.a)

        self.bearing_offset_dangers = {}
        max_danger = BearingOffsetDanger(0.0, 0.0)
        wave_point = -self.MAX_BEARING_OFFSET
        upper = self.MAX_BEARING_OFFSET + RADIANS_0_1
        while wave_point <= upper:
            danger = 0.0
            for interval in bot_intervals:
                if interval.a > wave_point:
                    break
                if interval.b < wave_point:
                    continue
                center = interval.center()
                length = interval.length
                if abs(wave_point - center) < length / 4:
                    danger += interval.danger
                else:
                    danger += (length / 4) / abs(wave_point - center) * interval.danger
            self.bearing_offset_dangers[wave_point] = danger
            if danger > max_danger.danger:
                max_danger = BearingOffsetDanger(wave_point, danger)
            wave_point += self.BEARING_OFFSET_STEP
        return max_danger.bearing_offset

    def _get_future_poses(self, target, starts, speed: float, cache: dict) -> list[LXXPoint]:
        future_poses: list[LXXPoint] = []
        for start in starts:
            if start in cache:
                future_pos = cache[start]
            else:
                future_pos = self._get_future_pos(target, start, speed)
                cache[start] = future_pos
            if future_pos is not None:
                future_poses.append(future_pos)
                assert self.future_poses is not None
                self.future_poses.append(future_pos)
        return future_poses

    def _get_future_pos(self, target, start, speed: float) -> LXXPoint | None:
        assert self.robot_pos_at_fire_time is not None
        robot_pos = self.robot_pos_at_fire_time
        target_pos = target.position
        future_pos = LXXPoint.of(target_pos)
        current = self._skip(start.next, self.AIMING_TIME)
        battle_field = self.robot.battle_field
        absolute_heading = target.absolute_heading_radians
        speed_sum = speed + MAX_VELOCITY
        travelled = speed
        while self._is_bullet_hit_enemy(future_pos, travelled) is _BulletState.COMING:
            if current is None:
                return None
            delta = self._enemy_delta_vector(start, current)
            alpha = absolute_heading + delta.alpha_radians
            future_pos = target_pos.project(alpha, delta.length)
            if not battle_field.contains(future_pos):
                return None
            time_delta = current.time - start.time - self.AIMING_TIME
            travelled = time_delta * speed
            min_flight_time = max(int((robot_pos.a_distance(future_pos) - travelled) / speed_sum) - 1, 1)
            current = self._skip(current, min_flight_time)
        return future_pos

    @staticmethod
    def _enemy_delta_vector(ts1, ts2) -> DeltaVector:
        enemy_heading = ts1.enemy_snapshot.absolute_heading_radians
        x1, y1 = ts1.enemy_snapshot.x, ts1.enemy_snapshot.y
        x2, y2 = ts2.enemy_snapshot.x, ts2.enemy_snapshot.y
        alpha = angle(x1, y1, x2, y2)
        return DeltaVector(normal_relative_angle(alpha - enemy_heading), math.hypot(x2 - x1, y2 - y1))

    @staticmethod
    def _skip(start, count: int):
        for _ in range(count):
            if start is None:
                return None
            start = start.next
        return start

    def _is_bullet_hit_enemy(self, predicted_pos: LXXPoint, travelled: float) -> _BulletState:
        assert self.robot_pos_at_fire_time is not None
        robot_pos = self.robot_pos_at_fire_time
        angle_to_predicted = robot_pos.angle_to(predicted_pos)
        bullet_pos = robot_pos.project(angle_to_predicted, travelled)
        if bounding_rect_contains(predicted_pos, bullet_pos.x, bullet_pos.y):
            return _BulletState.HITTING
        if travelled > robot_pos.a_distance(predicted_pos) + ROBOT_SIDE_HALF_SIZE:
            return _BulletState.PASSED
        return _BulletState.COMING


class TargetingProfile:
    def __init__(self) -> None:
        self.dist_with_ho_bo_median = Median(1000)
        self.dist_with_linear_bo_median = Median(1000)
        self.bearing_offsets_interval = IntervalDouble(0, 0)
        self.bearing_offsets = 0

    def add_bearing_offset(self, enemy, me, bearing_offset_radians: float, speed: float) -> None:
        self.bearing_offsets += 1
        self.dist_with_ho_bo_median.add_value(abs(bearing_offset_radians))
        linear_bo = abs(lateral_velocity(enemy, me) / speed)
        self.dist_with_linear_bo_median.add_value(abs(bearing_offset_radians - linear_bo))
        self.bearing_offsets_interval.extend(bearing_offset_radians)


_TARGETING_PROFILES: dict[object, TargetingProfile] = {}


def reset_targeting_profiles() -> None:
    _TARGETING_PROFILES.clear()


class TomcatEyes:
    """Classifies the enemy gun from the bullets that hit us (BulletManagerListener)."""

    def bullet_hit(self, bullet) -> None:
        self._process_bullet(bullet)

    def bullet_intercepted(self, bullet) -> None:
        self._process_bullet(bullet)

    def bullet_passing(self, bullet) -> None:
        return None

    def bullet_miss(self, bullet) -> None:
        return None

    def bullet_fired(self, bullet) -> None:
        return None

    def _process_bullet(self, bullet) -> None:
        bearing_offset = bullet.real_bearing_offset_radians
        profile = self._get_targeting_profile(bullet.source_state.name)
        profile.add_bearing_offset(
            bullet.target_state, bullet.wave.source_state, bearing_offset * bullet.target_lateral_direction, bullet.speed
        )

    @staticmethod
    def _get_targeting_profile(name) -> TargetingProfile:
        profile = _TARGETING_PROFILES.get(name)
        if profile is None:
            profile = TargetingProfile()
            _TARGETING_PROFILES[name] = profile
        return profile

    def get_enemy_gun_type(self, name) -> GunType:
        profile = self._get_targeting_profile(name)
        if profile.bearing_offsets == 0:
            return GunType.UNKNOWN
        if profile.dist_with_ho_bo_median.get_median() < RADIANS_10 and profile.bearing_offsets_interval.a > -RADIANS_15:
            return GunType.HEAD_ON
        if profile.dist_with_linear_bo_median.get_median() < RADIANS_15 and profile.bearing_offsets_interval.a > -RADIANS_15:
            return GunType.LINEAR
        return GunType.ADVANCED

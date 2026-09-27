"""``lxx.bullets.enemy.AdvancedEnemyGunModel``: predicts where the enemy's bullets go.

Each enemy has a ``LogSet`` of 31 logs keyed by attribute subsets. Hit logs
learn from real hits, visit logs from every wave that passes us; the best logs
by recent efficiency provide the bearing offsets the movement surfs against.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tomcat_port.bullets import BearingOffsetDanger, EnemyBulletPredictionData
from tomcat_port.data_analysis import LxxDataPoint, RangeStore
from tomcat_port.lxx_utils import (
    AvgValue,
    HitRate,
    IntervalDouble,
    bullet_speed,
    lateral_direction,
    limit,
    max_escape_angle,
    max_escape_angle_precise,
    robot_width_in_radians_between,
    round_time,
)
from tomcat_port.targeting import GunType
from tomcat_port.ts_log import (
    dist_between,
    my_acceleration_attr,
    my_dist_last_10_ticks,
    my_dist_to_forward_wall,
    my_lateral_speed_attr,
)

FIRE_DETECTION_LATENCY = 2
BEST_LOGS_COUNT = 3
BULLETS_PER_LOG = 11


@dataclass(frozen=True)
class GuessFactor:
    guess_factor: float


class LogType(Enum):
    HIT_LOG = "hit"
    VISIT_LOG = "visit"


_HALF_SIDE_LENGTH = {
    my_lateral_speed_attr: 2.0,
    my_acceleration_attr: 0.0,
    dist_between: 75.0,
    my_dist_to_forward_wall: 50.0,
    my_dist_last_10_ticks: 20.0,
}


class Log:
    def __init__(self, office, attrs: tuple, log_type: LogType) -> None:
        self.office = office
        self.attrs = attrs
        self.type = log_type
        self.store = RangeStore(attrs)
        self.short_avg_hit_rate = AvgValue(9)
        self.mid_avg_hit_rate = AvgValue(45)
        self.long_avg_hit_rate = AvgValue(5000)
        self.short_avg_miss_rate = AvgValue(9)
        self.mid_avg_miss_rate = AvgValue(45)
        self.long_avg_miss_rate = AvgValue(5000)
        self.enemy_hit_rate = HitRate()
        self.usage = 0
        self.last_update_round_time = 0

    def get_bearing_offsets(self, predicate, fire_power: float, bullet_shadows) -> list[BearingOffsetDanger]:
        entries = self.store.range_search(self._get_range(predicate))
        entries.sort(key=lambda entry: entry.ts.round_time, reverse=True)
        direction = lateral_direction(predicate.enemy_snapshot, predicate.my_snapshot)
        mea = max_escape_angle(bullet_speed(fire_power))
        bearing_offsets: list[BearingOffsetDanger] = []
        for entry in entries:
            if len(bearing_offsets) == BULLETS_PER_LOG:
                break
            bearing_offset = entry.payload.guess_factor * direction * mea
            if any(shadow.contains(bearing_offset) for shadow in bullet_shadows):
                continue
            bearing_offsets.append(BearingOffsetDanger(bearing_offset, 1.0))
        return bearing_offsets

    def _get_range(self, center) -> list[IntervalDouble]:
        ranges = []
        for attr in self.attrs:
            delta = _HALF_SIDE_LENGTH[attr]
            value = center.get_attr_value(attr)
            low = round(limit(attr.actual_range.a, value - delta, attr.actual_range.b))
            high = round(limit(attr.actual_range.a, value + delta, attr.actual_range.b))
            ranges.append(IntervalDouble(low, high))
        return ranges

    def add_entry(self, location, payload: GuessFactor) -> None:
        self.store.insert(LxxDataPoint.create_plain_point(location, payload, self.attrs))
        self.last_update_round_time = round_time(self.office.time, self.office.robot.round)


class LogSet:
    def __init__(self, office) -> None:
        self.office = office
        self.hit_logs_set: list[Log] = []
        self.visit_logs_set: list[Log] = []
        self.short_logs: list[Log] = []
        self.mid_logs: list[Log] = []
        self.long_logs: list[Log] = []
        self.enemy_hit_rate_logs: list[Log] = []

    @property
    def best_log_lists(self) -> list[list[Log]]:
        return [self.short_logs, self.mid_logs, self.long_logs, self.enemy_hit_rate_logs]

    def learn_visit(self, location, payload: GuessFactor) -> None:
        for log in self.visit_logs_set:
            log.add_entry(location, payload)

    def get_prediction_data(self, ts, target, bullet_shadows) -> EnemyBulletPredictionData:
        bearing_offsets: list[BearingOffsetDanger] = []
        best_logs_bearing_offsets: dict = {}
        prediction_round_time = round_time(target.time, target.round)
        for log in self.get_best_logs():
            log_bos = log.get_bearing_offsets(ts, target.fire_power, bullet_shadows)
            best_logs_bearing_offsets[log] = log_bos
            bearing_offsets.extend(log_bos)
            log.usage += 1
        if not bearing_offsets:
            gun_type = self.office.tomcat_eyes.get_enemy_gun_type(target.name)
            self._fill_with_simple_bos(ts, target, bearing_offsets, gun_type)
        return EnemyBulletPredictionData(bearing_offsets, prediction_round_time, best_logs_bearing_offsets, ts, bullet_shadows)

    def update_best_logs(self) -> None:
        self.short_logs.sort(key=lambda log: -(log.short_avg_hit_rate.current_value - log.short_avg_miss_rate.current_value))
        self.mid_logs.sort(key=lambda log: -(log.mid_avg_hit_rate.current_value - log.mid_avg_miss_rate.current_value))
        self.long_logs.sort(key=lambda log: -(log.long_avg_hit_rate.current_value - log.long_avg_miss_rate.current_value))
        self.enemy_hit_rate_logs.sort(
            key=lambda log: (1, 0.0) if log.enemy_hit_rate.get_fire_count() == 0 else (0, log.enemy_hit_rate.get_hit_rate())
        )

    def get_best_logs(self) -> list[Log]:
        best: list[Log] = []
        hit_rate = self.office.statistics_manager.enemy_hit_rate.get_hit_rate()
        for logs in self.best_log_lists:
            added = 0
            for log in logs:
                if log.type is LogType.VISIT_LOG and hit_rate < 0.05:
                    continue
                if log not in best:
                    best.append(log)
                added += 1
                if added == BEST_LOGS_COUNT + 1:
                    break
        return best

    def _fill_with_simple_bos(self, ts, target, bearing_offsets: list[BearingOffsetDanger], gun_type: GunType) -> None:
        direction = lateral_direction(ts.enemy_snapshot, ts.my_snapshot)
        speed = bullet_speed(target.fire_power)
        mea = max_escape_angle_precise(target, self.office.robot.current_snapshot, speed)
        if gun_type is not GunType.HEAD_ON:
            if direction != 0:
                bearing_offsets.append(BearingOffsetDanger(mea * direction, 1.0))
            else:
                bearing_offsets.append(BearingOffsetDanger(mea, 1.0))
                bearing_offsets.append(BearingOffsetDanger(-mea, 1.0))
        if gun_type in (GunType.UNKNOWN, GunType.HEAD_ON):
            bearing_offsets.append(BearingOffsetDanger(0.0, 1.0))

    def learn(self, bullet, is_hit: bool) -> None:
        self._recalculate_efficiency(bullet, self.visit_logs_set, is_hit)
        self._recalculate_efficiency(bullet, self.hit_logs_set, is_hit)
        self.update_best_logs()
        if is_hit:
            direction = bullet.target_lateral_direction
            guess_factor = bullet.real_bearing_offset_radians / max_escape_angle(bullet.speed) * direction
            for log in self.hit_logs_set:
                log.add_entry(bullet.aim_prediction_data.ts, GuessFactor(guess_factor))

    def _recalculate_efficiency(self, bullet, logs: list[Log], is_hit: bool) -> None:
        flight_time = bullet.fire_position.a_distance(bullet.target_state) / bullet.speed
        prediction = bullet.aim_prediction_data
        for log in logs:
            bearing_offsets = prediction.get_bearing_offsets(log)
            if bearing_offsets is None:
                bearing_offsets = log.get_bearing_offsets(prediction.ts, bullet.bullet.power, bullet.bullet_shadows)
            efficiency = self._calculate_efficiency(bullet, bearing_offsets, is_hit) * flight_time
            if is_hit:
                log.short_avg_hit_rate.add_value(efficiency)
                log.mid_avg_hit_rate.add_value(efficiency)
                log.long_avg_hit_rate.add_value(efficiency)
            else:
                log.short_avg_miss_rate.add_value(efficiency)
                log.mid_avg_miss_rate.add_value(efficiency)
                log.long_avg_miss_rate.add_value(efficiency)

    @staticmethod
    def _calculate_efficiency(bullet, bearing_offsets: list[BearingOffsetDanger], is_hit: bool) -> float:
        if is_hit:
            half_size = robot_width_in_radians_between(bullet.fire_position, bullet.target) / 2
            current_bo = bullet.real_bearing_offset_radians
            effective = IntervalDouble(current_bo - half_size, current_bo + half_size)
        else:
            hit_interval = bullet.wave.hit_bearing_offset_interval
            effective = IntervalDouble(
                hit_interval.center() - hit_interval.length * 0.4,
                hit_interval.center() + hit_interval.length * 0.4,
            )
        total = 0.0
        real = 0.0
        for past in bearing_offsets:
            total += past.danger
            if effective.contains(past.bearing_offset):
                real += past.danger
        return real / total if total else 0.0


# Battle-persistent like the Java static map.
_LOG_SETS: dict[object, LogSet] = {}


def reset_battle_persistent_state() -> None:
    _LOG_SETS.clear()


class AdvancedEnemyGunModel:
    def __init__(self, office) -> None:
        self.office = office

    def get_prediction_data(self, target, turn_snapshot, bullet_shadows) -> EnemyBulletPredictionData:
        return self._get_log_set(target.name).get_prediction_data(turn_snapshot, target, bullet_shadows)

    def process_hit(self, bullet) -> None:
        log_set = self._get_log_set(bullet.source_state.name)
        self._update_enemy_hit_rate(log_set, bullet.aim_prediction_data, True)
        log_set.learn(bullet, True)

    def process_intercept(self, bullet) -> None:
        self._get_log_set(bullet.source_state.name).learn(bullet, True)

    def process_miss(self, bullet) -> None:
        log_set = self._get_log_set(bullet.source_state.name)
        self._update_enemy_hit_rate(log_set, bullet.aim_prediction_data, False)
        log_set.learn(bullet, False)

    def process_visit(self, bullet) -> None:
        direction = bullet.target_lateral_direction
        undirected = bullet.wave.hit_bearing_offset_interval.center() / max_escape_angle(bullet.speed)
        self._get_log_set(bullet.source_state.name).learn_visit(bullet.aim_prediction_data.ts, GuessFactor(undirected * direction))

    def update_bullet_prediction_data(self, bullet) -> None:
        current_round_time = round_time(self.office.time, self.office.robot.round)
        self._update_old_data(bullet)
        self._calculate_new_data(bullet, current_round_time)

    @staticmethod
    def _update_enemy_hit_rate(log_set: LogSet, prediction: EnemyBulletPredictionData, is_hit: bool) -> None:
        for log in log_set.hit_logs_set + log_set.visit_logs_set:
            if prediction.get_bearing_offsets(log) is not None:
                if is_hit:
                    log.enemy_hit_rate.hit()
                else:
                    log.enemy_hit_rate.miss()

    def _update_old_data(self, bullet) -> None:
        prediction = bullet.aim_prediction_data
        shadows = bullet.bullet_shadows
        shadows_changed = len(shadows) != len(prediction.bullet_shadows)
        for log in prediction.logs:
            if not self._needs_update(log, bullet, prediction, shadows_changed):
                continue
            prediction.add_log_prediction(log, log.get_bearing_offsets(prediction.ts, bullet.bullet.power, shadows))
        if shadows_changed:
            prediction.bullet_shadows = list(shadows)

    def _calculate_new_data(self, bullet, current_round_time: int) -> None:
        prediction = bullet.aim_prediction_data
        log_set = self._get_log_set(bullet.source_state.name)
        bearing_offsets: list[BearingOffsetDanger] = []
        for log in log_set.get_best_logs():
            log_bos = prediction.get_bearing_offsets(log)
            if log_bos is None:
                log_bos = log.get_bearing_offsets(prediction.ts, bullet.bullet.power, bullet.bullet_shadows)
                prediction.add_log_prediction(log, log_bos)
            bearing_offsets.extend(log_bos)
        if bearing_offsets:
            prediction.set_predicted_bearing_offsets(bearing_offsets)
            prediction.prediction_round_time = current_round_time

    @staticmethod
    def _needs_update(log: Log, bullet, prediction: EnemyBulletPredictionData, shadows_changed: bool) -> bool:
        if shadows_changed:
            return True
        if log.type is LogType.HIT_LOG and log.last_update_round_time > prediction.prediction_round_time:
            return True
        bos = prediction.get_bearing_offsets(log) or []
        return any(shadow.contains(bo.bearing_offset) for shadow in bullet.bullet_shadows for bo in bos)

    def _get_log_set(self, enemy_name) -> LogSet:
        log_set = _LOG_SETS.get(enemy_name)
        if log_set is None:
            log_set = self._create_log_set()
            _LOG_SETS[enemy_name] = log_set
        else:
            log_set.office = self.office
            for log in log_set.hit_logs_set + log_set.visit_logs_set:
                log.office = self.office
        return log_set

    def _create_log_set(self) -> LogSet:
        log_set = LogSet(self.office)
        log_set.visit_logs_set.extend(
            self._create_logs((my_lateral_speed_attr, my_acceleration_attr, dist_between, my_dist_to_forward_wall), (), 1, LogType.VISIT_LOG)
        )
        log_set.hit_logs_set.extend(
            self._create_logs((my_acceleration_attr, dist_between, my_dist_to_forward_wall, my_dist_last_10_ticks), (my_lateral_speed_attr,), 1, LogType.HIT_LOG)
        )
        for logs in (log_set.short_logs, log_set.mid_logs, log_set.long_logs, log_set.enemy_hit_rate_logs):
            logs.extend(log_set.hit_logs_set)
            logs.extend(log_set.visit_logs_set)
        log_set.update_best_logs()
        return log_set

    def _create_logs(self, possible: tuple, required: tuple, min_elements: int, log_type: LogType) -> list[Log]:
        logs: list[Log] = []
        for mask in range(2 ** len(possible)):
            attrs = list(required)
            for bit, attr in enumerate(possible):
                if mask & (1 << bit):
                    attrs.append(attr)
            if len(attrs) < min_elements:
                continue
            logs.append(Log(self.office, tuple(attrs), log_type))
        return logs

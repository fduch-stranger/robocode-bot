"""Bullet models ported from ``lxx.bullets``: ``LXXBullet``, ``BulletSnapshot``,
``BulletShadow``, ``BearingOffsetDanger`` and the aiming prediction data classes.

Painting code was dropped; only the state the decisions read is kept.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tomcat_port.lxx_utils import IntervalDouble, LXXPoint, PointLike, bullet_speed, lateral_direction, normal_relative_angle


class BulletState(Enum):
    ON_AIR = "on_air"
    INTERCEPTED = "intercepted"
    HITTED = "hitted"
    MISSED = "missed"


@dataclass
class BulletInfo:
    """The engine bullet facts Tomcat read from ``robocode.Bullet``."""

    heading_radians: float
    power: float
    x: float
    y: float
    bullet_id: int = -1

    @property
    def speed(self) -> float:
        return bullet_speed(self.power)


@dataclass(order=True)
class BearingOffsetDanger:
    bearing_offset: float
    danger: float


class BulletShadow(IntervalDouble):
    __slots__ = ("is_passed",)

    def __init__(self, a: float, b: float) -> None:
        super().__init__(a, b)
        self.is_passed = False


class BulletSnapshot:
    __slots__ = ("owner_state", "target_state", "no_bearing_offset_radians", "traveled_distance", "speed", "launch_time")

    def __init__(self, owner_state, target_state, no_bearing_offset_radians: float, traveled_distance: float, speed: float, launch_time: int) -> None:
        self.owner_state = owner_state
        self.target_state = target_state
        self.no_bearing_offset_radians = no_bearing_offset_radians
        self.traveled_distance = traveled_distance
        self.speed = speed
        self.launch_time = launch_time

    def flight_time(self, pnt: PointLike) -> float:
        return (self.owner_state.a_distance(pnt) - self.traveled_distance) / self.speed

    def bearing_offset_radians(self, pnt: PointLike) -> float:
        return normal_relative_angle(self.owner_state.angle_to(pnt) - self.no_bearing_offset_radians)


class AimingPredictionData:
    def __init__(self, ts, prediction_round_time: int) -> None:
        self.ts = ts
        self.prediction_round_time = prediction_round_time


class EnemyBulletPredictionData(AimingPredictionData):
    def __init__(self, predicted_bearing_offsets: list[BearingOffsetDanger], prediction_round_time: int, all_logs_predictions: dict, ts, bullet_shadows) -> None:
        super().__init__(ts, prediction_round_time)
        self.all_logs_predictions = all_logs_predictions
        self.predicted_bearing_offsets = sorted(predicted_bearing_offsets)
        self.bullet_shadows = list(bullet_shadows) if bullet_shadows is not None else []

    def get_bearing_offsets(self, log) -> list[BearingOffsetDanger] | None:
        return self.all_logs_predictions.get(log)

    @property
    def logs(self):
        return list(self.all_logs_predictions.keys())

    def set_predicted_bearing_offsets(self, predicted_bearing_offsets: list[BearingOffsetDanger]) -> None:
        self.predicted_bearing_offsets = sorted(predicted_bearing_offsets)

    def add_log_prediction(self, log, bearing_offsets: list[BearingOffsetDanger]) -> None:
        self.all_logs_predictions[log] = bearing_offsets


class TCPredictionData(AimingPredictionData):
    def __init__(self, matches, predicted_poses, robot_pos, initial_pos, data_views_predictions) -> None:
        super().__init__(None, -1)
        self.matches = matches
        self.predicted_poses = predicted_poses
        self.robot_pos = robot_pos
        self.initial_pos = initial_pos
        self.data_views_predictions = data_views_predictions


class LXXBullet:
    def __init__(self, bullet: BulletInfo, wave, aim_prediction_data: AimingPredictionData | None = None) -> None:
        self.bullet = bullet
        self.wave = wave
        self.aim_prediction_data = aim_prediction_data
        self.fire_position = LXXPoint.of(wave.source_state)
        self.state = BulletState.ON_AIR
        self._bullet_shadows: dict[LXXBullet, BulletShadow] = {}
        self.merged_shadows: list[IntervalDouble] = []
        wave.carried_bullet = self

    @property
    def target(self):
        return self.wave.target

    @property
    def traveled_distance(self) -> float:
        return self.wave.traveled_distance

    @property
    def heading_radians(self) -> float:
        return self.bullet.heading_radians

    @property
    def speed(self) -> float:
        return self.bullet.speed

    @property
    def target_state(self):
        return self.wave.target_state

    @property
    def source_state(self):
        return self.wave.source_state

    @property
    def distance_to_target(self) -> float:
        return self.wave.source_state.a_distance(self.wave.target)

    @property
    def no_bearing_offset(self) -> float:
        return self.wave.no_bearing_offset

    @property
    def real_bearing_offset_radians(self) -> float:
        return normal_relative_angle(self.bullet.heading_radians - self.wave.no_bearing_offset)

    def bearing_offset_radians(self, pnt: PointLike) -> float:
        return normal_relative_angle(self.fire_position.angle_to(pnt) - self.wave.no_bearing_offset)

    @property
    def target_lateral_direction(self) -> float:
        return lateral_direction(self.fire_position, self.target_state)

    def flight_time(self, pnt: PointLike) -> float:
        return (self.fire_position.a_distance(pnt) - self.traveled_distance) / self.speed

    def add_bullet_shadow(self, bullet: LXXBullet, shadow: BulletShadow) -> None:
        self._bullet_shadows[bullet] = shadow
        for merged in self.merged_shadows:
            if merged.intersects(shadow):
                merged.merge(shadow)
                return
        self.merged_shadows.append(IntervalDouble.of(shadow))

    def get_bullet_shadow(self, bullet: LXXBullet) -> BulletShadow | None:
        return self._bullet_shadows.get(bullet)

    @property
    def bullet_shadows(self) -> list[BulletShadow]:
        return list(self._bullet_shadows.values())

    def remove_bullet_shadow(self, bullet: LXXBullet) -> None:
        self._bullet_shadows.pop(bullet, None)
        self.merged_shadows = []
        for shadow in self._bullet_shadows.values():
            for merged in self.merged_shadows:
                if merged.intersects(shadow):
                    merged.merge(shadow)
                    break
            else:
                self.merged_shadows.append(IntervalDouble.of(shadow))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LXXBullet) and self.wave == other.wave

    def __hash__(self) -> int:
        return hash(self.wave)

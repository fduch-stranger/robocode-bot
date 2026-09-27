"""Enemy tracking ported from ``lxx.targeting``: ``Target``, ``TargetData`` and
``TargetManager``.

Engine events are delivered as the small records in this module (built by the
bot adapter from Tank Royale events), stamped with the turn they arrived in.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tomcat_port.lxx_utils import (
    DECELERATION,
    INITIAL_GUN_HEAT,
    RADIANS_30,
    ROBOT_HIT_DAMAGE,
    AvgValue,
    LXXPoint,
    PointLike,
    angles_diff,
    bullet_damage,
    gun_heat_for,
    normal_absolute_angle,
    returned_energy,
    wall_hit_damage,
)
from tomcat_port.snapshots import EnemySnapshot


class GunType(Enum):
    UNKNOWN = "unknown"
    HEAD_ON = "head_on"
    LINEAR = "linear"
    ADVANCED = "advanced"


@dataclass
class ScannedEvent:
    time: int
    x: float
    y: float
    heading_radians: float
    velocity: float
    energy: float


@dataclass
class HitByBulletEvent:
    """The enemy's bullet hit us: the enemy collects energy."""

    time: int
    bullet_power: float


@dataclass
class BulletHitEvent:
    """Our bullet hit the enemy."""

    time: int
    bullet_power: float
    bullet_x: float
    bullet_y: float
    energy: float


@dataclass
class HitRobotEvent:
    time: int
    x: float
    y: float
    energy: float


@dataclass
class RobotDeathEvent:
    time: int


class TargetData:
    def __init__(self) -> None:
        self.visited_guess_factors: list[float] = []
        self.avg_fire_delay = AvgValue(2000)
        self.min_fire_energy = float(2147483647)

    def add_visit(self, guess_factor: float) -> None:
        self.visited_guess_factors.append(guess_factor)

    def add_fire_delay(self, fire_delay: int) -> None:
        self.avg_fire_delay.add_value(fire_delay)

    def get_avg_fire_delay(self) -> float:
        return self.avg_fire_delay.current_value

    def set_min_fire_energy(self, fire_energy: float) -> None:
        self.min_fire_energy = min(fire_energy, self.min_fire_energy)


class Target(PointLike):
    def __init__(self, owner, name, target_data: TargetData) -> None:
        self.owner = owner
        self.name = name
        self.target_data = target_data
        self._events: list = []
        self.is_alive = True
        self.is_ramming_now = False
        self.prev_snapshot: EnemySnapshot | None = None
        self.current_snapshot: EnemySnapshot | None = None
        self.position = LXXPoint()
        self.energy = 100.0
        self.enemy_last_hit_time = -1
        self.enemy_last_collected_energy = 0.0
        self.my_last_hit_time = -1
        self.my_last_damage = 0.0
        self.heading_radians = 0.0
        self.velocity = 0.0
        self.enemy_hit_robot_energy_loss = 0.0
        self.enemy_last_fire_power = 0.0
        self.gun_heat = 0.0
        self.fire_ready_time = 0

    def add_event(self, event) -> None:
        self._events.append(event)

    def update(self) -> None:
        self.prev_snapshot = self.current_snapshot
        self._update_robot_state()
        if self.prev_snapshot is None:
            self.current_snapshot = EnemySnapshot(self, visits=self.target_data.visited_guess_factors)
        else:
            self.current_snapshot = EnemySnapshot(self, prev_state=self.prev_snapshot)
        self._update_state()
        self.is_ramming_now = (
            angles_diff(self.angle_to(self.owner), self.absolute_heading_radians) < RADIANS_30 and self.speed > 0
        ) or self.owner.a_distance(self) < 50
        self._events = []

    def _update_state(self) -> None:
        self.enemy_hit_robot_energy_loss = 0.0
        if self.prev_snapshot is None:
            self.gun_heat = INITIAL_GUN_HEAT - self.owner.gun_cooling_rate * (self.owner.time - 1)
        elif self.is_fire_last_tick():
            fire_power = self.expected_energy() - self.energy
            self.gun_heat = gun_heat_for(fire_power)
            self.enemy_last_fire_power = fire_power
            self.target_data.add_fire_delay(self.owner.time - self.fire_ready_time)
            self.target_data.set_min_fire_energy(self.prev_snapshot.energy)
        self.gun_heat = max(0.0, self.gun_heat - self.owner.gun_cooling_rate)
        if self.gun_heat == 0:
            self.fire_ready_time = self.owner.time
        assert self.current_snapshot is not None
        self.current_snapshot.set_gun_heat(self.gun_heat)

    def _update_robot_state(self) -> None:
        for event in self._events:
            if isinstance(event, ScannedEvent):
                self.position = LXXPoint(event.x, event.y)
                self.heading_radians = event.heading_radians
                self.velocity = event.velocity
                self.energy = event.energy
                self.is_alive = True
            elif isinstance(event, HitRobotEvent):
                self.position = LXXPoint(event.x, event.y)
                self.energy = event.energy
                self.enemy_hit_robot_energy_loss += ROBOT_HIT_DAMAGE
            elif isinstance(event, BulletHitEvent):
                self.my_last_hit_time = event.time
                self.my_last_damage = bullet_damage(event.bullet_power)
                self.position = LXXPoint(event.bullet_x, event.bullet_y)
                self.energy = event.energy
            elif isinstance(event, HitByBulletEvent):
                assert self.prev_snapshot is not None
                self.energy = self.prev_snapshot.energy + returned_energy(event.bullet_power)
                self.enemy_last_hit_time = event.time
                self.enemy_last_collected_energy = returned_energy(event.bullet_power)
            elif isinstance(event, RobotDeathEvent):
                self.energy = 0.0

    @property
    def update_time(self) -> int:
        assert self.current_snapshot is not None
        return self.current_snapshot.snapshot_time

    @property
    def time(self) -> int:
        return self.owner.time

    @property
    def round(self) -> int:
        return self.owner.round

    @property
    def x(self) -> float:
        return self.position.x

    @property
    def y(self) -> float:
        return self.position.y

    @property
    def speed(self) -> float:
        return abs(self.velocity)

    @property
    def absolute_heading_radians(self) -> float:
        if self.velocity >= 0:
            return self.heading_radians
        return normal_absolute_angle(self.heading_radians + 3.141592653589793)

    @property
    def battle_field(self):
        return self.owner.battle_field

    @property
    def width(self) -> float:
        return self.owner.width

    @property
    def height(self) -> float:
        return self.owner.height

    @property
    def fire_power(self) -> float:
        return self.enemy_last_fire_power

    def set_not_alive(self) -> None:
        self.is_alive = False

    def is_fire_last_tick(self) -> bool:
        if self.prev_snapshot is not None and self.prev_snapshot.gun_heat >= self.owner.gun_cooling_rate:
            return False
        energy_diff = self.expected_energy() - self.energy
        return 0 < energy_diff < 3.1

    def expected_energy(self) -> float:
        if self.prev_snapshot is None:
            return self.energy
        expected = self.prev_snapshot.energy
        if self.owner.time == self.my_last_hit_time:
            expected -= self.my_last_damage
        if self.owner.time == self.enemy_last_hit_time:
            expected += self.enemy_last_collected_energy
        if self.is_hit_wall():
            expected -= wall_hit_damage(abs(self.prev_snapshot.velocity) + self.prev_snapshot.acceleration)
        expected -= self.enemy_hit_robot_energy_loss
        return expected

    def is_hit_wall(self) -> bool:
        prev = self.prev_snapshot
        if prev is None:
            return False
        if abs(prev.velocity) - abs(self.velocity) > DECELERATION:
            return True
        assert self.current_snapshot is not None
        projected = prev.position.project(self.current_snapshot.absolute_heading_radians, abs(self.velocity))
        return prev.position.a_distance(self.position) - prev.position.a_distance(projected) < -1.1

    def add_visit(self, guess_factor: float) -> None:
        self.target_data.add_visit(guess_factor)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Target) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


# Battle-persistent, like the Java static map.
_TARGET_DATAS: dict[object, TargetData] = {}


def reset_battle_persistent_state() -> None:
    _TARGET_DATAS.clear()


class TargetManager:
    def __init__(self, robot) -> None:
        self.robot = robot
        self._targets: dict[object, Target] = {}
        self._alive_targets: list[Target] = []
        self._listeners: list = []
        self._updated_targets: list[Target] = []
        self._is_alive_targets_dirty = True

    def update_target(self, event, name) -> None:
        target = self.get_target(name)
        if target not in self._updated_targets:
            self._updated_targets.append(target)
        target.add_event(event)
        self._is_alive_targets_dirty = True

    def on_target_killed(self, name) -> None:
        target = self._targets.get(name)
        if target is not None and target.is_alive:
            target.set_not_alive()
            self._is_alive_targets_dirty = True

    def on_tick(self) -> None:
        for target in self._updated_targets:
            target.update()
            for listener in self._listeners:
                listener.target_updated(target)
        self._updated_targets = []

    def get_target(self, name) -> Target:
        target = self._targets.get(name)
        if target is None:
            data = _TARGET_DATAS.get(name)
            if data is None:
                data = TargetData()
                _TARGET_DATAS[name] = data
            target = Target(self.robot, name, data)
            self._targets[name] = target
        return target

    def get_alive_targets(self) -> list[Target]:
        if self._is_alive_targets_dirty:
            self._alive_targets = [target for target in self._targets.values() if target.is_alive]
        self._is_alive_targets_dirty = False
        return self._alive_targets

    def get_alive_target_count(self) -> int:
        return len(self.get_alive_targets())

    def has_duel_opponent(self) -> bool:
        return self.get_alive_target_count() == 1

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    def get_duel_opponent(self) -> Target | None:
        alive = self._alive_targets
        return alive[0] if alive else None

    def get_any_duel_opponent(self) -> Target | None:
        return next(iter(self._targets.values()), None)

    def get_duel_opponent_name(self):
        return next(iter(self._targets.keys()), None)

    def is_no_alive_enemies(self) -> bool:
        return len(self._alive_targets) == 0

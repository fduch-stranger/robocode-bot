"""Robot state snapshots ported from ``lxx.RobotSnapshot``, ``MySnapshot``,
``EnemySnapshot`` and ``RobotImage``.

A "robot" here is any object exposing ``x``, ``y``, ``heading_radians``,
``velocity``, ``speed``, ``energy``, ``gun_heat``, ``battle_field``, ``name``
and ``time``; the bot adapter and ``Target`` both do.
"""
from __future__ import annotations

import math

from tomcat_port.lxx_utils import (
    MAX_TURN_RATE_RADIANS,
    ACCELERATION,
    DECELERATION,
    RADIANS_180,
    LXXPoint,
    PointLike,
    calculate_acceleration,
    limit,
    normal_absolute_angle,
    normal_relative_angle,
    sign,
)


class RobotSnapshot(PointLike):
    def __init__(self, current_state=None, prev_state=None, state1=None, state2=None, interpolation_k: float = 0.0) -> None:
        if state1 is not None and state2 is not None:
            self._init_interpolated(state1, state2, interpolation_k)
            return
        assert current_state is not None
        self.snapshot_time: int = current_state.time
        self.heading_radians: float = current_state.heading_radians
        self.speed: float = current_state.speed
        self.velocity: float = current_state.velocity
        self.position = LXXPoint(current_state.x, current_state.y)
        self.battle_field = current_state.battle_field
        self.energy: float = current_state.energy
        self.name = current_state.name
        self.gun_heat: float = current_state.gun_heat
        if prev_state is None:
            self.last_direction = 1
            self.acceleration = 0.0
        else:
            if self.velocity != 0:
                self.last_direction = int(sign(self.velocity))
            else:
                self.last_direction = prev_state.last_direction
            self.acceleration = calculate_acceleration(prev_state, current_state)

    def _init_interpolated(self, state1, state2, k: float) -> None:
        self.snapshot_time = int(state1.snapshot_time + (state2.snapshot_time - state1.snapshot_time) * k)
        self.heading_radians = state1.heading_radians + (state2.heading_radians - state1.heading_radians) * k
        self.speed = state1.speed + (state2.speed - state1.speed) * k
        self.velocity = state1.velocity + (state2.velocity - state1.velocity) * k
        self.energy = state1.energy + (state2.energy - state1.energy) * k
        self.gun_heat = state1.gun_heat + (state2.gun_heat - state1.gun_heat) * k
        self.position = LXXPoint(state1.x + (state2.x - state1.x) * k, state1.y + (state2.y - state1.y) * k)
        self.acceleration = state1.acceleration + (state2.acceleration - state1.acceleration) * k
        self.battle_field = state1.battle_field
        self.name = state1.name
        self.last_direction = state2.last_direction

    @property
    def x(self) -> float:
        return self.position.x

    @property
    def y(self) -> float:
        return self.position.y

    @property
    def absolute_heading_radians(self) -> float:
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RobotSnapshot) and self.snapshot_time == other.snapshot_time and self.name == other.name

    def __hash__(self) -> int:
        return hash((self.snapshot_time, self.name))


class MySnapshot(RobotSnapshot):
    def __init__(self, current_state=None, prev_state=None, last10_ticks_dist: float = 0.0, state1=None, state2=None, interpolation_k: float = 0.0) -> None:
        super().__init__(current_state, prev_state, state1, state2, interpolation_k)
        if state1 is not None and state2 is not None:
            self.last10_ticks_dist = state1.last10_ticks_dist + (state2.last10_ticks_dist - state1.last10_ticks_dist) * interpolation_k
            self.bullets = state2.bullets
            self.gun_cooling_rate = state2.gun_cooling_rate
        else:
            self.last10_ticks_dist = last10_ticks_dist
            self.bullets = list(current_state.bullets_in_air)
            self.gun_cooling_rate = current_state.gun_cooling_rate

    @property
    def absolute_heading_radians(self) -> float:
        direction = sign(self.velocity)
        if direction == 1:
            return self.heading_radians
        if direction == -1:
            return normal_absolute_angle(self.heading_radians + math.pi)
        if self.last_direction == 1:
            return self.heading_radians
        return normal_absolute_angle(self.heading_radians + math.pi)

    @property
    def bullets_in_air(self) -> list:
        return self.bullets

    def turns_to_gun_cool(self) -> int:
        return int(round(self.gun_heat / self.gun_cooling_rate))

    def set_bullets(self, bullets: list) -> None:
        self.bullets = bullets


class EnemySnapshot(RobotSnapshot):
    def __init__(self, current_state=None, visits: list | None = None, prev_state=None, state1=None, state2=None, interpolation_k: float = 0.0) -> None:
        super().__init__(current_state, prev_state, state1, state2, interpolation_k)
        if state1 is not None and state2 is not None:
            self.last_dir_change_time = int(state1.last_dir_change_time + (state2.last_dir_change_time - state1.last_dir_change_time) * interpolation_k)
            self.visits = state2.visits
            self.turn_rate_radians = state1.turn_rate_radians + (state2.turn_rate_radians - state1.turn_rate_radians) * interpolation_k
            return
        if prev_state is None:
            self.visits = visits if visits is not None else []
            self.last_dir_change_time = 0
            self.turn_rate_radians = 0.0
            return
        assert current_state is not None
        if (
            current_state.is_alive
            and sign(prev_state.acceleration) != sign(self.acceleration)
            and 0.1 < self.speed < 7.9
        ):
            self.last_dir_change_time = current_state.time - 1
        else:
            self.last_dir_change_time = prev_state.last_dir_change_time

        turn_rate = normal_relative_angle(current_state.heading_radians - prev_state.heading_radians)
        if abs(turn_rate) > MAX_TURN_RATE_RADIANS + 0.01:
            if current_state.time == prev_state.snapshot_time + 1:
                turn_rate = MAX_TURN_RATE_RADIANS * sign(turn_rate)
            else:
                turn_rate = turn_rate / (self.snapshot_time - prev_state.snapshot_time)
                if abs(turn_rate) > MAX_TURN_RATE_RADIANS:
                    turn_rate = MAX_TURN_RATE_RADIANS * sign(turn_rate)
        self.turn_rate_radians = turn_rate
        self.visits = prev_state.visits

    @property
    def absolute_heading_radians(self) -> float:
        if self.velocity >= 0:
            return self.heading_radians
        return normal_absolute_angle(self.heading_radians + math.pi)

    @property
    def visited_guess_factors(self) -> list:
        return self.visits

    def set_gun_heat(self, gun_heat: float) -> None:
        self.gun_heat = gun_heat


class RobotImage(PointLike):
    """A mutable copy of a snapshot that ``apply`` moves with simplified physics."""

    __slots__ = (
        "position",
        "velocity",
        "heading",
        "battle_field",
        "energy",
        "speed",
        "absolute_heading_radians",
        "name",
        "acceleration",
        "last_direction",
    )

    def __init__(self, original) -> None:
        self.position = LXXPoint(original.x, original.y)
        self.velocity = original.velocity
        self.speed = abs(self.velocity)
        self.heading = original.heading_radians
        self.battle_field = original.battle_field
        self.energy = original.energy
        self.name = original.name
        self.acceleration = original.acceleration
        self.absolute_heading_radians = original.absolute_heading_radians
        self.last_direction = original.last_direction

    def apply(self, movement_decision) -> None:
        self.heading = normal_absolute_angle(self.heading + movement_decision.turn_rate_radians)
        desired_velocity = movement_decision.desired_velocity
        if abs(sign(self.velocity) - sign(desired_velocity)) <= 1:
            acceleration = limit(-DECELERATION, abs(desired_velocity) - self.speed, ACCELERATION)
            self.speed += acceleration
            self.velocity = self.speed * sign(self.velocity if self.velocity != 0 else desired_velocity)
        elif self.speed > DECELERATION:
            self.velocity -= DECELERATION * sign(self.velocity)
            self.speed -= DECELERATION
        else:
            self.velocity = 0.0
            self.speed = 0.0
        self.absolute_heading_radians = (
            self.heading if self.velocity >= 0 else normal_absolute_angle(self.heading + RADIANS_180)
        )
        self.position = self.position.project(self.absolute_heading_radians, self.speed)

    @property
    def x(self) -> float:
        return self.position.x

    @property
    def y(self) -> float:
        return self.position.y

    @property
    def heading_radians(self) -> float:
        return self.heading

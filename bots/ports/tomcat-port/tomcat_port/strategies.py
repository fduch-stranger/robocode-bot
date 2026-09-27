"""Strategies ported from ``lxx.strategies``: the selector plus the duel,
find-enemies, fatality and win strategies, and the duel fire power selector.
"""
from __future__ import annotations

import math

from tomcat_port.gun import GunDecision
from tomcat_port.lxx_utils import (
    GUN_TURN_RATE_RADIANS,
    INACTIVITY_TIMER,
    MAX_TURN_RATE_RADIANS,
    MAX_VELOCITY,
    RADAR_TURN_RATE_RADIANS,
    RADIANS_5,
    RADIANS_90,
    RADIANS_180,
    angles_diff,
    bullet_damage,
    limit,
    normal_absolute_angle,
    normal_relative_angle,
    sign,
)
from tomcat_port.movement import MovementDecision


class TurnDecision:
    __slots__ = ("movement_decision", "gun_turn_rate", "fire_power", "radar_turn_rate", "target", "aim_prediction_data")

    def __init__(self, movement_decision: MovementDecision, gun_turn_rate: float | None, fire_power: float, radar_turn_rate: float | None, target, aim_prediction_data) -> None:
        self.movement_decision = movement_decision
        self.gun_turn_rate = gun_turn_rate
        self.fire_power = fire_power
        self.radar_turn_rate = radar_turn_rate
        self.target = target
        self.aim_prediction_data = aim_prediction_data


def _radar_turn_to(robot, target) -> float:
    if target is None:
        return normal_relative_angle(-robot.radar_heading_radians)
    angle_to_target = robot.angle_to(target)
    if angle_to_target != robot.radar_heading_radians:
        direction = sign(normal_relative_angle(angle_to_target - robot.radar_heading_radians))
    else:
        direction = 1
    return normal_relative_angle(angle_to_target - robot.radar_heading_radians + RADIANS_5 * direction)


class DuelFirePowerSelector:
    def __init__(self, statistics_manager) -> None:
        self.statistics_manager = statistics_manager

    def select_fire_power(self, robot, target) -> float:
        if target is None or robot.energy < 0.2:
            return 0.0
        power = 1.95
        if robot.a_distance(target) < 75:
            return min(3.0, robot.energy - 0.1)
        if target.is_ramming_now and robot.a_distance(target) < 150:
            power = 3.0
        raw_hit_rate = self.statistics_manager.get_my_raw_hit_rate()
        fires_per_hits = (math.ceil(1 / raw_hit_rate) + 1 if raw_hit_rate > 0 else 20) * max(1.0, target.energy / robot.energy) * 3
        power = limit(0.1, min(power, robot.energy / fires_per_hits), 3.0)
        if bullet_damage(power) > target.energy:
            power = target.energy / 4.0
        if power < 0.1:
            power = 0.1
        if 0.9 <= power <= 1.0:
            power = 1.1
        return power


class FindEnemiesStrategy:
    def __init__(self, robot, target_manager, enemies_count: int) -> None:
        self.robot = robot
        self.target_manager = target_manager
        self.enemies_count = enemies_count
        turn = sign(normal_relative_angle(robot.angle_to(robot.battle_field.center) - robot.radar_heading_radians))
        self.turn_direction = int(turn) if turn != 0 else 1

    def match(self) -> bool:
        return self.robot.time < 20 and self.target_manager.get_alive_target_count() < self.enemies_count

    def make_decision(self) -> TurnDecision:
        direction = self.turn_direction
        return TurnDecision(
            MovementDecision(0.0, MAX_TURN_RATE_RADIANS * direction),
            GUN_TURN_RATE_RADIANS * direction,
            0.0,
            RADAR_TURN_RATE_RADIANS * direction,
            None,
            None,
        )


class FatalityStrategy:
    def __init__(self, target_manager, enemy_bullet_manager, robot) -> None:
        self.target_manager = target_manager
        self.enemy_bullet_manager = enemy_bullet_manager
        self.robot = robot
        self.target = None

    def match(self) -> bool:
        robot = self.robot
        if robot.round < 2 or not self.target_manager.has_duel_opponent():
            return False
        if self.enemy_bullet_manager.get_all_bullets_on_air():
            return False
        target = self.target_manager.get_duel_opponent()
        self.target = target
        if target is None or bullet_damage(target.energy) > robot.energy:
            return False
        if target.energy >= target.target_data.min_fire_energy:
            return False
        if target.target_data.get_avg_fire_delay() > 5:
            return False
        if robot.time - robot.last_fire_time >= INACTIVITY_TIMER - 2:
            return False
        if robot.energy <= target.energy + 0.1:
            return False
        return True

    def make_decision(self) -> TurnDecision:
        velocity = self._velocity()
        heading = self.robot.heading_radians if velocity > 0 else normal_absolute_angle(self.robot.heading_radians + RADIANS_180)
        return TurnDecision(
            MovementDecision(velocity, self._turn_rate(heading)),
            self._turn_rate(self.robot.gun_heading_radians),
            0.0,
            _radar_turn_to(self.robot, self.target),
            None,
            None,
        )

    def _velocity(self) -> float:
        if angles_diff(self.robot.heading_radians, self.robot.angle_to(self.target)) < RADIANS_90:
            return MAX_VELOCITY
        return -MAX_VELOCITY

    def _turn_rate(self, heading: float) -> float:
        target = self.target
        point = target.project(
            normal_absolute_angle(target.absolute_heading_radians + target.current_snapshot.turn_rate_radians), MAX_VELOCITY
        )
        return normal_relative_angle(self.robot.angle_to(point) - heading)


class DuelStrategy:
    def __init__(self, robot, movement, gun, fire_power_selector: DuelFirePowerSelector, target_manager, enemy_bullet_manager) -> None:
        self.robot = robot
        self.movement = movement
        self.gun = gun
        self.fire_power_selector = fire_power_selector
        self.target_manager = target_manager
        self.enemy_bullet_manager = enemy_bullet_manager
        self.target = None

    def match(self) -> bool:
        match = self.target_manager.has_duel_opponent() or len(self.enemy_bullet_manager.get_bullets_on_air(1)) > 0
        if match:
            self.target = self.target_manager.get_duel_opponent()
        return match

    def make_decision(self) -> TurnDecision:
        mark_phase = getattr(self.robot, "mark_phase", None)
        movement_decision = self.movement.get_movement_decision()
        if mark_phase is not None:
            mark_phase("movement")
        target = self.target
        fire_power = self.fire_power_selector.select_fire_power(self.robot, target)
        if target is None:
            gun_decision = GunDecision(normal_relative_angle(-self.robot.gun_heading_radians), None)
        else:
            gun_decision = self.gun.get_gun_decision(target, fire_power)
        if mark_phase is not None:
            mark_phase("gun")
        return TurnDecision(
            movement_decision,
            gun_decision.gun_turn_angle_radians,
            fire_power,
            _radar_turn_to(self.robot, target),
            target,
            gun_decision.aim_prediction_data,
        )


class WinStrategy:
    PARADE_HEADING = RADIANS_90

    def __init__(self, robot, target_manager, enemy_bullet_manager) -> None:
        self.robot = robot
        self.target_manager = target_manager
        self.enemy_bullet_manager = enemy_bullet_manager

    def match(self) -> bool:
        return (
            self.robot.time > 10
            and not self.enemy_bullet_manager.get_bullets_on_air(1)
            and self.target_manager.is_no_alive_enemies()
        )

    def make_decision(self) -> TurnDecision:
        return TurnDecision(
            MovementDecision(0.0, self._turn_remaining()),
            normal_relative_angle(-self.robot.gun_heading_radians),
            0.1,
            normal_relative_angle(-self.robot.radar_heading_radians),
            self.target_manager.get_any_duel_opponent(),
            None,
        )

    def _turn_remaining(self) -> float:
        heading = self.robot.heading_radians
        turn_remaining = normal_relative_angle(self.PARADE_HEADING - heading)
        if abs(turn_remaining) > RADIANS_90:
            turn_remaining = normal_relative_angle(self.PARADE_HEADING - normal_absolute_angle(heading + math.pi))
        return turn_remaining


class StrategySelector:
    def __init__(self, robot, office) -> None:
        from tomcat_port.gun import TomcatClaws
        from tomcat_port.movement import WaveSurfingMovement

        target_manager = office.target_manager
        enemy_bullet_manager = office.enemy_bullet_manager
        enemy_bullet_manager.add_listener(office.tomcat_eyes)
        tomcat_claws = TomcatClaws(robot, office.turn_snapshots_log, office.data_view_manager)
        wave_surfing = WaveSurfingMovement(office)
        self.strategies = [
            FindEnemiesStrategy(robot, target_manager, robot.initial_others),
            FatalityStrategy(target_manager, enemy_bullet_manager, robot),
            DuelStrategy(
                robot,
                wave_surfing,
                tomcat_claws,
                DuelFirePowerSelector(office.statistics_manager),
                target_manager,
                enemy_bullet_manager,
            ),
            WinStrategy(robot, target_manager, enemy_bullet_manager),
        ]

    def select_strategy(self):
        for strategy in self.strategies:
            if strategy.match():
                return strategy
        return None

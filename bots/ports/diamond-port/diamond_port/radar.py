"""``voidious.radar.DiamondEyes``: 1v1 radar lock with a half-arc overshoot,
and a stalest-bot sweep for melee."""
from __future__ import annotations

import math
import sys

from diamond_port.dia_utils import BattleField, Point, absolute_bearing, non_zero_sign, normal_relative_angle
from diamond_port.enemy import ScannedRobotEvent
from diamond_port.movement_predictor import MovementPredictor

MAX_RADAR_TRACKING_AMOUNT = math.pi / 4
BOT_NOT_FOUND = -1


class RadarScan:
    __slots__ = ("last_scan_time", "last_location")

    def __init__(self, last_scan_time: int, last_location: Point) -> None:
        self.last_scan_time = last_scan_time
        self.last_location = last_location


class DiamondEyes:
    def __init__(self, robot, battle_field: BattleField) -> None:
        self._robot = robot
        self._scans: dict[object, RadarScan] = {}
        self._my_location = Point(robot.x, robot.y)
        self._target_name = None
        self._lock_mode = False
        self._reset_time = 0
        self._center_field = Point(battle_field.width / 2, battle_field.height / 2)
        self._radar_direction = 1
        self._last_radar_heading = 0.0
        self._predictor = MovementPredictor(battle_field)
        self._start_direction = 1

    def init_round(self, robot) -> None:
        self._robot = robot
        self._my_location = Point(robot.x, robot.y)
        self._scans.clear()
        self._lock_mode = False
        self._reset_time = 0
        self._last_radar_heading = robot.radar_heading_radians
        self._start_direction = self._get_start_radar_direction()

    def execute(self) -> None:
        robot = self._robot
        self._my_location = Point(robot.x, robot.y)
        self._check_scans_integrity()
        if robot.others == 1 and not self._lock_mode and self._scans:
            self.set_radar_lock(next(iter(self._scans)))
        self.direct_radar()
        self._last_radar_heading = robot.radar_heading_radians
        self._my_location = self._predictor.next_location(robot)

    def on_scanned_robot(self, e: ScannedRobotEvent) -> None:
        self._scans[e.name] = RadarScan(self._robot.time, e.location)

    def on_robot_death(self, bot_name) -> None:
        self._scans.pop(bot_name, None)
        if self._target_name is not None and self._target_name == bot_name:
            self._lock_mode = False

    def direct_radar(self) -> None:
        robot = self._robot
        if self._lock_mode and self._target_name not in self._scans:
            self._lock_mode = False

        if self._lock_mode and self._scans[self._target_name].last_scan_time == robot.time:
            radar_turn_amount = normal_relative_angle(
                absolute_bearing(self._my_location, self._scans[self._target_name].last_location) - robot.radar_heading_radians
            )
            self._radar_direction = non_zero_sign(radar_turn_amount)
            radar_turn_amount += self._radar_direction * (MAX_RADAR_TRACKING_AMOUNT / 2)
        else:
            self._radar_direction = self._next_radar_direction()
            radar_turn_amount = self._radar_direction * MAX_RADAR_TRACKING_AMOUNT
        robot.set_turn_radar_right_radians(radar_turn_amount)

    def set_radar_lock(self, bot_name) -> None:
        if bot_name in self._scans:
            self._target_name = bot_name
            self._lock_mode = True

    def release_radar_lock(self) -> None:
        self._lock_mode = False

    def min_ticks_to_scan(self, bot_name) -> int:
        scan = self._scans.get(bot_name)
        if scan is None:
            return BOT_NOT_FOUND
        abs_bearing = absolute_bearing(self._my_location, scan.last_location)
        shortest_angle_to_scan = abs(normal_relative_angle(abs_bearing - self._robot.radar_heading_radians))
        return int(math.ceil(shortest_angle_to_scan / MAX_RADAR_TRACKING_AMOUNT))

    def _get_start_radar_direction(self) -> int:
        return self._direction_to_bearing(absolute_bearing(self._my_location, self._center_field))

    def _next_radar_direction(self) -> int:
        if not self._scans or len(self._scans) < self._robot.others:
            return self._start_direction
        stalest_bot = self._find_stalest_bot_name()
        if self.min_ticks_to_scan(stalest_bot) == 4:
            radar_target = self._center_field
        else:
            radar_target = self._scans[stalest_bot].last_location
        abs_bearing_radar_target = absolute_bearing(self._my_location, radar_target)
        if self.just_scanned_that_spot(abs_bearing_radar_target):
            return self._radar_direction
        return self._direction_to_bearing(abs_bearing_radar_target)

    def _direction_to_bearing(self, bearing: float) -> int:
        return 1 if normal_relative_angle(bearing - self._robot.radar_heading_radians) > 0 else -1

    def _find_stalest_bot_name(self):
        oldest_time = 2**63 - 1
        bot_name = None
        for name, scan in self._scans.items():
            if scan.last_scan_time < oldest_time:
                oldest_time = scan.last_scan_time
                bot_name = name
        return bot_name

    def _check_scans_integrity(self) -> None:
        robot = self._robot
        if len(self._scans) != robot.others and robot.time - self._reset_time > 25 and robot.others > 0:
            self._scans.clear()
            self._lock_mode = False
            self._reset_time = robot.time
            if robot.verbose:
                print(f"WARNING: Radar integrity failure detected (time = {self._reset_time}), resetting.", file=sys.stderr)

    def just_scanned_that_spot(self, abs_bearing: float) -> bool:
        return (
            non_zero_sign(normal_relative_angle(abs_bearing - self._last_radar_heading)) == self._radar_direction
            and non_zero_sign(normal_relative_angle(self._robot.radar_heading_radians - abs_bearing)) == self._radar_direction
        )

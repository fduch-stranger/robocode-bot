"""``voidious.utils.MovementPredictor``: Robocode-order movement physics
(turn, then accelerate, then move) used for wave-surfing prediction, next-tick
locations and precise maximum escape angles.

The engine now moves bots in Tank Royale order (speed, move, turn), so this
predictor is a few pixels off per tick; it is kept as Diamond wrote it because
every danger estimate and escape angle was tuned against it.
"""
from __future__ import annotations

import math

from diamond_port.dia_utils import (
    ACCELERATION,
    DECELERATION,
    HALF_PI,
    QUARTER_PI,
    TWO_PI,
    BattleField,
    MaxEscapeTarget,
    Point,
    RobotState,
    absolute_bearing,
    get_turn_rate_radians,
    limit,
    normal_relative_angle,
    signum,
)

PRECISE_MEA_ITERATIONS = 3
FULL_SPEED = 8.0


class MovementPredictor:
    __slots__ = ("battle_field",)

    def __init__(self, battle_field: BattleField) -> None:
        self.battle_field = battle_field

    def predict(
        self,
        start_state: RobotState,
        distance: float,
        turn: float,
        max_velocity: float,
        ticks: int,
        ignore_walls: bool,
    ) -> RobotState:
        state = start_state
        field = self.battle_field
        for _ in range(ticks):
            next_heading = state.heading
            max_turn_rate = abs(get_turn_rate_radians(state.velocity))
            if abs(turn) < max_turn_rate:
                next_heading += turn
                turn = 0.0
            else:
                turn_amount = max_turn_rate * signum(turn)
                next_heading += turn_amount
                turn -= turn_amount

            next_velocity = self._get_new_velocity(state.velocity, distance, max_velocity)
            distance -= next_velocity

            location = state.location
            next_location = Point(
                location.x + math.sin(next_heading) * next_velocity,
                location.y + math.cos(next_heading) * next_velocity,
            )
            if not ignore_walls and not field.contains_point(next_location):
                self._adjust_for_walls(next_location, next_heading)
            state = RobotState(next_location, next_heading, next_velocity, state.time + 1)
        return state

    def _adjust_for_walls(self, location: Point, heading: float) -> None:
        field = self.battle_field
        x_out = min(0.0, field.max_x - location.x)
        y_out = min(0.0, field.max_y - location.y)
        if x_out == 0:
            x_out = max(0.0, field.min_x - location.x)
        if y_out == 0:
            y_out = max(0.0, field.min_y - location.y)

        x_offset = x_out
        y_offset = y_out
        while heading < 0:
            heading += TWO_PI
        if math.fmod(heading, QUARTER_PI) != 0:
            tan_heading = math.tan(heading)
            if abs(x_out) > 0:
                y_offset = x_out / tan_heading
            if abs(y_out) > 0:
                x_offset = y_out * tan_heading
            if abs(y_out) > abs(y_offset):
                y_offset = y_out
            if abs(x_out) > abs(x_offset):
                x_offset = x_out
        location.x += x_offset
        location.y += y_offset

    # Adapted (by Voidious) from the optimal velocity collaboration also used by
    # the Robocode engine.
    def _get_new_velocity(self, velocity: float, distance: float, max_velocity: float) -> float:
        if distance < 0:
            return -self._get_new_velocity(-velocity, -distance, max_velocity)
        if distance == math.inf or (distance >= 20 and max_velocity <= 8):
            # _get_max_velocity(distance) is at least 8 once 20 units remain,
            # so the stopping-distance cap cannot bind; skip the sqrt.
            goal_velocity = max_velocity
        else:
            goal_velocity = min(self._get_max_velocity(distance), max_velocity)
        if velocity >= 0:
            return limit(velocity - DECELERATION, goal_velocity, velocity + ACCELERATION)
        return limit(velocity - ACCELERATION, goal_velocity, velocity + self._max_decel(-velocity))

    @staticmethod
    def _get_max_velocity(distance: float) -> float:
        decel_time = max(1.0, math.ceil((math.sqrt((4 * 2 / DECELERATION) * distance + 1) - 1) / 2))
        decel_dist = (decel_time / 2.0) * (decel_time - 1) * DECELERATION
        return ((decel_time - 1) * DECELERATION) + ((distance - decel_dist) / decel_time)

    @staticmethod
    def _max_decel(velocity: float) -> float:
        velocity = abs(velocity)
        if velocity > DECELERATION:
            return DECELERATION
        tick_fraction_decel = velocity / DECELERATION
        tick_fraction_accel = 1 - tick_fraction_decel
        return (tick_fraction_decel * DECELERATION) + (tick_fraction_accel * ACCELERATION)

    def next_robot_state(self, robot) -> RobotState:
        return self.predict(
            RobotState(Point(robot.x, robot.y), robot.heading_radians, robot.velocity, robot.time),
            robot.distance_remaining,
            robot.turn_remaining_radians,
            robot.max_velocity,
            1,
            False,
        )

    def next_location(self, robot) -> Point:
        return self.next_robot_state(robot).location

    @staticmethod
    def next_location_of_state(robot_state: RobotState) -> Point:
        return MovementPredictor.next_location_from(robot_state.location, robot_state.heading, robot_state.velocity)

    @staticmethod
    def next_location_from(bot_location: Point, heading: float, velocity: float) -> Point:
        return Point(bot_location.x + math.sin(heading) * velocity, bot_location.y + math.cos(heading) * velocity)

    def next_perpendicular_location(
        self, robot_state: RobotState, abs_bearing: float, orientation: int, attack_angle: float, ignore_wall_hits: bool
    ) -> RobotState:
        return self.next_perpendicular_wall_smoothed_location(
            robot_state, abs_bearing, 8.0, attack_angle, orientation, 0.0, ignore_wall_hits
        )

    def next_perpendicular_wall_smoothed_location(
        self,
        robot_state: RobotState,
        abs_bearing: float,
        max_velocity: float,
        attack_angle: float,
        orientation: int,
        wall_stick: float,
        ignore_wall_hits: bool,
    ) -> RobotState:
        go_angle = normal_relative_angle(abs_bearing + (orientation * (HALF_PI + attack_angle)))
        if wall_stick != 0:
            go_angle = self.battle_field.wall_smoothing(robot_state.location, go_angle, orientation, wall_stick)
        return self.next_location_toward(robot_state, max_velocity, go_angle, ignore_wall_hits)

    def next_location_toward(self, robot_state: RobotState, max_velocity: float, go_angle: float, ignore_wall_hits: bool) -> RobotState:
        future_turn = normal_relative_angle(go_angle - robot_state.heading)
        if abs(future_turn) > HALF_PI:
            future_turn = future_turn - (signum(future_turn) * math.pi)
            future_distance = -1000.0
        else:
            future_distance = 1000.0
        return self.predict(robot_state, future_distance, future_turn, max_velocity, 1, ignore_wall_hits)

    def escape_angle_range(self, source: Point, fire_time: int, bullet_speed: float, start_state: RobotState, wall_stick: float) -> float:
        return (
            self.precise_escape_angle(1, source, fire_time, bullet_speed, start_state, 0.0, wall_stick).angle
            + self.precise_escape_angle(-1, source, fire_time, bullet_speed, start_state, 0.0, wall_stick).angle
        )

    def precise_escape_angle(
        self,
        predict_direction: int,
        source: Point,
        fire_time: int,
        bullet_speed: float,
        start_state: RobotState,
        attack_angle: float,
        wall_stick: float,
    ) -> MaxEscapeTarget:
        abs_bearing = absolute_bearing(source, start_state.location)
        straight = self._straight_precise_escape_angle(
            predict_direction, abs_bearing, source, fire_time, bullet_speed, start_state, attack_angle
        )
        best_smoothing = None
        if straight.hit_wall:
            best_smoothing = self._smoothing_precise_escape_angle(
                predict_direction, abs_bearing, source, fire_time, bullet_speed, start_state, attack_angle, wall_stick, PRECISE_MEA_ITERATIONS
            )
        if best_smoothing is not None and best_smoothing.angle > straight.angle:
            return best_smoothing
        return straight

    def _straight_precise_escape_angle(
        self, predict_direction: int, abs_bearing: float, source: Point, fire_time: int, bullet_speed: float, start_state: RobotState, attack_angle: float
    ) -> MaxEscapeTarget:
        predicted = start_state
        hit_wall = False
        wave_passed = False
        field = self.battle_field
        while True:
            predicted = self.next_perpendicular_location(predicted, abs_bearing, predict_direction, attack_angle, True)
            if not field.contains_point(predicted.location):
                hit_wall = True
            elif self._wave_passed(source, fire_time, bullet_speed, predicted):
                wave_passed = True
            if hit_wall or wave_passed:
                break
        mea_location = field.translate_to_field(predicted.location)
        straight_escape_angle = predict_direction * normal_relative_angle(absolute_bearing(source, mea_location) - abs_bearing)
        return MaxEscapeTarget(straight_escape_angle, mea_location, predicted.time, hit_wall)

    def _smoothing_precise_escape_angle(
        self,
        predict_direction: int,
        abs_bearing: float,
        source: Point,
        fire_time: int,
        bullet_speed: float,
        start_state: RobotState,
        attack_angle: float,
        wall_stick: float,
        iterations: int,
    ) -> MaxEscapeTarget:
        field = self.battle_field
        best = MaxEscapeTarget(0.0, start_state.location, start_state.time, False)
        go_angle = abs_bearing + (predict_direction * (HALF_PI + attack_angle))
        go_angle = field.wall_smoothing(start_state.location, go_angle, predict_direction, wall_stick)
        for x in range(iterations):
            predicted = start_state
            while True:
                predicted = self.next_location_toward(predicted, FULL_SPEED, go_angle, True)
                if self._wave_passed(source, fire_time, bullet_speed, predicted):
                    break
                go_angle = field.wall_smoothing(predicted.location, go_angle, predict_direction, wall_stick)
            predicted_location = field.translate_to_field(predicted.location)
            this_escape_angle = predict_direction * normal_relative_angle(absolute_bearing(source, predicted_location) - abs_bearing)
            if this_escape_angle > best.angle:
                best = MaxEscapeTarget(this_escape_angle, predicted_location, predicted.time, False)
            if x + 1 < iterations:
                go_angle = absolute_bearing(start_state.location, predicted_location)
        return best

    @staticmethod
    def _wave_passed(source: Point, fire_time: int, bullet_speed: float, enemy_state: RobotState) -> bool:
        threshold = bullet_speed * (enemy_state.time - fire_time) + bullet_speed
        return enemy_state.location.distance_sq(source) < (threshold * threshold) * signum(threshold)

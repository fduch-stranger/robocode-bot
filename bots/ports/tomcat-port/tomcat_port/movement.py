"""Wave surfing movement ported from ``lxx.strategies.duel``: ``PointsGenerator``,
``PointDanger``, ``DistanceController``, ``WaveSurfingMovement`` and the
``MovementDecision`` model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from tomcat_port.lxx_utils import (
    ACCELERATION,
    MAX_VELOCITY,
    RADIANS_30,
    RADIANS_50,
    RADIANS_80,
    RADIANS_90,
    RADIANS_100,
    RADIANS_135,
    RADIANS_180,
    IntervalDouble,
    LXXPoint,
    PointLike,
    angle,
    angles_diff,
    limit,
    normal_absolute_angle,
    normal_near_absolute_angle,
    normal_relative_angle,
    robot_width_in_radians,
    sign,
    stop_distance,
    turn_rate_radians,
)
from tomcat_port.snapshots import RobotImage


@dataclass(frozen=True)
class MovementDecision:
    desired_velocity: float
    turn_rate_radians: float

    @staticmethod
    def to_movement_decision(robot, desired_speed: float, desired_heading: float) -> MovementDecision:
        if desired_speed > MAX_VELOCITY:
            desired_speed = MAX_VELOCITY
        heading = robot.heading_radians
        want_to_go_front = angles_diff(heading, desired_heading) < RADIANS_90
        normalized_heading = desired_heading if want_to_go_front else normal_absolute_angle(desired_heading + RADIANS_180)
        turn_remaining = normal_relative_angle(normalized_heading - heading)
        turn_limit = turn_rate_radians(robot.speed)
        turn_rate = limit(-turn_limit, turn_remaining, turn_limit)
        return MovementDecision(desired_speed * (1 if want_to_go_front else -1), turn_rate)


class OrbitDirection(Enum):
    CLOCKWISE = 1
    COUNTER_CLOCKWISE = -1

    @property
    def sign(self) -> int:
        return self.value


class PointDanger:
    def __init__(self, bullet, danger_on_first_wave: float, distance_to_center: float) -> None:
        self.bullet = bullet
        self.danger_on_first_wave = danger_on_first_wave
        self.distance_to_center = distance_to_center
        self.dist_to_enemy_sq = float(2147483647)
        self.min_danger_on_second_wave: PointDanger | None = None
        self.danger = 0.0
        self.danger_multiplier = 1.0
        self.calculate_danger()

    def set_min_dist_to_enemy_sq(self, dist_sq: float) -> None:
        self.dist_to_enemy_sq = min(self.dist_to_enemy_sq, dist_sq)

    def set_min_danger_on_second_wave(self, danger: PointDanger) -> None:
        self.min_danger_on_second_wave = danger
        self.calculate_danger()

    def calculate_danger(self) -> None:
        dist_to_enemy = math.sqrt(self.dist_to_enemy_sq)
        this_danger = (
            self.danger_on_first_wave * 120
            + self.distance_to_center / 800 * 5
            + max(0.0, 500 - dist_to_enemy) / dist_to_enemy * 15
        )
        if self.bullet is not None:
            this_danger *= self.bullet.bullet.power
        second = self.min_danger_on_second_wave.danger if self.min_danger_on_second_wave is not None else 0.0
        self.danger = (this_danger + second / 10) * self.danger_multiplier


class WSPoint(LXXPoint):
    __slots__ = ("danger", "orbit_direction")

    def __init__(self, point: PointLike, danger: PointDanger) -> None:
        super().__init__(point.x, point.y)
        self.danger = danger
        self.orbit_direction: OrbitDirection | None = None


class DistanceController:
    SIMPLE_DISTANCE = 650.0
    ANTI_RAM_DISTANCE = 150
    MAX_ATTACK_DELTA_WITHOUT_BULLETS = RADIANS_30
    MIN_ATTACK_DELTA_WITHOUT_BULLETS = RADIANS_30

    def __init__(self, target_manager) -> None:
        self.target_manager = target_manager
        self.desired_distance = self.SIMPLE_DISTANCE

    def get_desired_heading(self, surf_point: PointLike, robot_pos: PointLike, orbit_direction: OrbitDirection) -> float:
        distance_between = robot_pos.a_distance(surf_point)
        distance_diff = distance_between - self.SIMPLE_DISTANCE
        attack_angle_koeff = distance_diff / self.SIMPLE_DISTANCE
        opponent = self.target_manager.get_duel_opponent()
        if opponent is not None and distance_between < self.ANTI_RAM_DISTANCE and opponent.is_ramming_now:
            anti_ram_angle = RADIANS_50 * (self.ANTI_RAM_DISTANCE - distance_between) / self.ANTI_RAM_DISTANCE
        else:
            anti_ram_angle = 0.0
        max_attack_angle = RADIANS_100 + self.MAX_ATTACK_DELTA_WITHOUT_BULLETS
        min_attack_angle = RADIANS_80 - self.MIN_ATTACK_DELTA_WITHOUT_BULLETS - anti_ram_angle / 2
        attack_angle = RADIANS_90 + ((RADIANS_30 + anti_ram_angle) * attack_angle_koeff)
        return normal_absolute_angle(
            angle(surf_point.x, surf_point.y, robot_pos.x, robot_pos.y)
            + limit(min_attack_angle, attack_angle, max_attack_angle) * orbit_direction.sign
        )

    def set_desired_distance(self, desired_distance: float) -> None:
        self.desired_distance = desired_distance


class PointsGenerator:
    def __init__(self, distance_controller: DistanceController, battle_field) -> None:
        self.distance_controller = distance_controller
        self.battle_field = battle_field

    def _get_point_danger(self, bullet, robot_pos: LXXPoint) -> PointDanger:
        wave_danger = self._get_wave_danger(robot_pos, bullet) if bullet is not None else 0.0
        return PointDanger(bullet, wave_danger, self.battle_field.center.a_distance(robot_pos))

    @staticmethod
    def _get_wave_danger(pnt: LXXPoint, bullet) -> float:
        prediction = bullet.aim_prediction_data
        predicted = prediction.predicted_bearing_offsets
        if not predicted:
            return 0.0
        fire_pos = bullet.fire_position
        alpha = angle(fire_pos.x, fire_pos.y, pnt.x, pnt.y)
        bearing_offset = normal_relative_angle(alpha - bullet.no_bearing_offset)
        width = robot_width_in_radians(alpha, fire_pos.a_distance(pnt))
        bullets_danger = 0.0
        hi_effect = width * 0.75
        low_effect = width * 2.55
        for bo in predicted:
            if bo.bearing_offset < bearing_offset - low_effect:
                continue
            if bo.bearing_offset > bearing_offset + low_effect:
                break
            dist = abs(bearing_offset - bo.bearing_offset)
            if dist < hi_effect:
                bullets_danger += (2 - dist / hi_effect) * bo.danger
            elif dist < low_effect:
                bullets_danger += (1 - dist / low_effect) * bo.danger
        intersection_total = 0.0
        half_width = width / 2
        robot_interval = IntervalDouble(bearing_offset - half_width, bearing_offset + half_width)
        for shadow in bullet.merged_shadows:
            if robot_interval.intersects(shadow):
                intersection_total += robot_interval.intersection(shadow)
        bullets_danger *= 1 - intersection_total / width
        return bullets_danger

    def generate_points(self, dst_point: PointLike, bullet, robot_img: RobotImage, opponent_img: RobotImage | None, time: int, points: list | None) -> int:
        surf_point = self.get_surf_point(opponent_img, bullet)
        speed = bullet.speed
        travelled = bullet.traveled_distance + speed * time
        fire_position = bullet.fire_position
        enemy_desired_velocity = MAX_VELOCITY * sign(opponent_img.velocity) if opponent_img is not None else 0.0
        while True:
            decision = self.get_movement_decision(surf_point, dst_point, robot_img, opponent_img)
            robot_img.apply(decision)
            robot_pos = robot_img.position
            if points is not None:
                points.append(WSPoint(robot_img, self._get_point_danger(bullet, robot_pos)))
                if opponent_img is not None:
                    opponent_img.apply(MovementDecision(enemy_desired_velocity, 0.0))
                    opp_pos = opponent_img.position
                    for prev_point in points:
                        prev_point.danger.set_min_dist_to_enemy_sq(prev_point.a_distance_sq(opp_pos))
            time += 1
            travelled += speed
            if not (travelled < 0 or fire_position.a_distance_sq(robot_pos) > travelled * travelled):
                break
            if time > 600:
                break
        return time

    def play_forward_wave_surfing(self, dst_point: PointLike, bullet, robot_img: RobotImage, opponent_img: RobotImage | None) -> int:
        return self.generate_points(dst_point, bullet, robot_img, opponent_img, 0, None)

    def get_movement_decision(self, surf_point: LXXPoint, dst_point: PointLike, robot, opponent) -> MovementDecision:
        alpha_to_robot = surf_point.angle_to(robot)
        alpha_to_dst = surf_point.angle_to(dst_point)
        accelerated_speed = min(MAX_VELOCITY, robot.speed + ACCELERATION)
        target = surf_point.project(alpha_to_dst, surf_point.a_distance(robot))
        desired_speed = 8.0 if robot.a_distance(target) > stop_distance(accelerated_speed) + accelerated_speed + 1 else 0.0
        orbit_direction = OrbitDirection.CLOCKWISE if normal_relative_angle(alpha_to_dst - alpha_to_robot) >= 0 else OrbitDirection.COUNTER_CLOCKWISE
        return self._get_movement_decision(surf_point, orbit_direction, robot, opponent, desired_speed)

    def _get_movement_decision(self, surf_point: LXXPoint, orbit_direction: OrbitDirection, robot, opponent, desired_speed: float) -> MovementDecision:
        robot_pos = robot.position
        desired_heading = self.distance_controller.get_desired_heading(surf_point, robot_pos, orbit_direction)
        field = self.battle_field
        if (
            robot_pos.x < field.no_smooth_x.a
            or robot_pos.x > field.no_smooth_x.b
            or robot_pos.y < field.no_smooth_y.a
            or robot_pos.y > field.no_smooth_y.b
        ):
            desired_heading = field.smooth_walls(robot_pos, desired_heading, orbit_direction is OrbitDirection.CLOCKWISE)
        if opponent is not None:
            opp_pos = opponent.position
            dist_to_opponent = robot.a_distance(opp_pos)
            angle_to_opponent = angle(robot_pos.x, robot_pos.y, opp_pos.x, opp_pos.y)
            if angles_diff(desired_heading, angle_to_opponent) < robot_width_in_radians(angle_to_opponent, dist_to_opponent) * 1.1:
                desired_heading = normal_near_absolute_angle(desired_heading + RADIANS_180)
        angle_to_surf_point = robot.angle_to(surf_point)
        if angles_diff(desired_heading, angle_to_surf_point) < robot_width_in_radians(angle_to_surf_point, robot.a_distance(surf_point)) * 1.1:
            desired_heading = normal_near_absolute_angle(desired_heading + RADIANS_180)
        return MovementDecision.to_movement_decision(robot, desired_speed, desired_heading)

    @staticmethod
    def get_surf_point(duel_opponent, bullet) -> LXXPoint:
        if duel_opponent is None:
            return bullet.fire_position
        return LXXPoint(duel_opponent.x, duel_opponent.y)


class MovementDirectionPrediction:
    def __init__(self) -> None:
        self.cw_points: list[WSPoint] = []
        self.ccw_points: list[WSPoint] = []
        self.enemy_velocity_sign = 0.0
        self.first_bullet_prediction_time = 0
        self.min_danger_point: WSPoint | None = None


class WaveSurfingMovement:
    def __init__(self, office) -> None:
        self.robot = office.robot
        self.target_manager = office.target_manager
        self.enemy_bullet_manager = office.enemy_bullet_manager
        self.statistics_manager = office.statistics_manager
        self.distance_controller = DistanceController(office.target_manager)
        self.points_generator = PointsGenerator(self.distance_controller, self.robot.battle_field)
        self.duel_opponent = None
        self.prev_prediction: MovementDirectionPrediction | None = None

    def get_movement_decision(self) -> MovementDecision:
        self.duel_opponent = self.target_manager.get_duel_opponent()
        bullets = self._get_bullets()
        if self._need_to_reselect_orbit_direction(bullets):
            self._select_orbit_direction(bullets)
        opponent = self.duel_opponent.current_snapshot if self.duel_opponent is not None else None
        if self.duel_opponent is None or self.statistics_manager.enemy_hit_rate.get_hit_rate() < 0.05:
            self.distance_controller.set_desired_distance(900)
        surf_point = self.points_generator.get_surf_point(opponent, bullets[0])
        assert self.prev_prediction is not None and self.prev_prediction.min_danger_point is not None
        return self.points_generator.get_movement_decision(surf_point, self.prev_prediction.min_danger_point, self.robot.current_snapshot, opponent)

    def _need_to_reselect_orbit_direction(self, bullets) -> bool:
        prev = self.prev_prediction
        if prev is None or prev.min_danger_point is None:
            return True
        if self._is_bullets_updated(bullets):
            return True
        if self.duel_opponent is not None and sign(self.duel_opponent.velocity) != prev.enemy_velocity_sign:
            return True
        return self.robot.a_distance(prev.min_danger_point) <= stop_distance(self.robot.speed) + MAX_VELOCITY

    def _is_bullets_updated(self, bullets) -> bool:
        prediction_round_time = bullets[0].aim_prediction_data.prediction_round_time
        assert self.prev_prediction is not None
        return prediction_round_time != self.prev_prediction.first_bullet_prediction_time or prediction_round_time == 0

    def _select_orbit_direction(self, bullets) -> None:
        prediction = MovementDirectionPrediction()
        prediction.first_bullet_prediction_time = bullets[0].aim_prediction_data.prediction_round_time
        prediction.enemy_velocity_sign = sign(self.duel_opponent.velocity) if self.duel_opponent is not None else 0.0
        my_snapshot = self.robot.current_snapshot
        opp_snapshot = self.duel_opponent.current_snapshot if self.duel_opponent is not None else None
        prediction.cw_points = self._predict_movement_in_direction(bullets, OrbitDirection.CLOCKWISE, RobotImage(my_snapshot), RobotImage(opp_snapshot) if opp_snapshot is not None else None)
        prediction.ccw_points = self._predict_movement_in_direction(bullets, OrbitDirection.COUNTER_CLOCKWISE, RobotImage(my_snapshot), RobotImage(opp_snapshot) if opp_snapshot is not None else None)
        future_poses = sorted(prediction.cw_points + prediction.ccw_points, key=lambda point: point.danger.danger)
        if len(bullets) >= 2:
            for i in range(min(len(future_poses), 6)):
                future_pos = future_poses[i]
                if i > 0 and prediction.min_danger_point is not None and future_pos.danger.danger > prediction.min_danger_point.danger.danger:
                    break
                min_second = self._get_min_point_danger(RobotImage(my_snapshot), RobotImage(opp_snapshot) if opp_snapshot is not None else None, bullets, future_pos)
                future_pos.danger.set_min_danger_on_second_wave(min_second)
                if prediction.min_danger_point is None or future_pos.danger.danger < prediction.min_danger_point.danger.danger:
                    prediction.min_danger_point = future_pos
        else:
            prediction.min_danger_point = future_poses[0]
        self.prev_prediction = prediction

    def _get_min_point_danger(self, robot_image: RobotImage, opponent_img: RobotImage | None, bullets, dst: PointLike) -> PointDanger:
        me_img = RobotImage(robot_image)
        opp_img = RobotImage(opponent_img) if opponent_img is not None else None
        time = self.points_generator.play_forward_wave_surfing(dst, bullets[0], me_img, opp_img)
        second_bullets = bullets[1:]
        second_surf_point = opp_img if opp_img is not None else second_bullets[0].fire_position
        second_wave_points: list[WSPoint] = []
        for direction in (OrbitDirection.CLOCKWISE, OrbitDirection.COUNTER_CLOCKWISE):
            dst_point = second_surf_point.project(
                normal_absolute_angle(second_surf_point.angle_to(robot_image) + RADIANS_135 * direction.sign),
                second_surf_point.a_distance(me_img) * 10,
            )
            points: list[WSPoint] = []
            self.points_generator.generate_points(dst_point, second_bullets[0], RobotImage(me_img), RobotImage(opp_img) if opp_img is not None else None, time, points)
            second_wave_points.extend(points)
        min_danger_point = WSPoint(robot_image, PointDanger(None, 10000, 0))
        for point in second_wave_points:
            point.danger.calculate_danger()
            if min_danger_point.danger.danger > point.danger.danger:
                min_danger_point = point
        return min_danger_point.danger

    def _predict_movement_in_direction(self, bullets, orbit_direction: OrbitDirection, robot_image: RobotImage, opponent_img: RobotImage | None) -> list[WSPoint]:
        surf_point = opponent_img if opponent_img is not None else bullets[0].fire_position
        dst_point = surf_point.project(
            normal_absolute_angle(surf_point.angle_to(robot_image) + RADIANS_135 * orbit_direction.sign),
            surf_point.a_distance(robot_image) * 10,
        )
        points: list[WSPoint] = []
        self.points_generator.generate_points(dst_point, bullets[0], RobotImage(robot_image), RobotImage(opponent_img) if opponent_img is not None else None, 0, points)
        prev = self.prev_prediction
        for point in points:
            point.orbit_direction = orbit_direction
            if prev is not None and prev.min_danger_point is not None and point.orbit_direction is prev.min_danger_point.orbit_direction:
                point.danger.danger_multiplier = 0.95
            point.danger.calculate_danger()
        return points

    def _get_bullets(self) -> list:
        bullets = self.enemy_bullet_manager.get_bullets_on_air(2)
        if len(bullets) < 2 and self.duel_opponent is not None:
            bullets.append(self.enemy_bullet_manager.create_future_bullet(self.duel_opponent))
        if not bullets:
            bullets = self.enemy_bullet_manager.get_all_bullets_on_air()
        return bullets

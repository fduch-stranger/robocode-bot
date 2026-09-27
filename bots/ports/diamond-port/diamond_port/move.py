"""``voidious.move``: ``DiamondWhoosh`` and everything under it: the movement
data manager, the enemy-bullet model (``MoveEnemy``), the wave surfer with its
danger search, the minimum-risk melee mover and the surfing formulas."""
from __future__ import annotations

import math
import random
import sys

from diamond_port.dia_utils import (
    ACCELERATION,
    DECELERATION,
    HALF_PI,
    LONG_MIN,
    BattleField,
    Circle,
    DistanceFormula,
    LineSeg,
    Point,
    RobotState,
    RobotStateLog,
    TimestampedGuessFactor,
    absolute_bearing,
    accel as accel_of,
    distance_to_wall,
    get_bullet_damage,
    get_bullet_hit_bonus,
    get_gun_heat,
    get_wall_hit_damage,
    inverse_sqrt,
    java_div,
    limit,
    margin_of_error,
    non_zero_sign,
    normal_absolute_angle,
    normal_relative_angle,
    normalize_angle,
    project,
    round_to,
    square,
)
from diamond_port.enemy import BulletRecord, Enemy, EnemyDataManager, ScannedRobotEvent, warn
from diamond_port.gun import FiredBullet
from diamond_port.kd_tree import KdTree
from diamond_port.knn_view import KnnView
from diamond_port.movement_predictor import MovementPredictor
from diamond_port.wave import (
    BREAKING_CENTER,
    BREAKING_FRONT,
    FIRING_WAVE,
    FIRST_WAVE,
    GONE,
    MIDAIR,
    Intersection,
    Wave,
    WaveManager,
    is_breaking,
)

WAVES_TO_SURF = 2


# Formulas --------------------------------------------------------------------------
def _accel_attribute(w: Wave) -> float:
    return ((w.target_accel / (DECELERATION if w.target_accel < 0 else ACCELERATION)) + 1) / 2


class SimpleFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [1.0, 1.0, 1.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            (w.lateral_velocity() + 0.1) / 8.1,
            _accel_attribute(w),
        ]


class NormalFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [4.0, 3.0, 3.0, 3.0, 2.0, 4.0, 1.0, 3.0, 2.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            _accel_attribute(w),
            min(1.0, w.target_wall_distance) / 1.0,
            min(1.0, w.target_rev_wall_distance) / 1.0,
            min(1.0, java_div(w.target_vchange_time, w.target_distance / w.bullet_speed())),
            w.target_dl8t / 64,
        ]


class FlattenerFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [3.0, 4.0, 3.0, 5.0, 1.0, 4.0, 3.0, 3.0, 2.0, 2.0, 2.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            _accel_attribute(w),
            min(1.0, w.target_wall_distance) / 1.0,
            min(1.0, w.target_rev_wall_distance) / 1.0,
            min(1.0, java_div(float(w.target_vchange_time), w.target_distance / w.bullet_speed())),
            w.target_dl8t / 64,
            w.target_dl20t / 160,
            w.target_dl40t / 320,
        ]


class WallHitDamage:
    __slots__ = ("min", "max")

    def __init__(self, minimum: float, maximum: float) -> None:
        self.min = minimum
        self.max = maximum


# MoveEnemy -----------------------------------------------------------------------------
class MoveEnemy(Enemy):
    RECENT_SCANS_HIT_THRESHOLD = 2.5
    LIGHT_FLATTENER_HIT_THRESHOLD = 3.0
    FLATTENER_HIT_THRESHOLD = 5.9
    DECAY_RATE = 1.8
    BOT_WIDTH = 36.0
    TYPICAL_ANGULAR_BOT_WIDTH = 0.1
    TYPICAL_ESCAPE_RANGE = 0.98
    BULLET_POWER_WEIGHTS = [3.0, 5.0, 1.0]

    def __init__(
        self,
        bot_name,
        distance: float,
        energy: float,
        location: Point,
        heading: float,
        velocity: float,
        abs_bearing: float,
        round_num: int,
        time: int,
        battle_field: BattleField,
        predictor: MovementPredictor,
    ) -> None:
        super().__init__(bot_name, location, distance, energy, heading, velocity, abs_bearing, round_num, time, battle_field, predictor, WaveManager())
        self.damage_taken = 0.0
        self.last_bullet_power = 0.0
        self.last_bullet_fire_time = 0
        self.total_bullet_power = 0.0
        self.total_times_hit = 0
        self.total_distance = 500.0
        self.last_time_hit = LONG_MIN
        self.last_time_closest = LONG_MIN
        self.avoid_being_targeted = False
        self.stay_perpendicular = False
        self.damage_factor = 0.0
        self.raw_1v1_shots_fired = 0
        self.raw_1v1_shots_hit = 0
        self.weighted_1v1_shots_hit = 0.0
        self.raw_1v1_shots_fired_this_round = 0
        self.raw_1v1_shots_hit_this_round = 0
        self.weighted_1v1_shots_hit_this_round = 0.0
        self.wall_hit_damage = WallHitDamage(0.0, 0.0)
        self.is_robot = False
        self._imaginary_wave: Wave | None = None
        self._imaginary_wave_index = -1
        self.init_surf_views()
        self.power_tree = KdTree(len(self.BULLET_POWER_WEIGHTS), None)
        self.power_tree.set_weights(self.BULLET_POWER_WEIGHTS)

    def init_round(self) -> None:
        super().init_round()
        self.last_time_hit = LONG_MIN
        self.last_time_closest = LONG_MIN
        self.last_bullet_fire_time = 0
        self.raw_1v1_shots_fired_this_round = 0
        self.raw_1v1_shots_hit_this_round = 0
        self.weighted_1v1_shots_hit_this_round = 0.0
        self.last_bullet_power = 0.0
        self._imaginary_wave = None
        self.clear_neighbor_cache()

    def init_surf_views(self) -> None:
        simple = KnnView(SimpleFormula()).set_weight(3).set_k(25).set_k_divisor(5).bullet_hits_on()
        normal = KnnView(NormalFormula()).set_weight(40).set_k(20).set_k_divisor(5).set_hit_threshold(3.0).bullet_hits_on()
        recent = KnnView(NormalFormula()).set_weight(100).set_k(1).set_max_data_points(1).set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD).bullet_hits_on()
        recent2 = KnnView(NormalFormula()).set_weight(100).set_k(1).set_max_data_points(5).set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD).bullet_hits_on()
        recent3 = (
            KnnView(NormalFormula()).set_weight(100).set_k(1).set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD).set_decay_rate(self.DECAY_RATE).bullet_hits_on()
        )
        recent4 = (
            KnnView(NormalFormula())
            .set_weight(100)
            .set_k(7)
            .set_k_divisor(4)
            .set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD)
            .set_decay_rate(self.DECAY_RATE)
            .bullet_hits_on()
        )
        recent5 = (
            KnnView(NormalFormula())
            .set_weight(100)
            .set_k(35)
            .set_k_divisor(3)
            .set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD)
            .set_decay_rate(self.DECAY_RATE)
            .bullet_hits_on()
        )
        recent6 = (
            KnnView(NormalFormula())
            .set_weight(100)
            .set_k(100)
            .set_k_divisor(2)
            .set_hit_threshold(self.RECENT_SCANS_HIT_THRESHOLD)
            .set_decay_rate(self.DECAY_RATE)
            .bullet_hits_on()
        )
        light_flattener = (
            KnnView(NormalFormula())
            .set_weight(10)
            .set_k(50)
            .set_max_data_points(1000)
            .set_k_divisor(5)
            .set_padded_hit_threshold(self.LIGHT_FLATTENER_HIT_THRESHOLD)
            .visits_on()
        )
        flattener = (
            KnnView(FlattenerFormula())
            .set_weight(50)
            .set_k(25)
            .set_max_data_points(300)
            .set_k_divisor(12)
            .set_padded_hit_threshold(self.FLATTENER_HIT_THRESHOLD)
            .visits_on()
        )
        flattener2 = (
            KnnView(FlattenerFormula())
            .set_weight(500)
            .set_k(50)
            .set_max_data_points(2000)
            .set_k_divisor(14)
            .set_padded_hit_threshold(self.FLATTENER_HIT_THRESHOLD)
            .set_decay_rate(self.DECAY_RATE)
            .visits_on()
        )
        for view in (simple, normal, recent, recent2, recent3, recent4, recent5, recent6, light_flattener, flattener, flattener2):
            self.add_view(view)

    def execute_1v1(self, current_round: int, current_time: int, my_location: Point) -> None:
        def on_wave_break(w: Wave, wave_break_states: list[RobotState]) -> None:
            self._on_wave_break(w, wave_break_states, current_round, current_time)

        self.wave_manager.check_active_waves(current_time, RobotState(my_location, time=current_time), on_wave_break)

    def process_bullet(self, bullet: BulletRecord, current_round: int, current_time: int) -> Wave | None:
        bullet_location = Point(bullet.x, bullet.y)
        bot_name = bullet.name
        hit_wave = self.wave_manager.find_closest_wave(bullet_location, current_time, FIRING_WAVE, bot_name, bullet.power)
        if hit_wave is None or bot_name != hit_wave.bot_name:
            return None
        hit_guess_factor = hit_wave.guess_factor_of_location(bullet_location)
        for view in self.views.values():
            if view.log_bullet_hits:
                view.log_wave(hit_wave, TimestampedGuessFactor(current_round, current_time, hit_guess_factor))
        return hit_wave

    def avg_bullet_power(self) -> float:
        if self.total_bullet_power == 0:
            return 3.0
        return self.total_bullet_power / self.total_times_hit

    def min_distance_sq(self) -> float:
        return min(self._bot_distances_sq.values(), default=math.inf)

    def bots_closer(self, distance_sq: float) -> int:
        return sum(1 for bot_distance_sq in self._bot_distances_sq.values() if bot_distance_sq < distance_sq)

    def clear_neighbor_cache(self) -> None:
        for view in self.views.values():
            view.clear_cache()

    def get_gun_heat(self, time: int) -> float:
        if time <= 30:
            gun_heat = max(0.0, 3.0 - (time * 0.1))
        else:
            gun_heat = max(0.0, get_gun_heat(self.last_bullet_power) - ((time - self.last_bullet_fire_time) * 0.1))
        return round_to(gun_heat, 6)

    @staticmethod
    def bullet_power_data_point(distance: float, enemy_energy: float, my_energy: float) -> list[float]:
        return [min(distance, 800.0) / 800, min(enemy_energy, 125.0) / 125, min(my_energy, 125.0) / 125]

    def reset_bullet_shadows(self, fired_bullets: list[FiredBullet]) -> None:
        for w in self.wave_manager.all_waves():
            if w.firing_wave:
                w.shadows.clear()
                for bullet in fired_bullets:
                    self.set_shadows_on(w, bullet)

    def set_shadows(self, bullet: FiredBullet) -> None:
        for w in self.wave_manager.all_waves():
            if w.firing_wave:
                self.set_shadows_on(w, bullet)

    def set_shadows_on(self, w: Wave, bullet: FiredBullet) -> None:
        start_time = max(w.fire_time, bullet.fire_time)
        if w.processed_bullet_hit() or w.source_location.distance_sq(bullet.position(start_time)) <= square(w.distance_traveled(start_time)):
            return
        time = start_time
        while True:
            time += 1
            if w.source_location.distance_sq(bullet.position(time)) < square(w.distance_traveled(time)) and time < bullet.death_time:
                self._add_bullet_shadows(w, bullet, time)
                break
            if not self.battle_field.contains_point(bullet.position(time)):
                break

    def _add_bullet_shadows(self, w: Wave, b: FiredBullet, time: int) -> None:
        wave_circle1 = Circle(w.source_location.x, w.source_location.y, w.distance_traveled(time - 1))
        wave_circle2 = Circle(w.source_location.x, w.source_location.y, w.distance_traveled(time))
        bullet_point1 = b.position(time - 1)
        bullet_point2 = b.position(time)
        bullet_seg = LineSeg(bullet_point1.x, bullet_point1.y, bullet_point2.x, bullet_point2.y)
        x_points1 = wave_circle1.intersects(bullet_seg)
        x_points2 = wave_circle2.intersects(bullet_seg)

        if x_points1[0] is None and x_points2[0] is None:
            w.cast_shadow(bullet_point1, bullet_point2)
        elif x_points1[0] is not None:
            if x_points2[0] is not None:
                w.cast_shadow(x_points2[0], x_points1[0])
            elif x_points1[1] is not None:
                if bullet_point1.distance_sq(x_points1[0]) < bullet_point1.distance_sq(x_points1[1]):
                    intersect1, intersect2 = x_points1[0], x_points1[1]
                else:
                    intersect1, intersect2 = x_points1[1], x_points1[0]
                w.cast_shadow(bullet_point1, intersect1)
                w.cast_shadow(intersect2, bullet_point2)
            else:
                w.cast_shadow(bullet_point1, x_points1[0])
        elif x_points2[0] is not None:
            w.cast_shadow(x_points2[0], bullet_point2)

    def new_move_wave(
        self,
        source_location: Point,
        target_location: Point,
        abs_bearing: float,
        fire_round: int,
        fire_time: int,
        bullet_power: float,
        my_energy: float,
        my_heading: float,
        my_velocity: float,
        velocity_sign: int,
        accel: float,
        dl8t: float,
        dl20t: float,
        dl40t: float,
        time_since_reverse_direction: int,
        time_since_velocity_change: int,
    ) -> Wave:
        w = Wave(
            self.bot_name, source_location, target_location, fire_round, fire_time, bullet_power, my_heading, my_velocity, velocity_sign, self.battle_field, self.predictor
        )
        w.set_abs_bearing(abs_bearing)
        w.set_accel(accel)
        w.set_distance(source_location.distance(target_location))
        w.set_dchange_time(time_since_reverse_direction)
        w.set_vchange_time(time_since_velocity_change)
        w.set_distance_last_8_ticks(dl8t)
        w.set_distance_last_20_ticks(dl20t)
        w.set_distance_last_40_ticks(dl40t)
        w.set_target_energy(my_energy)
        w.set_source_energy(self.energy)
        self.wave_manager.add_wave(w)
        return w

    def update_imaginary_wave(self, current_time: int, my_robot_state: RobotState, waves_to_surf: int, predictor: MovementPredictor) -> None:
        self._imaginary_wave_index = -1
        for x in range(waves_to_surf):
            if self.find_surfable_wave(x, my_robot_state) is None:
                self._imaginary_wave_index = x
                break

        enemy_gun_heat = self.get_gun_heat(current_time)
        if self._imaginary_wave_index >= 0 and enemy_gun_heat < 0.1000001:
            self.clear_neighbor_cache()
            if enemy_gun_heat < 0.0000001 and self.wave_manager.size() >= 2:
                self._imaginary_wave = self.wave_manager.get_wave_by_fire_time(current_time)
                previous_state = self.get_state(current_time - 1)
                aimed_from_location = previous_state.location if previous_state is not None else self.last_scan_state.location
            else:
                self._imaginary_wave = self.wave_manager.get_wave_by_fire_time(current_time + 1)
                aimed_from_location = self.last_scan_state.location
                source_location = self.battle_field.translate_to_field(MovementPredictor.next_location_of_state(self.last_scan_state))
                if source_location.distance(my_robot_state.location) < self.BOT_WIDTH:
                    source_location = self.last_scan_state.location
                if self._imaginary_wave is not None:
                    self._imaginary_wave.source_location = source_location

            imaginary_wave = self._imaginary_wave
            if imaginary_wave is not None:  # None after a skipped turn
                imaginary_wave.target_wall_distance = min(
                    1.5,
                    self.battle_field.orbital_wall_distance(
                        aimed_from_location, imaginary_wave.target_location, self.last_bullet_power, imaginary_wave.orbit_direction
                    ),
                )
                imaginary_wave.target_rev_wall_distance = min(
                    1.5,
                    self.battle_field.orbital_wall_distance(
                        aimed_from_location, imaginary_wave.target_location, self.last_bullet_power, -imaginary_wave.orbit_direction
                    ),
                )
                imaginary_wave.abs_bearing = absolute_bearing(aimed_from_location, imaginary_wave.target_location)

    def find_surfable_wave(self, surf_wave_index: int, my_robot_state: RobotState) -> Wave | None:
        surfable_wave = self.wave_manager.find_surfable_wave(surf_wave_index, my_robot_state, BREAKING_CENTER)
        if surfable_wave is None and self._imaginary_wave is not None and surf_wave_index == self._imaginary_wave_index:
            surfable_wave = self._imaginary_wave
        return surfable_wave

    def update_firing_wave(self, current_time: int, bullet_power: float, my_state_log: RobotStateLog, fired_bullets: list[FiredBullet]) -> None:
        fire_time = current_time - 1
        enemy_wave = self.wave_manager.get_wave_by_fire_time(fire_time)
        if enemy_wave is None:
            enemy_wave = self.wave_manager.interpolate_wave_by_fire_time(
                fire_time, current_time, self.last_scan_state.heading, self.last_scan_state.velocity, my_state_log, self.battle_field, self.predictor
            )
            if enemy_wave is not None:
                enemy_wave.firing_wave = True
                self.wave_manager.add_wave(enemy_wave)
        if enemy_wave is None:
            return

        aimed_from_state = self.get_state(current_time - 2)
        source_state = self.get_state(current_time - 1)
        my_state = my_state_log.get_state(current_time - 2)
        aimed_from_location = aimed_from_state.location if aimed_from_state is not None else enemy_wave.source_location
        if source_state is not None:
            enemy_wave.source_location = source_state.location
        if my_state is not None:
            enemy_wave.target_location = my_state.location
        enemy_wave.abs_bearing = absolute_bearing(aimed_from_location, enemy_wave.target_location)
        enemy_wave.set_bullet_power(bullet_power)
        enemy_wave.target_wall_distance = min(
            1.5, self.battle_field.orbital_wall_distance(aimed_from_location, enemy_wave.target_location, self.last_bullet_power, enemy_wave.orbit_direction)
        )
        enemy_wave.target_rev_wall_distance = min(
            1.5, self.battle_field.orbital_wall_distance(aimed_from_location, enemy_wave.target_location, self.last_bullet_power, -enemy_wave.orbit_direction)
        )

        if self._imaginary_wave is not None:
            self.clear_neighbor_cache()
        self._imaginary_wave = None

        enemy_wave.firing_wave = True
        self.last_bullet_power = bullet_power
        self.last_bullet_fire_time = enemy_wave.fire_time
        for bullet in fired_bullets:
            self.set_shadows_on(enemy_wave, bullet)

        data_point = self.bullet_power_data_point(enemy_wave.target_distance, enemy_wave.source_energy, enemy_wave.target_energy)
        self.power_tree.add_point(data_point, bullet_power)

    def update_damage_factor(self) -> None:
        if self.alive:
            self.time_alive_together += 1
            self.total_distance += self.distance
        self.damage_factor = ((self.damage_taken + 10) * self.total_distance) / self.time_alive_together

    def guess_bullet_power(self, my_energy: float) -> float:
        num_bullets = self.power_tree.size()
        if num_bullets == 0:
            return 1.9
        search_point = self.bullet_power_data_point(self.distance, self.energy, my_energy)
        bullet_powers = self.power_tree.nearest_neighbor(search_point, int(min(20, math.ceil(num_bullets / 3.0))))
        power_total = sum(entry.value for entry in bullet_powers)
        return round_to(power_total / len(bullet_powers), 6)

    def _on_wave_break(self, w: Wave, wave_break_states: list[RobotState], current_round: int, current_time: int) -> None:
        if not w.firing_wave:
            return
        precise_intersection = w.precise_intersection(wave_break_states)
        if precise_intersection is None:
            return
        for view in self.views.values():
            if view.log_visits:
                guess_factor = w.guess_factor(precise_intersection.angle)
                view.log_wave(w, TimestampedGuessFactor(current_round, current_time, guess_factor))

        if not w.bullet_hit_bullet:
            self.raw_1v1_shots_fired += 1
            self.raw_1v1_shots_fired_this_round += 1
            if w.hit_by_bullet:
                angular_bot_width = precise_intersection.bandwidth * 2
                this_hit = (self.TYPICAL_ANGULAR_BOT_WIDTH / angular_bot_width) * (w.escape_angle_range() / self.TYPICAL_ESCAPE_RANGE)
                self.weighted_1v1_shots_hit += this_hit
                self.weighted_1v1_shots_hit_this_round += this_hit
                self.raw_1v1_shots_hit += 1
                self.raw_1v1_shots_hit_this_round += 1


# MoveDataManager -------------------------------------------------------------------------
class MoveDataManager(EnemyDataManager):
    NON_ZERO_VELOCITY_THRESHOLD = 0.1
    DIRECTION_CHANGE_THRESHOLD = math.pi / 2
    EARLIEST_FIRE_TIME = 30

    def __init__(self, enemies_total: int, battle_field: BattleField, predictor: MovementPredictor) -> None:
        super().__init__(enemies_total, battle_field, predictor)
        self._previous_heading = 0.0
        self._current_heading = 0.0
        self._time_since_reverse_direction = 0
        self._time_since_velocity_change = 0
        self._last_velocity = 0.0
        self._previous_velocity = 0.0
        self._last_non_zero_velocity = 0.0
        self._my_state_log = RobotStateLog()
        self._fired_bullets: list[FiredBullet] = []

    def execute(self, round_num: int, time: int, my_location: Point, heading: float, velocity: float) -> None:
        self._my_state_log.add_state(RobotState(my_location, heading, velocity, time))
        self._previous_heading = self._current_heading
        if abs(velocity) > self.NON_ZERO_VELOCITY_THRESHOLD:
            self._last_non_zero_velocity = velocity
        self._previous_velocity = velocity
        self._current_heading = normal_absolute_angle(heading + (math.pi if self._last_non_zero_velocity < 0 else 0.0))
        self.update_bot_distances(my_location)
        self._update_damage_factors()
        self._remove_old_fired_bullets(time)
        if self._duel_enemy is not None:
            self._duel_enemy.execute_1v1(round_num, time, my_location)
        else:
            self.update_timers(velocity)

    def _remove_old_fired_bullets(self, current_time: int) -> None:
        self._fired_bullets = [bullet for bullet in self._fired_bullets if self.battle_field.contains_point(bullet.position(current_time))]

    def _update_damage_factors(self) -> None:
        if self.is_melee_battle():
            for move_data in self.get_all_enemy_data():
                move_data.update_damage_factor()

    def init_round(self) -> None:
        super().init_round()
        self._current_heading = self._previous_heading = 0.0
        self._time_since_reverse_direction = 0
        self._time_since_velocity_change = 0
        self._previous_velocity = self._last_velocity = self._last_non_zero_velocity = 0.0
        self._my_state_log.clear()
        self._fired_bullets.clear()

    def new_enemy(self, e: ScannedRobotEvent, enemy_location: Point, abs_bearing: float, current_round: int, is_1v1: bool) -> MoveEnemy:
        move_data = MoveEnemy(
            e.name, e.distance, e.energy, enemy_location, e.heading_radians, e.velocity, abs_bearing, current_round, e.time, self.battle_field, self.predictor
        )
        self._enemies[e.name] = move_data
        if is_1v1:
            self._duel_enemy = move_data
        return move_data

    def update_enemy(self, e: ScannedRobotEvent, enemy_location: Point, abs_bearing: float, current_round: int, is_1v1: bool) -> MoveEnemy:
        move_data = self.get_enemy_data(e.name)
        move_data.wall_hit_damage = self._get_wall_hit_damage(e, enemy_location, move_data)
        move_data.set_robot_state(RobotState(enemy_location, e.heading_radians, e.velocity, e.time))
        move_data.energy = e.energy
        move_data.distance = e.distance
        move_data.abs_bearing = abs_bearing
        move_data.last_scan_round = current_round
        if is_1v1:
            self._duel_enemy = move_data
        return move_data

    def _get_wall_hit_damage(self, e: ScannedRobotEvent, enemy_location: Point, move_data: MoveEnemy) -> WallHitDamage:
        last_state = move_data.last_scan_state
        if (
            not move_data.is_robot
            and e.time - last_state.time == 1
            and abs(last_state.velocity - e.velocity) > 2
            and abs(e.velocity) < 0.0001
            and distance_to_wall(enemy_location, self.battle_field) < 0.0001
        ):
            if abs(e.energy - move_data.energy) < 0.0001:
                move_data.is_robot = True
            else:
                max_speed = min(8.0, abs(last_state.velocity) + ACCELERATION)
                min_speed = abs(last_state.velocity) - DECELERATION
                return WallHitDamage(get_wall_hit_damage(min_speed), get_wall_hit_damage(max_speed))
        return WallHitDamage(0.0, 0.0)

    def on_hit_by_bullet(self, bullet: BulletRecord, current_round: int, current_time: int) -> None:
        """Everything Diamond did on ``HitByBulletEvent`` except the enemy's
        energy bonus, which the bot applies once the scan that carries it has
        been read (see ``apply_energy_delta``)."""
        bot_name = bullet.name
        move_data = self.get_enemy_data(bot_name)
        if move_data is not None:
            move_data.last_time_hit = current_time
            move_data.damage_taken += get_bullet_damage(bullet.power)
            move_data.total_bullet_power += bullet.power
            move_data.total_times_hit += 1
            hit_wave = move_data.process_bullet(bullet, current_round, current_time)
            if hit_wave is not None:
                hit_wave.hit_by_bullet = True
        else:
            warn(self.get_label(), f"A bot shot me that I never knew existed! ({bot_name})")
        if self._duel_enemy is not None:
            self._duel_enemy.clear_neighbor_cache()

    def on_bullet_hit_bullet(self, my_bullet: BulletRecord, hit_bullet: BulletRecord, current_round: int, current_time: int) -> None:
        bot_name = hit_bullet.name
        move_data = self.get_enemy_data(bot_name)
        if move_data is not None:
            hit_wave = move_data.process_bullet(hit_bullet, current_round, current_time)
            if hit_wave is not None:
                hit_wave.bullet_hit_bullet = True
        elif bot_name != my_bullet.name:
            warn(self.get_label(), f"One of my bullets hit a bullet from a bot that I never knew existed! ({bot_name})")
        self._remove_fired_bullet(my_bullet, current_time)
        if self._duel_enemy is not None:
            self._duel_enemy.reset_bullet_shadows(self._fired_bullets)
            self._duel_enemy.clear_neighbor_cache()

    def on_bullet_hit(self, victim_name, bullet: BulletRecord) -> None:
        """``damageGiven`` only; the energy drop is applied by ``apply_energy_delta``."""
        move_data = self.get_enemy_data(victim_name)
        if move_data is None:
            warn(self.get_label(), f"One of my bullets hit a bot that I never knew existed! ({victim_name})")
            return
        move_data.damage_given += get_bullet_damage(bullet.power)

    def apply_energy_delta(self, bot_name, delta: float) -> None:
        move_data = self.get_enemy_data(bot_name)
        if move_data is not None:
            move_data.energy += delta

    def update_enemy_waves(
        self,
        my_location: Point,
        previous_enemy_energy: float,
        bot_name,
        current_round: int,
        current_time: int,
        my_energy: float,
        my_heading: float,
        my_velocity: float,
        waves_to_surf: int,
    ) -> None:
        my_robot_state = RobotState(my_location, my_heading, my_velocity, current_time)
        self._my_state_log.add_state(my_robot_state)
        move_data = self.get_enemy_data(bot_name)
        detected_enemy_bullet = False
        energy_drop = previous_enemy_energy - move_data.energy - move_data.wall_hit_damage.max
        if 0.0999 < energy_drop < 3.0001 and move_data.get_gun_heat(current_time) < 0.0001:
            detected_enemy_bullet = True

        self.update_timers(my_velocity)
        velocity_sign = non_zero_sign(my_velocity if abs(my_velocity) > self.NON_ZERO_VELOCITY_THRESHOLD else self._last_non_zero_velocity)
        accel = limit(-DECELERATION, accel_of(my_velocity, self._previous_velocity), ACCELERATION)
        dl8t = self._my_state_log.get_displacement_distance(my_location, current_time, 8)
        dl20t = self._my_state_log.get_displacement_distance(my_location, current_time, 20)
        dl40t = self._my_state_log.get_displacement_distance(my_location, current_time, 40)
        guessed_power = move_data.guess_bullet_power(my_energy)
        fire_time = current_time + 1
        enemy_next_location = self.battle_field.translate_to_field(MovementPredictor.next_location_of_state(move_data.last_scan_state))

        move_data.new_move_wave(
            enemy_next_location,
            my_location,
            absolute_bearing(move_data.last_scan_state.location, my_location),
            current_round,
            fire_time,
            guessed_power,
            my_energy,
            my_heading,
            my_velocity,
            velocity_sign,
            accel,
            dl8t,
            dl20t,
            dl40t,
            self._time_since_reverse_direction,
            self._time_since_velocity_change,
        )
        move_data.update_imaginary_wave(current_time, my_robot_state, waves_to_surf, self.predictor)
        if detected_enemy_bullet and current_time > self.EARLIEST_FIRE_TIME:
            move_data.update_firing_wave(current_time, energy_drop, self._my_state_log, self._fired_bullets)

    def update_timers(self, velocity: float) -> None:
        if abs(normal_relative_angle(self._current_heading - self._previous_heading)) > self.DIRECTION_CHANGE_THRESHOLD:
            self._time_since_reverse_direction = 0
        else:
            self._time_since_reverse_direction += 1
        if abs(velocity - self._last_velocity) > 0.5:
            self._time_since_velocity_change = 0
        else:
            self._time_since_velocity_change += 1
        self._last_velocity = velocity

    def my_state_log(self) -> RobotStateLog:
        return self._my_state_log

    def add_fired_bullet(self, bullet: FiredBullet) -> None:
        self._fired_bullets.append(bullet)
        if self._duel_enemy is not None:
            self._duel_enemy.set_shadows(bullet)

    def _remove_fired_bullet(self, my_bullet: BulletRecord, current_time: int) -> None:
        closest_distance_sq = math.inf
        closest_fired_bullet = None
        bullet_point = Point(my_bullet.x, my_bullet.y)
        for fired_bullet in self._fired_bullets:
            this_distance_sq = fired_bullet.position(current_time).distance_sq(bullet_point)
            if this_distance_sq < closest_distance_sq:
                closest_distance_sq = this_distance_sq
                closest_fired_bullet = fired_bullet
        if closest_fired_bullet is not None and closest_distance_sq < square(40):
            closest_fired_bullet.death_time = current_time

    def get_label(self) -> str:
        return "move"

    def get_fired_bullets(self) -> list[FiredBullet]:
        return self._fired_bullets


# SurfMover -------------------------------------------------------------------------------------
COUNTER_CLOCKWISE_OPTION = -1
STOP_OPTION = 0
CLOCKWISE_OPTION = 1
SURF_OPTIONS = (COUNTER_CLOCKWISE_OPTION, STOP_OPTION, CLOCKWISE_OPTION)


class DistanceController:
    DESIRED_DISTANCE = 650.0
    MAX_ATTACK_ANGLE = math.pi * 0.45

    def surf_attack_angle(self, current_distance: float) -> float:
        return self._attack_angle(current_distance, 0.6)

    def orbit_attack_angle(self, current_distance: float) -> float:
        return self._attack_angle(current_distance, 1.65)

    def _attack_angle(self, current_distance: float, offset_multiplier: float) -> float:
        distance_factor = (current_distance - self.DESIRED_DISTANCE) / self.DESIRED_DISTANCE
        return limit(-self.MAX_ATTACK_ANGLE, distance_factor * offset_multiplier, self.MAX_ATTACK_ANGLE)


class SurfMover:
    WALL_STICK = 160.0
    MEA_WALL_STICK = 100.0
    DISTANCING_DANGER_BASE = 2.5
    BASE_DANGER_FACTOR = 1.0

    def __init__(self, robot, battle_field: BattleField) -> None:
        self._robot = robot
        self._battle_field = battle_field
        self._predictor = MovementPredictor(battle_field)
        self._last_surf_option = CLOCKWISE_OPTION
        self._last_surf_destination: Point | None = None
        self._stop_destination: Point | None = None
        self._surf_option_dangers: dict[int, float] = {}
        self._surf_option_destinations: dict[int, Point] = {}
        self._distancer = DistanceController()
        self._last_wave_surfed: Wave | None = None

    def init_round(self) -> None:
        self._last_surf_destination = None
        self._stop_destination = None

    def move(self, my_robot_state: RobotState, duel_enemy: MoveEnemy | None, waves_to_surf: int) -> None:
        if duel_enemy is None:
            return
        surf_wave = duel_enemy.find_surfable_wave(FIRST_WAVE, my_robot_state)
        if surf_wave is None:
            self.orbit(my_robot_state.location, duel_enemy)
        else:
            self.surf(my_robot_state, duel_enemy, surf_wave, waves_to_surf)

    def orbit(self, my_location: Point, duel_enemy: MoveEnemy) -> None:
        robot = self._robot
        robot.set_max_velocity(8.0)
        enemy_state = duel_enemy.last_scan_state
        orbit_abs_bearing = absolute_bearing(enemy_state.location, my_location)
        retreat_angle = self._distancer.orbit_attack_angle(my_location.distance(enemy_state.location))
        counter_go_angle = orbit_abs_bearing + (COUNTER_CLOCKWISE_OPTION * (HALF_PI + retreat_angle))
        counter_go_angle = self._wall_smoothing(my_location, counter_go_angle, COUNTER_CLOCKWISE_OPTION)
        clockwise_go_angle = orbit_abs_bearing + (CLOCKWISE_OPTION * (HALF_PI + retreat_angle))
        clockwise_go_angle = self._wall_smoothing(my_location, clockwise_go_angle, CLOCKWISE_OPTION)

        if abs(normal_relative_angle(clockwise_go_angle - orbit_abs_bearing)) < abs(normal_relative_angle(counter_go_angle - orbit_abs_bearing)):
            self._last_surf_option = CLOCKWISE_OPTION
            go_angle = clockwise_go_angle
        else:
            self._last_surf_option = COUNTER_CLOCKWISE_OPTION
            go_angle = counter_go_angle
        robot.set_back_as_front(go_angle)

    def surf(self, my_robot_state: RobotState, duel_enemy: MoveEnemy, surf_wave: Wave, waves_to_surf: int) -> None:
        robot = self._robot
        if surf_wave is not self._last_wave_surfed:
            duel_enemy.clear_neighbor_cache()
            self._last_wave_surfed = surf_wave
            self._last_surf_destination = None
            self._stop_destination = None

        going_clockwise = self._last_surf_option == CLOCKWISE_OPTION
        self._update_surf_dangers(my_robot_state, duel_enemy, waves_to_surf, going_clockwise)
        counter_danger = self._surf_option_dangers[COUNTER_CLOCKWISE_OPTION]
        stop_danger = self._surf_option_dangers[STOP_OPTION]
        clockwise_danger = self._surf_option_dangers[CLOCKWISE_OPTION]

        if stop_danger <= counter_danger and stop_danger <= clockwise_danger:
            if self._stop_destination is None:
                self._stop_destination = self._surf_option_destinations[self._last_surf_option]
            surf_destination = self._stop_destination
            robot.set_max_velocity(0.0)
            self._last_surf_destination = None
        else:
            robot.set_max_velocity(8.0)
            self._last_surf_option = CLOCKWISE_OPTION if clockwise_danger < counter_danger else COUNTER_CLOCKWISE_OPTION
            surf_destination = self._surf_option_destinations[self._last_surf_option]
            self._last_surf_destination = surf_destination
            self._stop_destination = None

        go_angle = absolute_bearing(my_robot_state.location, surf_destination)
        go_angle = self._wall_smoothing(my_robot_state.location, go_angle, self._last_surf_option)
        robot.set_back_as_front(go_angle)

    def _update_surf_dangers(self, my_robot_state: RobotState, duel_enemy: MoveEnemy, waves_to_surf: int, going_clockwise: bool) -> None:
        best_surf_danger = math.inf
        for test_option in self._get_sorted_surf_options():
            test_danger = self.check_danger(
                my_robot_state, duel_enemy, my_robot_state, test_option, going_clockwise, FIRST_WAVE, waves_to_surf, best_surf_danger, RobotStateLog()
            )
            self._surf_option_dangers[test_option] = test_danger
            best_surf_danger = min(best_surf_danger, test_danger)

    def _get_sorted_surf_options(self) -> list[int]:
        surf_options = list(SURF_OPTIONS)
        for x in range(len(surf_options)):
            lowest_danger = self._get_surf_option_danger(surf_options[x])
            for y in range(x + 1, len(surf_options)):
                if self._get_surf_option_danger(surf_options[y]) < lowest_danger:
                    lowest_danger = self._get_surf_option_danger(surf_options[y])
                    surf_options[x], surf_options[y] = surf_options[y], surf_options[x]
        return surf_options

    def _get_surf_option_danger(self, surf_option: int) -> float:
        return self._surf_option_dangers.get(surf_option, 0.0)

    def check_danger(
        self,
        my_robot_state: RobotState,
        duel_enemy: MoveEnemy,
        start_state: RobotState,
        surf_option: int,
        previously_moving_clockwise: bool,
        surf_wave_index: int,
        num_waves_to_surf: int,
        cutoff_danger: float,
        predicted_state_log: RobotStateLog,
    ) -> float:
        surf_wave = duel_enemy.find_surfable_wave(surf_wave_index, my_robot_state)
        if surf_wave is None:
            return 0.0

        danger_states: list[RobotState] = []
        start_wave_position = surf_wave.check_wave_position(start_state)
        if surf_wave_index > FIRST_WAVE and start_wave_position != MIDAIR:
            danger_states.extend(self._replay_surf_states(surf_wave, predicted_state_log))
        if start_wave_position == GONE and not danger_states:
            return 0.0

        predict_clockwise = self._predict_clockwise(surf_option, previously_moving_clockwise)
        predicted_state = start_state
        passed_state = start_state
        wave_hit = False
        if surf_option == STOP_OPTION:
            max_velocity = 0.0
            smoothing_surf_option = CLOCKWISE_OPTION if predict_clockwise else COUNTER_CLOCKWISE_OPTION
        else:
            max_velocity = 8.0
            smoothing_surf_option = surf_option
        if surf_wave_index == FIRST_WAVE and surf_option == STOP_OPTION and self._stop_destination is not None:
            surf_destination = self._stop_destination
        else:
            surf_destination = self._surf_destination(surf_wave, surf_wave_index, start_state, smoothing_surf_option)
        if surf_wave_index == FIRST_WAVE:
            self._surf_option_destinations[surf_option] = surf_destination

        while True:
            if not wave_hit and surf_wave.check_wave_position(predicted_state, False, BREAKING_FRONT) == BREAKING_FRONT:
                danger_state = predicted_state
                while True:
                    danger_states.append(danger_state)
                    danger_state = self._predict_surf_location(danger_state, surf_destination, 0.0, smoothing_surf_option)
                    if surf_wave.check_wave_position(danger_state, True) == GONE:
                        break
                wave_hit = True

            wave_position = surf_wave.check_wave_position(predicted_state, True)
            if wave_position == BREAKING_CENTER or wave_position == GONE:
                passed_state = predicted_state
                break
            predicted_state_log.add_state(predicted_state)
            predicted_state = self._predict_surf_location(predicted_state, surf_destination, max_velocity, smoothing_surf_option)

        intersection = surf_wave.precise_intersection(danger_states)
        if intersection is None:
            return 0.0
        base_danger_score = self.normalized_enemy_hit_rate(duel_enemy) * self.BASE_DANGER_FACTOR
        danger = base_danger_score + self.get_danger_score(duel_enemy, surf_wave, intersection, surf_wave_index)
        danger *= surf_wave.shadow_factor(intersection)
        danger *= get_bullet_damage(surf_wave.bullet_power())
        current_distance_to_wave_source = my_robot_state.location.distance(surf_wave.source_location)
        current_distance_to_wave = current_distance_to_wave_source - surf_wave.distance_traveled(self._robot.time)
        time_to_impact = max(1.0, current_distance_to_wave / surf_wave.bullet_speed())
        danger /= time_to_impact
        danger *= self._distancing_danger(start_state.location, passed_state.location, duel_enemy.last_scan_state.location)

        if surf_wave_index + 1 < num_waves_to_surf and danger < cutoff_danger:
            next_counter_clockwise_danger = self.check_danger(
                my_robot_state, duel_enemy, passed_state, COUNTER_CLOCKWISE_OPTION, predict_clockwise, surf_wave_index + 1, num_waves_to_surf, cutoff_danger, predicted_state_log.clone()
            )
            next_stop_danger = self.check_danger(
                my_robot_state, duel_enemy, passed_state, STOP_OPTION, predict_clockwise, surf_wave_index + 1, num_waves_to_surf, cutoff_danger, predicted_state_log.clone()
            )
            next_clockwise_danger = self.check_danger(
                my_robot_state, duel_enemy, passed_state, CLOCKWISE_OPTION, predict_clockwise, surf_wave_index + 1, num_waves_to_surf, cutoff_danger, predicted_state_log.clone()
            )
            danger += min(next_counter_clockwise_danger, min(next_stop_danger, next_clockwise_danger))
        return danger

    @staticmethod
    def _predict_clockwise(surf_option: int, previously_moving_clockwise: bool) -> bool:
        if surf_option == STOP_OPTION:
            return previously_moving_clockwise
        return surf_option == CLOCKWISE_OPTION

    @staticmethod
    def _replay_surf_states(surf_wave: Wave, predicted_state_log: RobotStateLog) -> list[RobotState]:
        return [state for state in predicted_state_log.all_states() if is_breaking(surf_wave.check_wave_position(state))]

    def _surf_destination(self, surf_wave: Wave, surf_wave_index: int, start_state: RobotState, surf_option: int) -> Point:
        if surf_wave_index == FIRST_WAVE and self._last_surf_option == surf_option and self._last_surf_destination is not None:
            return self._last_surf_destination
        attack_angle = self._distancer.surf_attack_angle(surf_wave.source_location.distance(start_state.location))
        mea_target = self._predictor.precise_escape_angle(
            surf_option, surf_wave.source_location, surf_wave.fire_time, surf_wave.bullet_speed(), start_state, attack_angle, self.MEA_WALL_STICK
        )
        return mea_target.location

    def _predict_surf_location(self, robot_state: RobotState, surf_destination: Point, max_velocity: float, smoothing_surf_option: int) -> RobotState:
        go_angle = self._wall_smoothing(robot_state.location, absolute_bearing(robot_state.location, surf_destination), smoothing_surf_option)
        return self._predictor.next_location_toward(robot_state, max_velocity, go_angle, False)

    def _wall_smoothing(self, start_location: Point, go_angle_radians: float, surf_option: int) -> float:
        return self._battle_field.wall_smoothing(start_location, go_angle_radians, surf_option, self.WALL_STICK)

    def _distancing_danger(self, start_location: Point, predicted_location: Point, enemy_location: Point) -> float:
        distance_to_enemy = enemy_location.distance(start_location)
        predicted_distance_to_enemy = enemy_location.distance(predicted_location)
        distance_quotient = java_div(distance_to_enemy, predicted_distance_to_enemy)
        return math.pow(self.DISTANCING_DANGER_BASE, distance_quotient) / self.DISTANCING_DANGER_BASE

    def get_danger_score(self, duel_enemy: MoveEnemy, w: Wave, intersection: Intersection, surf_wave_index: int) -> float:
        danger_angle = intersection.angle
        bandwidth = intersection.bandwidth
        total_danger = 0.0
        total_scan_weight = 0.0
        enabled_size = 0
        hit_percentage = self.normalized_enemy_hit_percentage(duel_enemy)
        error_margin = self.hit_percentage_margin_of_error(duel_enemy)
        for view in duel_enemy.views.values():
            if not view.enabled(hit_percentage, error_margin):
                continue
            enabled_size += view.size()
            nearest_neighbors = self._get_nearest_neighbors(view, w, surf_wave_index)
            weight_map = view.get_decay_weights(nearest_neighbors)
            density = 0.0
            view_scan_weight = 0.0
            for entry in nearest_neighbors:
                tsgf = entry.value
                scan_weight = weight_map[tsgf] * inverse_sqrt(entry.distance)
                x_firing_angle = normalize_angle(w.firing_angle(tsgf.guess_factor), danger_angle)
                if not w.shadowed(x_firing_angle):
                    ux = java_div(x_firing_angle - danger_angle, bandwidth)
                    density += scan_weight * math.pow(2, -abs(ux))
                view_scan_weight += scan_weight
            total_scan_weight += view_scan_weight * view.weight
            total_danger += view.weight * density
        if enabled_size == 0:
            return self._default_danger(w, intersection)
        return java_div(total_danger, total_scan_weight)

    @staticmethod
    def _get_nearest_neighbors(view: KnnView, w: Wave, surf_wave_index: int) -> list:
        neighbors = view.cached_neighbors.get(surf_wave_index)
        if neighbors is None:
            neighbors = view.nearest_neighbors(w, False)
            view.cached_neighbors[surf_wave_index] = neighbors
        return neighbors

    @staticmethod
    def normalized_enemy_hit_rate(duel_enemy: MoveEnemy | None) -> float:
        if duel_enemy is None or duel_enemy.raw_1v1_shots_fired == 0:
            return 0.0
        return duel_enemy.weighted_1v1_shots_hit / duel_enemy.raw_1v1_shots_fired

    def normalized_enemy_hit_percentage(self, duel_enemy: MoveEnemy | None) -> float:
        return 100 * self.normalized_enemy_hit_rate(duel_enemy)

    @staticmethod
    def raw_enemy_hit_percentage(duel_enemy: MoveEnemy | None) -> float:
        if duel_enemy is None or duel_enemy.raw_1v1_shots_fired == 0:
            return 0.0
        return (duel_enemy.raw_1v1_shots_hit / duel_enemy.raw_1v1_shots_fired) * 100.0

    def hit_percentage_margin_of_error(self, duel_enemy: MoveEnemy | None) -> float:
        if duel_enemy is None:
            return 100.0
        return 100 * margin_of_error(self.normalized_enemy_hit_rate(duel_enemy), duel_enemy.raw_1v1_shots_fired)

    @staticmethod
    def _default_danger(w: Wave, intersection: Intersection) -> float:
        guess_factors = (0.0, 0.85)
        weights = (3.0, 1.0)
        danger = 0.0
        for guess_factor, weight in zip(guess_factors, weights):
            firing_angle = w.firing_angle(guess_factor)
            ux = java_div(firing_angle - normalize_angle(intersection.angle, firing_angle), intersection.bandwidth)
            danger += weight * math.pow(2, -abs(ux))
        return danger

    def round_over(self, duel_enemy: MoveEnemy) -> None:
        if self._robot.verbose:
            print(
                f"Enemy normalized hit %: {round_to(self.normalized_enemy_hit_percentage(duel_enemy), 2)}\n"
                f"Enemy raw hit %: {round_to(self.raw_enemy_hit_percentage(duel_enemy), 2)}",
                file=sys.stderr,
            )

    def get_surf_option_dangers(self) -> dict[int, float]:
        return self._surf_option_dangers


# MeleeMover -----------------------------------------------------------------------------------
class Destination:
    __slots__ = ("location", "risk", "go_angle")

    def __init__(self, location: Point, risk: float, go_angle: float) -> None:
        self.location = location
        self.risk = risk
        self.go_angle = go_angle


class OldLocation:
    __slots__ = ("location", "time")

    def __init__(self, location: Point, time: int) -> None:
        self.location = location
        self.time = time


class MeleeMover:
    CURRENT_DESTINATION_BIAS = 0.8
    RECENT_LOCATIONS_TO_STORE = 50
    NUM_SLICES_BOT = 64

    def __init__(self, robot, battle_field: BattleField) -> None:
        self._robot = robot
        self._battle_field = battle_field
        self._predictor = MovementPredictor(battle_field)
        self._recent_locations: list[OldLocation] = []
        self._current_destination: Destination | None = None

    def init_round(self, robot, my_location: Point) -> None:
        self._robot = robot
        self._current_destination = Destination(my_location, math.inf, 0.0)
        self._recent_locations.clear()

    def move(self, my_location: Point, enemies: list[MoveEnemy], closest_enemy: MoveEnemy | None) -> None:
        if not enemies or closest_enemy is None:
            return
        self._update_recent_locations(self._robot.time, my_location)
        destinations = self._generate_destinations(my_location, enemies, closest_enemy)
        next_destination = self._get_next_destination(my_location, destinations)
        go_angle = absolute_bearing(my_location, next_destination.location)
        self._robot.set_back_as_front(go_angle)
        self._current_destination = next_destination

    def _update_recent_locations(self, current_time: int, my_location: Point) -> None:
        if current_time % 7 == 0:
            for _ in range(5):
                self._recent_locations.insert(
                    0, OldLocation(project(my_location, random.random() * math.pi * 2, 5 + random.random() * random.random() * 200), current_time)
                )
            del self._recent_locations[self.RECENT_LOCATIONS_TO_STORE :]

    def _generate_destinations(self, my_location: Point, enemies: list[MoveEnemy], closest_enemy: MoveEnemy) -> list[Destination]:
        possible_destinations = self._generate_points_around_bot(my_location, enemies, closest_enemy)
        current = self._current_destination
        if my_location.distance(current.location) <= my_location.distance(closest_enemy.last_scan_state.location):
            current_go_angle = absolute_bearing(my_location, current.location)
            current_risk = self.CURRENT_DESTINATION_BIAS * self._evaluate_risk(enemies, current.location, current.go_angle)
            self._current_destination = Destination(current.location, current_risk, current_go_angle)
            possible_destinations.append(self._current_destination)
        return possible_destinations

    def _generate_points_around_bot(self, my_location: Point, enemies: list[MoveEnemy], closest_enemy: MoveEnemy) -> list[Destination]:
        destinations: list[Destination] = []
        distance_to_closest_bot = my_location.distance(closest_enemy.last_scan_state.location)
        movement_stick = min(100 + random.random() * 100, distance_to_closest_bot)
        slice_size = (2 * math.pi) / self.NUM_SLICES_BOT
        for x in range(self.NUM_SLICES_BOT):
            angle = x * slice_size
            dest = self._battle_field.translate_to_field(project(my_location, angle, movement_stick))
            destinations.append(Destination(dest, self._evaluate_risk(enemies, dest, angle), angle))
        return destinations

    def _evaluate_risk(self, enemies: list[MoveEnemy], destination: Point, go_angle: float) -> float:
        risk = 0.0
        my_energy = self._robot.energy
        for move_data in enemies:
            if move_data.alive:
                distance_sq = destination.distance_sq(move_data.last_scan_state.location)
                risk += (
                    limit(0.25, java_div(move_data.energy, my_energy), 4.0)
                    * (1 + abs(math.cos(move_data.abs_bearing - go_angle)))
                    * move_data.damage_factor
                    / (distance_sq * (move_data.bots_closer(distance_sq * 0.8) + 1))
                )
        random_risk = 0.0
        for old_location in self._recent_locations:
            random_risk += java_div(30.0, old_location.location.distance_sq(destination))
        risk *= 1 + random_risk
        return risk

    def _get_next_destination(self, my_location: Point, destinations: list[Destination]) -> Destination:
        robot = self._robot
        current_state = RobotState(my_location, robot.heading_radians, robot.velocity, robot.time)
        while True:
            next_destination = self._safest_destination(my_location, destinations)
            if next_destination in destinations:
                destinations.remove(next_destination)
            if not self._would_hit_wall(current_state, next_destination) or not destinations:
                return next_destination

    def _safest_destination(self, my_location: Point, possible_destinations: list[Destination]) -> Destination:
        lowest_risk = math.inf
        safest = None
        for destination in possible_destinations:
            if destination.risk < lowest_risk:
                lowest_risk = destination.risk
                safest = destination
        if safest is None:
            safest = self._current_destination
        return safest

    def _would_hit_wall(self, current_state: RobotState, destination: Destination) -> bool:
        for _ in range(5):
            current_state = self._predictor.next_location_toward(
                current_state, 8.0, absolute_bearing(current_state.location, destination.location), True
            )
            if not self._battle_field.contains_point(current_state.location):
                return True
        return False


# DiamondWhoosh ---------------------------------------------------------------------------------
class DiamondWhoosh:
    def __init__(self, robot, battle_field: BattleField) -> None:
        self._robot = robot
        self._battle_field = battle_field
        predictor = MovementPredictor(battle_field)
        self._move_data_manager = MoveDataManager(robot.others, battle_field, predictor)
        self._melee_mover = MeleeMover(robot, battle_field)
        self._surf_mover = SurfMover(robot, battle_field)

    def init_round(self, robot) -> None:
        self._robot = robot
        self._move_data_manager.init_round()
        self._melee_mover.init_round(robot, self.my_location())
        self._surf_mover.init_round()

    def execute(self) -> None:
        robot = self._robot
        self._move_data_manager.execute(robot.round_num, robot.time, self.my_location(), robot.heading_radians, robot.velocity)
        self._move()

    def _move(self) -> None:
        robot = self._robot
        if self.is_1v1():
            self._surf_mover.move(self._move_data_manager.my_state_log().get_state(robot.time), self._move_data_manager.duel_enemy(), WAVES_TO_SURF)
        else:
            my_location = self.my_location()
            self._melee_mover.move(my_location, self._move_data_manager.get_all_enemy_data(), self._move_data_manager.get_closest_living_bot(my_location))

    def on_scanned_robot(self, e: ScannedRobotEvent) -> None:
        robot = self._robot
        my_location = self.my_location()
        bot_name = e.name
        enemy_location = e.location
        abs_bearing = normal_absolute_angle(absolute_bearing(my_location, enemy_location))
        if self._move_data_manager.has_enemy(bot_name):
            previous_enemy_energy = self._move_data_manager.get_enemy_data(bot_name).energy
            self._move_data_manager.update_enemy(e, enemy_location, abs_bearing, robot.round_num, self.is_1v1())
        else:
            previous_enemy_energy = e.energy
            self._move_data_manager.new_enemy(e, enemy_location, abs_bearing, robot.round_num, self.is_1v1())

        if self.is_1v1() and self._move_data_manager.duel_enemy() is not None:
            self._move_data_manager.update_enemy_waves(
                self.my_location(), previous_enemy_energy, bot_name, robot.round_num, robot.time, robot.energy, robot.heading_radians, robot.velocity, WAVES_TO_SURF
            )

    def on_robot_death(self, bot_name) -> None:
        self._move_data_manager.on_robot_death(bot_name)

    def on_hit_by_bullet(self, bullet: BulletRecord) -> None:
        self._move_data_manager.on_hit_by_bullet(bullet, self._robot.round_num, self._robot.time)

    def on_bullet_hit_bullet(self, my_bullet: BulletRecord, hit_bullet: BulletRecord) -> None:
        self._move_data_manager.on_bullet_hit_bullet(my_bullet, hit_bullet, self._robot.round_num, self._robot.time)

    def on_bullet_hit(self, victim_name, bullet: BulletRecord) -> None:
        self._move_data_manager.on_bullet_hit(victim_name, bullet)

    def apply_energy_delta(self, bot_name, delta: float) -> None:
        self._move_data_manager.apply_energy_delta(bot_name, delta)

    def round_over(self) -> None:
        duel_enemy = self._move_data_manager.duel_enemy()
        if self.is_1v1() and duel_enemy is not None:
            self._surf_mover.round_over(duel_enemy)

    def my_location(self) -> Point:
        return Point(self._robot.x, self._robot.y)

    def is_1v1(self) -> bool:
        return self._robot.others <= 1

    # FireListener
    def bullet_fired(self, bullet: FiredBullet) -> None:
        self._move_data_manager.add_fired_bullet(bullet)

    @property
    def move_data_manager(self) -> MoveDataManager:
        return self._move_data_manager

    @property
    def surf_mover(self) -> SurfMover:
        return self._surf_mover

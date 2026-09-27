"""``voidious.gun``: ``DiamondFist`` and everything under it: the gun data
manager and its per-enemy waves, the virtual-gun rating, the Main, TripHammer
KNN, Anti-Surfer, Perceptual and Melee guns, and the formulas that turn a
wave into a data point."""
from __future__ import annotations

import math
import sys

from diamond_port.dia_utils import (
    ACCELERATION,
    DECELERATION,
    BattleField,
    DistanceFormula,
    Point,
    RobotState,
    TimestampedFiringAngle,
    absolute_bearing,
    accel as accel_of,
    bot_width_aim_angle,
    cube,
    generate_firing_angles,
    get_bullet_damage,
    inverse_sqrt,
    java_div,
    limit,
    non_zero_sign,
    normal_absolute_angle,
    normal_relative_angle,
    round_to,
    signum,
)
from diamond_port.enemy import IS_BULLET_HIT, IS_VISIT, BulletRecord, Enemy, EnemyDataManager, ScannedRobotEvent, warn
from diamond_port.kd_tree import KdTree
from diamond_port.knn_view import KnnView
from diamond_port.movement_predictor import MovementPredictor
from diamond_port.perceptual_dna import SKNN_HEX_STRING
from diamond_port.wave import BREAKING_CENTER, DIRECT, FIRING_WAVE, MIDAIR, ORBITAL, Wave, WaveManager


# FireListener.FiredBullet -----------------------------------------------------
class FiredBullet:
    __slots__ = ("fire_time", "source_location", "firing_angle", "bullet_speed", "dx", "dy", "death_time")

    def __init__(self, fire_time: int, source_location: Point, firing_angle: float, bullet_speed: float) -> None:
        self.fire_time = fire_time
        self.source_location = source_location
        self.firing_angle = firing_angle
        self.bullet_speed = bullet_speed
        self.dx = math.sin(firing_angle) * bullet_speed
        self.dy = math.cos(firing_angle) * bullet_speed
        self.death_time = 2**63 - 1

    def distance_traveled(self, current_time: int) -> float:
        return (current_time - self.fire_time) * self.bullet_speed

    def position(self, current_time: int) -> Point:
        ticks = current_time - self.fire_time
        return Point(self.source_location.x + (self.dx * ticks), self.source_location.y + (self.dy * ticks))


# Formulas --------------------------------------------------------------------------
def _accel_attribute(wave: Wave) -> float:
    return ((wave.target_accel / (DECELERATION if wave.target_accel < 0 else ACCELERATION)) + 1) / 2


def _vchange_attribute(wave: Wave) -> float:
    return min(1.0, java_div(float(wave.target_vchange_time), wave.target_distance / wave.bullet_speed())) / 1.0


class MainGunFormula(DistanceFormula):
    def __init__(self, enemies_total: int) -> None:
        self.enemies_total = enemies_total
        self.weights = [3.0, 4.0, 3.0, 2.0, 2.0, 4.0, 2.0, 3.0, 2.0, 2.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            _accel_attribute(w),
            min(1.0, w.target_wall_distance),
            min(1.0, w.target_rev_wall_distance),
            _vchange_attribute(w),
            0.0 if aiming else w.virtuality(),
            math.sqrt(float(w.enemies_alive - 1) / max(self.enemies_total - 1, 1)),
        ]


class AntiSurferFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [3.0, 4.0, 3.0, 2.0, 2.0, 4.0, 2.0, 3.0, 1.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            _accel_attribute(w),
            min(1.0, w.target_wall_distance),
            min(1.0, w.target_rev_wall_distance),
            _vchange_attribute(w),
            0.0 if aiming else w.virtuality(),
        ]


class TripHammerFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [0.34, 10.0, 3.13, 2.58, 8.38, 7.91, 8.67, 5.12, 2.34, 0.38]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(3.0, w.bullet_power()) / 3,
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            (w.target_accel + DECELERATION) / (DECELERATION + ACCELERATION),
            min(1.25, w.target_wall_distance),
            min(1.15, w.target_rev_wall_distance),
            _vchange_attribute(w),
            0.0 if aiming else w.virtuality(),
        ]


class MeleeFormula(DistanceFormula):
    def __init__(self) -> None:
        self.weights = [4.0, 6.0, 2.0, 4.0, 3.0, 1.0, 1.0]

    def data_point_from_wave(self, w: Wave, aiming: bool = False) -> list[float]:
        return [
            min(91.0, w.target_distance / w.bullet_speed()) / 91,
            ((w.target_velocity_sign * w.target_velocity) + 0.1) / 8.1,
            (math.cos(w.target_relative_heading) + 1) / 2,
            min(1.0, w.target_wall_distance),
            min(1.0, w.target_rev_wall_distance),
            w.target_dl8t / 64,
            w.target_dl20t / 160,
        ]


# GunEnemy ----------------------------------------------------------------------------
class GunEnemy(Enemy):
    NON_ZERO_VELOCITY_THRESHOLD = 0.1

    def __init__(
        self,
        bot_name,
        distance: float,
        energy: float,
        location: Point,
        round_num: int,
        time: int,
        heading: float,
        velocity: float,
        abs_bearing: float,
        battle_field: BattleField,
        predictor: MovementPredictor,
    ) -> None:
        super().__init__(bot_name, location, distance, energy, heading, velocity, abs_bearing, round_num, time, battle_field, predictor, WaveManager())
        self._wave_breaks = 0
        self.last_non_zero_velocity = velocity
        self.previous_velocity = 0.0
        self.time_since_direction_change = 0
        self.time_since_velocity_change = 0
        self.time_moving_at_me = 0
        self.last_wave_fired: Wave | None = None
        self.hit_locations: list[Point] = []

    def init_round(self) -> None:
        super().init_round()
        self.last_non_zero_velocity = 0.0
        self.previous_velocity = 0.0
        self.time_since_direction_change = 0
        self.time_since_velocity_change = 0
        self.hit_locations.clear()

    def execute(
        self,
        current_time: int,
        last_bullet_fired_time: int,
        bullet_power: float,
        current_gun_heat: float,
        my_location: Point,
        is_1v1: bool,
        enemies_total: int,
        gun_data_listeners: list,
    ) -> None:
        for wave in self.wave_manager.current_waves(current_time):
            self.update_wave(wave, my_location, bullet_power, last_bullet_fired_time, current_gun_heat, is_1v1, gun_data_listeners)

        def on_wave_break(wave: Wave, wave_break_states: list[RobotState]) -> None:
            self.process_wave_break(wave, wave_break_states, current_time, enemies_total, gun_data_listeners)

        self.wave_manager.check_active_waves(current_time, self.last_scan_state, on_wave_break)

    def update_wave(self, w: Wave, my_location: Point, bullet_power: float, last_bullet_fired_time: int, gun_heat: float, is_1v1: bool, listeners: list) -> None:
        if w.alt_wave:
            return
        w.gun_heat = gun_heat
        w.last_bullet_fired_time = last_bullet_fired_time
        if self.last_scan_state.time == w.fire_time:
            w.source_location = my_location
            w.target_location = self.last_scan_state.location
            w.abs_bearing = absolute_bearing(my_location, self.last_scan_state.location)

    def process_wave_break(self, w: Wave, wave_break_states: list[RobotState], current_time: int, enemies_total: int, listeners: list) -> None:
        if not wave_break_states:
            return
        guess_factor = 0.0
        precise_intersection = None
        if enemies_total == 1:
            precise_intersection = w.precise_intersection(wave_break_states)
            if precise_intersection is None:
                return
            guess_factor = w.guess_factor_precise(precise_intersection.angle)

        wave_break_state = wave_break_states[len(wave_break_states) // 2]
        disp_vector = w.displacement_vector_of_state(wave_break_state)
        self.log_wave(w, disp_vector, guess_factor, current_time, IS_VISIT)
        self._wave_breaks += 1

        if w.enemies_alive == 1 and w.firing_wave and not w.alt_wave:
            if precise_intersection is None:
                precise_intersection = w.precise_intersection(wave_break_states)
                if precise_intersection is None:
                    return
            for listener in listeners:
                listener.on_1v1_firing_wave_break(w, precise_intersection.angle, precise_intersection.bandwidth)

    def process_bullet_hit(self, bullet: BulletRecord, current_time: int, is_1v1_battle: bool, log_hit_wave: bool) -> Wave | None:
        bullet_location = Point(bullet.x, bullet.y)
        hit_wave = self.wave_manager.find_closest_wave(bullet_location, current_time, FIRING_WAVE, self.bot_name, bullet.power)
        if hit_wave is None:
            return None
        if log_hit_wave:
            hit_vector = hit_wave.displacement_vector(self.last_scan_state.location, current_time)
            hit_factor = 0.0
            if is_1v1_battle:
                hit_factor = hit_wave.guess_factor_precise_of_location(self.last_scan_state.location)
            self.log_wave(hit_wave, hit_vector, hit_factor, current_time, IS_BULLET_HIT)
        return hit_wave

    def log_bullet_hit_location(self, bullet: BulletRecord) -> None:
        self.hit_locations.append(Point(bullet.x, bullet.y))

    def log_wave(self, w: Wave, disp_vector: Point, guess_factor: float, time: int, is_visit: bool) -> None:
        for view in self.views.values():
            if (
                ((is_visit and view.log_visits) or (not is_visit and view.log_bullet_hits))
                and (view.log_virtual or w.firing_wave)
                and (view.log_melee or w.enemies_alive <= 1)
            ):
                view.log_wave(w, TimestampedFiringAngle(w.fire_round, time, guess_factor, disp_vector))

    def new_gun_wave(
        self,
        source_location: Point,
        target_location: Point,
        fire_round: int,
        fire_time: int,
        last_bullet_fired_time: int,
        bullet_power: float,
        my_energy: float,
        gun_heat: float,
        enemies_alive: int,
        accel: float,
        dl8t: float,
        dl20t: float,
        dl40t: float,
        alt_wave: bool,
    ) -> Wave:
        new_wave = Wave(
            self.bot_name,
            source_location,
            target_location,
            fire_round,
            fire_time,
            bullet_power,
            self.last_scan_state.heading,
            self.last_scan_state.velocity,
            non_zero_sign(self.last_non_zero_velocity),
            self.battle_field,
            self.predictor,
        )
        new_wave.set_accel(accel)
        new_wave.set_distance(source_location.distance(target_location))
        new_wave.set_dchange_time(self.time_since_direction_change)
        new_wave.set_vchange_time(self.time_since_velocity_change)
        new_wave.set_distance_last_8_ticks(dl8t)
        new_wave.set_distance_last_20_ticks(dl20t)
        new_wave.set_distance_last_40_ticks(dl40t)
        new_wave.set_target_energy(self.energy)
        new_wave.set_source_energy(my_energy)
        new_wave.set_gun_heat(gun_heat)
        new_wave.set_enemies_alive(enemies_alive)
        new_wave.set_last_bullet_fired_time(last_bullet_fired_time)
        new_wave.set_alt_wave(alt_wave)
        new_wave.set_wall_distances(ORBITAL if enemies_alive <= 1 else DIRECT)
        if my_energy > 0:
            self.wave_manager.add_wave(new_wave)
        return new_wave

    def mark_firing_waves(self, current_time: int, is_1v1: bool, listeners: list) -> None:
        for wave in self.wave_manager.current_waves(current_time):
            if wave.alt_wave:
                continue
            wave.firing_wave = True
            if is_1v1:
                for listener in listeners:
                    listener.on_mark_firing_wave(wave)

    def find_surfable_wave(self, aim_wave: Wave, surf_index: int) -> Wave | None:
        target_state = RobotState(aim_wave.target_location, time=aim_wave.fire_time)
        return self.wave_manager.find_surfable_wave(surf_index, target_state, BREAKING_CENTER)

    def update_timers(self, velocity: float) -> None:
        if abs(velocity - self.last_non_zero_velocity) > 0.5:
            self.time_since_velocity_change = 0
        if abs(velocity) > self.NON_ZERO_VELOCITY_THRESHOLD:
            if signum(velocity) != signum(self.last_non_zero_velocity):
                self.time_since_direction_change = 0
            self.last_non_zero_velocity = velocity

    def get_last_wave_fire_time(self) -> int:
        return self.wave_manager.get_last_fire_time()

    def interpolate_gun_wave(self, fire_time: int, current_time: int, my_heading: float, my_velocity: float, enemy_state: RobotState) -> Wave | None:
        wave = self.wave_manager.interpolate_wave_by_fire_time(
            fire_time, current_time, my_heading, my_velocity, self.state_log, self.battle_field, self.predictor
        )
        if wave is not None and wave.check_wave_position(enemy_state) == MIDAIR:
            self.wave_manager.add_wave(wave)
            return wave
        return None

    def advancing_velocity(self) -> float:
        return -math.cos(self.last_scan_state.heading - self.abs_bearing) * self.last_scan_state.velocity

    def is_rammer(self) -> bool:
        return (float(self.time_moving_at_me) / self.time_alive_together) > 0.5

    def get_wave_breaks(self) -> int:
        return self._wave_breaks


# GunDataManager ----------------------------------------------------------------------
class GunDataManager(EnemyDataManager):
    WARNING_BULLET_HIT_UNKNOWN = "I shot a bot that I never knew existed!"
    WARNING_BULLET_HIT_BULLET_UNKNOWN = "I shot a bullet by a bot that I never knew existed!"

    def __init__(self, enemies_total: int, battle_field: BattleField, predictor: MovementPredictor) -> None:
        super().__init__(enemies_total, battle_field, predictor)
        self._listeners: list = []
        self._last_bullet_fired_time = 0

    def init_round(self) -> None:
        super().init_round()
        self._last_bullet_fired_time = 0

    def execute(self, current_round: int, current_time: int, bullet_power: float, current_gun_heat: float, my_location: Point, is_1v1: bool) -> None:
        self.update_bot_distances(my_location)
        for gun_data in self.get_all_enemy_data():
            if gun_data.alive:
                gun_data.execute(
                    current_time, self._last_bullet_fired_time, bullet_power, current_gun_heat, my_location, is_1v1, self.enemies_total, self._listeners
                )

    def new_enemy(self, e: ScannedRobotEvent, enemy_location: Point, abs_bearing: float, current_round: int, is_1v1: bool) -> GunEnemy:
        if self.has_enemy(e.name):
            raise ValueError(f"GunEnemy already exists for bot: {e.name}")
        gun_data = GunEnemy(
            e.name, e.distance, e.energy, enemy_location, current_round, e.time, e.heading_radians, e.velocity, abs_bearing, self.battle_field, self.predictor
        )
        gun_data.update_timers(e.velocity)
        self._enemies[e.name] = gun_data
        if is_1v1:
            self._duel_enemy = gun_data
        return gun_data

    def update_enemy(self, e: ScannedRobotEvent, enemy_location: Point, abs_bearing: float, current_round: int, is_1v1: bool) -> GunEnemy:
        gun_data = self.get_enemy_data(e.name)
        time_since_last_scan = e.time - gun_data.last_scan_state.time
        gun_data.time_since_direction_change += time_since_last_scan
        gun_data.time_since_velocity_change += time_since_last_scan

        gun_data.update_timers(e.velocity)
        gun_data.distance = e.distance
        gun_data.abs_bearing = abs_bearing
        gun_data.energy = e.energy
        gun_data.last_scan_round = current_round
        gun_data.previous_velocity = gun_data.last_scan_state.velocity
        gun_data.set_robot_state(RobotState(enemy_location, e.heading_radians, e.velocity, e.time))
        gun_data.time_alive_together += 1
        if gun_data.advancing_velocity() > 6:
            gun_data.time_moving_at_me += 1
        if is_1v1:
            self._duel_enemy = gun_data
        return gun_data

    def on_bullet_hit(self, victim_name, bullet: BulletRecord, current_time: int) -> None:
        gun_data = self.get_enemy_data(victim_name)
        if gun_data is not None:
            bullet_damage = min(get_bullet_damage(bullet.power), gun_data.energy)
            gun_data.damage_given += bullet_damage
            gun_data.log_bullet_hit_location(bullet)
        else:
            warn(self.get_label(), f"{self.WARNING_BULLET_HIT_UNKNOWN} ({victim_name})")
        for gun_data in self.get_all_enemy_data():
            hit_wave = gun_data.process_bullet_hit(bullet, current_time, self.enemies_total == 1, True)
            if hit_wave is not None:
                hit_wave.hit_by_bullet = True

    def on_bullet_hit_bullet(self, my_bullet: BulletRecord, hit_bullet: BulletRecord, current_time: int) -> None:
        bot_name = hit_bullet.name
        for gun_data in self.get_all_enemy_data():
            hit_wave = gun_data.process_bullet_hit(my_bullet, current_time, self.enemies_total == 1, bot_name == gun_data.bot_name)
            if hit_wave is not None:
                hit_wave.bullet_hit_bullet = True
        if not self.has_enemy(bot_name) and bot_name != my_bullet.name:
            warn(self.get_label(), f"{self.WARNING_BULLET_HIT_BULLET_UNKNOWN} ({bot_name})")

    def get_damage_given(self) -> float:
        return sum(gun_data.damage_given for gun_data in self.get_all_enemy_data())

    def get_average_energy(self) -> float:
        total_energy = 0.0
        enemies_alive = 0
        for gun_data in self.get_all_enemy_data():
            if gun_data.alive:
                total_energy += gun_data.energy
                enemies_alive += 1
        return 0.0 if enemies_alive == 0 else total_energy / enemies_alive

    def mark_firing_waves(self, current_time: int, is_1v1: bool) -> None:
        self._last_bullet_fired_time = current_time
        for gun_data in self.get_all_enemy_data():
            gun_data.mark_firing_waves(current_time, is_1v1, self._listeners)

    def fire_next_tick_wave(
        self,
        my_next_location: Point,
        target_location: Point,
        target_name,
        current_round: int,
        current_time: int,
        bullet_power: float,
        my_energy: float,
        gun_heat: float,
        my_heading: float,
        my_velocity: float,
        enemies_alive: int,
    ) -> None:
        gun_data = self.get_enemy_data(target_name)
        last_scan_state = gun_data.last_scan_state
        enemy_next_location = self.battle_field.translate_to_field(
            MovementPredictor.next_location_from(target_location, last_scan_state.heading, last_scan_state.velocity)
        )
        accel = limit(-DECELERATION, accel_of(last_scan_state.velocity, gun_data.previous_velocity), ACCELERATION)
        fire_time = current_time + 1
        last_wave_fire_time = gun_data.get_last_wave_fire_time()
        state_log = gun_data.state_log
        dl8t = state_log.get_displacement_distance(target_location, current_time, 8)
        dl20t = state_log.get_displacement_distance(target_location, current_time, 20)
        dl40t = state_log.get_displacement_distance(target_location, current_time, 40)

        next_wave = gun_data.new_gun_wave(
            my_next_location,
            enemy_next_location,
            current_round,
            fire_time,
            self._last_bullet_fired_time,
            bullet_power,
            my_energy,
            gun_heat,
            enemies_alive,
            accel,
            dl8t,
            dl20t,
            dl40t,
            False,
        )
        gun_data.last_wave_fired = next_wave

        for alt_gun_data in self.get_all_enemy_data():
            if alt_gun_data.alive and alt_gun_data.bot_name != target_name:
                # Diamond passes velocity and heading in the wrong order here;
                # kept as written.
                alt_next_location = self.battle_field.translate_to_field(
                    MovementPredictor.next_location_from(
                        alt_gun_data.last_scan_state.location, alt_gun_data.last_scan_state.velocity, alt_gun_data.last_scan_state.heading
                    )
                )
                gun_data.new_gun_wave(
                    alt_next_location,
                    enemy_next_location,
                    current_round,
                    fire_time,
                    self._last_bullet_fired_time,
                    bullet_power,
                    alt_gun_data.energy,
                    gun_heat,
                    enemies_alive,
                    accel,
                    dl8t,
                    dl20t,
                    dl40t,
                    True,
                )

        if self._duel_enemy is not None and last_wave_fire_time > 0:
            for time in range(last_wave_fire_time + 1, fire_time):
                gun_data.interpolate_gun_wave(time, current_time, my_heading, my_velocity, last_scan_state)

    def add_listener(self, listener) -> None:
        self._listeners.append(listener)

    def get_enemies_total(self) -> int:
        return self.enemies_total

    def get_duel_data_size(self) -> int:
        return self._duel_enemy.get_wave_breaks()

    def get_label(self) -> str:
        return "gun"


# Guns ------------------------------------------------------------------------------------
class DuelGun:
    def __init__(self) -> None:
        self._firing_angles: dict[Wave, float] = {}

    def clear_cache(self) -> None:
        self._firing_angles.clear()

    def aim(self, w: Wave) -> float:
        angle = self._firing_angles.get(w)
        if angle is None:
            angle = self.aim_internal(w)
            self._firing_angles[w] = angle
        return angle

    def get_label(self) -> str:
        raise NotImplementedError

    def aim_internal(self, w: Wave) -> float:
        raise NotImplementedError

    def new_data_views(self) -> list[KnnView]:
        raise NotImplementedError


class MainGun(DuelGun):
    VIEW_NAME = "Main"
    K_SIZE = 100
    K_DIVISOR = 10

    def __init__(self, gun_data_manager: GunDataManager, battle_field: BattleField) -> None:
        super().__init__()
        self._gun_data_manager = gun_data_manager
        self._battle_field = battle_field

    def get_label(self) -> str:
        return "Main Gun"

    def aim_internal(self, w: Wave) -> float:
        gun_data = self._gun_data_manager.get_enemy_data(w.bot_name)
        view = gun_data.views[self.VIEW_NAME]
        if view.size() == 0:
            return w.abs_bearing
        nearest_neighbors = view.nearest_neighbors(w, True)
        firing_angles: list[float | None] = []
        for entry in nearest_neighbors:
            projected_location = w.project_location_from_displacement_vector(entry.value.displacement_vector)
            if not self._battle_field.contains_point(projected_location):
                firing_angles.append(None)
            else:
                firing_angles.append(normal_relative_angle(w.firing_angle_from_target_location(projected_location) - w.abs_bearing))

        best_angle = None
        best_density = -math.inf
        bandwidth = 2 * bot_width_aim_angle(w.source_location.distance(w.target_location))
        for x, x_firing_angle in enumerate(firing_angles):
            if x_firing_angle is None:
                continue
            x_density = 0.0
            for y, y_firing_angle in enumerate(firing_angles):
                if x == y or y_firing_angle is None:
                    continue
                ux = (x_firing_angle - y_firing_angle) / bandwidth
                x_density += math.exp(-0.5 * ux * ux)
            if x_density > best_density:
                best_angle = x_firing_angle
                best_density = x_density
        if best_angle is None:
            return w.abs_bearing
        return normal_absolute_angle(w.abs_bearing + best_angle)

    def new_data_views(self) -> list[KnnView]:
        return [
            KnnView(MainGunFormula(self._gun_data_manager.get_enemies_total()))
            .set_k(self.K_SIZE)
            .set_k_divisor(self.K_DIVISOR)
            .visits_on()
            .virtual_waves_on()
            .melee_on()
            .set_name(self.VIEW_NAME)
        ]


class AntiSurferGun(DuelGun):
    FIRING_ANGLES = 59

    def __init__(self, gun_data_manager: GunDataManager, battle_field: BattleField) -> None:
        super().__init__()
        self._gun_data_manager = gun_data_manager
        self._battle_field = battle_field
        self._view_names: list[str] = []
        self._formula = AntiSurferFormula()
        self._is_1v1_battle = gun_data_manager.get_enemies_total() == 1

    def get_label(self) -> str:
        return "Anti-Surfer Gun"

    def aim_internal(self, w: Wave) -> float:
        gun_data = self._gun_data_manager.get_enemy_data(w.bot_name)
        nearest_neighbors = []
        neighbor_weights: list[float] = []
        for view_name in self._view_names:
            view = gun_data.views[view_name]
            if view.size() < view.k_divisor:
                continue
            this_neighbors = view.nearest_neighbors(w, True)
            nearest_neighbors.extend(this_neighbors)
            neighbor_weights.extend([view.weight] * len(this_neighbors))

        if not nearest_neighbors:
            return w.abs_bearing

        firing_angles: list[float | None] = []
        for entry in nearest_neighbors:
            if self._is_1v1_battle:
                guess_factor = entry.value.guess_factor
                firing_angles.append(normal_relative_angle(guess_factor * w.orbit_direction * w.precise_escape_angle(guess_factor >= 0)))
            else:
                projected_location = w.project_location_from_displacement_vector(entry.value.displacement_vector)
                if not self._battle_field.contains_point(projected_location):
                    firing_angles.append(None)
                else:
                    firing_angles.append(normal_relative_angle(w.firing_angle_from_target_location(projected_location) - w.abs_bearing))

        best_angle = None
        best_density = -math.inf
        bandwidth = bot_width_aim_angle(w.source_location.distance(w.target_location)) * 2
        real_angles = generate_firing_angles(self.FIRING_ANGLES, w.max_escape_angle())
        for x_firing_angle in real_angles:
            x_density = 0.0
            for y, y_firing_angle in enumerate(firing_angles):
                if y_firing_angle is None:
                    continue
                ux = (x_firing_angle - y_firing_angle) / bandwidth
                x_density += math.exp(-0.5 * ux * ux) * neighbor_weights[y]
            if x_density > best_density:
                best_angle = x_firing_angle
                best_density = x_density
        if best_angle is None:
            return w.abs_bearing
        return normal_absolute_angle(w.abs_bearing + best_angle)

    def new_data_views(self) -> list[KnnView]:
        views = []
        for name, max_points in (("asView1", 125), ("asView2", 400), ("asView3", 1500), ("asView4", 4000)):
            views.append(KnnView(self._formula).set_k(3).set_max_data_points(max_points).set_k_divisor(10).visits_on().virtual_waves_on().set_name(name))
        for view in views:
            if view.name not in self._view_names:
                self._view_names.append(view.name)
        return views


class TripHammerKnnGun(DuelGun):
    VIEW_NAME = "TripHammerKNN"
    FIRING_ANGLES = 59
    MAX_K_SIZE = 225
    K_DIVISOR = 9
    INITIAL_WEIGHTS = [0.94, 10.0, 1.73, 3.7, 3.31, 2.13, 5.51, 1.26, 1.57, 5.51]
    FINAL_WEIGHTS = [4.25, 5.43, 0.16, 4.25, 8.74, 3.39, 4.41, 8.03, 7.24, 4.41]
    FINAL_TIMES = [28920, 23040, 23100, 1740, 16680, 5580, 0, 11280, 21420, 1920]

    def __init__(self, gun_data_manager: GunDataManager) -> None:
        super().__init__()
        self._gun_data_manager = gun_data_manager
        self._num_firing_angles = self.FIRING_ANGLES
        self._max_k = self.MAX_K_SIZE
        self._k_divisor = self.K_DIVISOR
        self._formula = TripHammerFormula()

    def get_label(self) -> str:
        return "Main Gun"

    def aim_internal(self, w: Wave) -> float:
        enemy_data = self._gun_data_manager.get_enemy_data(w.bot_name)
        view = enemy_data.views[self.VIEW_NAME]
        view_size = view.size()
        if view_size == 0:
            return w.abs_bearing

        view.set_weights(self._get_weights(view_size))
        nearest_neighbors = view.nearest_neighbors(w, True)
        firing_angles: list[float] = []
        weights: list[float] = []
        for entry in nearest_neighbors:
            guess_factor = entry.value.guess_factor
            firing_angles.append(normal_relative_angle(guess_factor * w.orbit_direction * w.precise_escape_angle(guess_factor >= 0)))
            weights.append(inverse_sqrt(entry.distance))

        bandwidth = 2 * bot_width_aim_angle(w.source_location.distance(w.target_location))
        best_angle = None
        best_density = -math.inf
        real_angles = generate_firing_angles(self._num_firing_angles, w.max_escape_angle())
        for real_angle in real_angles:
            density = 0.0
            for y, firing_angle in enumerate(firing_angles):
                ux = (real_angle - firing_angle) / bandwidth
                if abs(ux) < 1:
                    density += (1 - cube(abs(ux))) * weights[y]
            if density > best_density:
                best_angle = real_angle
                best_density = density
        if best_angle is None:
            return w.abs_bearing
        return normal_absolute_angle(w.abs_bearing + best_angle)

    def _get_weights(self, view_size: int) -> list[float]:
        new_weights = []
        for x in range(len(self.INITIAL_WEIGHTS)):
            final_time = self.FINAL_TIMES[x]
            progress = 1.0 if final_time == 0 else min(1.0, float(view_size - 1) / final_time)
            new_weights.append(self.INITIAL_WEIGHTS[x] + progress * (self.FINAL_WEIGHTS[x] - self.INITIAL_WEIGHTS[x]))
        return new_weights

    def new_data_views(self) -> list[KnnView]:
        return [KnnView(self._formula).set_k(self._max_k).set_k_divisor(self._k_divisor).visits_on().virtual_waves_on().set_name(self.VIEW_NAME)]


class PerceptualGun(DuelGun):
    """A fixed 1000-point kd-tree, evolved offline, used until real data exists."""

    NUM_POINTS = 1000
    WEIGHT_BITS = 7
    COORDINATE_BITS = 7
    GUESSFACTOR_BITS = 7
    NUM_ATTR = 7
    GUESSFACTORS = 2**GUESSFACTOR_BITS

    _weights: list[float] | None = None
    _tree: KdTree | None = None

    def __init__(self) -> None:
        super().__init__()
        if PerceptualGun._tree is None:
            PerceptualGun._weights, PerceptualGun._tree = self._decode()

    def get_label(self) -> str:
        return "Perceptual Gun"

    @classmethod
    def _decode(cls) -> tuple[list[float], KdTree]:
        hex_digits = SKNN_HEX_STRING[2:]
        bits = "".join(format(int(ch, 16), "04b") for ch in hex_digits)
        length = cls.NUM_ATTR * cls.WEIGHT_BITS + cls.NUM_POINTS * (cls.NUM_ATTR * cls.COORDINATE_BITS + cls.GUESSFACTOR_BITS)
        bits = bits[:length]

        def number(position: int, size: int) -> int:
            return int(bits[position : position + size], 2)

        max_weight = 2**cls.WEIGHT_BITS - 1
        max_coordinate = 2**cls.COORDINATE_BITS - 1
        weights = [number(x * cls.WEIGHT_BITS, cls.WEIGHT_BITS) / max_weight for x in range(cls.NUM_ATTR)]
        num_points = (len(bits) - cls.NUM_ATTR * cls.WEIGHT_BITS) // (cls.NUM_ATTR * cls.COORDINATE_BITS + cls.GUESSFACTOR_BITS)
        tree = KdTree(cls.NUM_ATTR)
        point_bits = cls.NUM_ATTR * cls.COORDINATE_BITS + cls.GUESSFACTOR_BITS
        base = cls.NUM_ATTR * cls.WEIGHT_BITS
        for x in range(num_points):
            start = base + x * point_bits
            point = [(number(start + y * cls.COORDINATE_BITS, cls.COORDINATE_BITS) / max_coordinate) * weights[y] for y in range(cls.NUM_ATTR)]
            tree.add_point(point, number(start + cls.NUM_ATTR * cls.COORDINATE_BITS, cls.GUESSFACTOR_BITS))
        return weights, tree

    def aim_internal(self, w: Wave) -> float:
        p = [
            abs(w.target_velocity) / 8.0,
            min(w.target_distance / w.bullet_speed(), 90.0) / 90.0,
            math.sin(w.target_relative_heading),
            (math.cos(w.target_relative_heading) + 1) / 2,
            (w.target_accel + DECELERATION) / (DECELERATION + ACCELERATION),
            min(1.25, w.target_wall_distance) / 1.25,
            min(1.15, w.target_rev_wall_distance) / 1.15,
        ]
        wp = [value * weight for value, weight in zip(p, self._weights)]
        guess_factor_index = self._tree.nearest_neighbor(wp, 1)[0].value
        half = self.GUESSFACTORS // 2
        if self.GUESSFACTORS % 2 == 0:
            if guess_factor_index == half or guess_factor_index == half - 1:
                guess_factor = 0.0
            else:
                guess_factor = float(guess_factor_index - half + 1) / half
        else:
            guess_factor = float(guess_factor_index - half) / half
        return w.abs_bearing + (w.orbit_direction * guess_factor * w.precise_escape_angle(guess_factor >= 0))

    def new_data_views(self) -> list[KnnView]:
        return []


class MeleeGun:
    VIEW_NAME = "Melee"
    MAX_SCANS = 100

    class MeleeFiringAngle:
        __slots__ = ("angle", "distance", "bandwidth", "scan_weight", "wave")

        def __init__(self, angle: float, distance: float, bandwidth: float, scan_weight: float, wave: Wave) -> None:
            self.angle = angle
            self.distance = distance
            self.bandwidth = bandwidth
            self.scan_weight = scan_weight
            self.wave = wave

    def __init__(self, gun_data_manager: GunDataManager, battle_field: BattleField) -> None:
        self._gun_data_manager = gun_data_manager
        self._battle_field = battle_field

    def aim_at_everyone(self, my_next_location: Point, current_time: int, enemies_alive: int, bullet_power: float, closest_bot: GunEnemy) -> float:
        firing_angles: list[MeleeGun.MeleeFiringAngle] = []
        k_size = self._get_common_k_size(enemies_alive)
        for gun_data in self._gun_data_manager.get_all_enemy_data():
            view = gun_data.views.get(self.VIEW_NAME)
            if gun_data.alive and view is not None and view.size() >= 10 and gun_data.last_wave_fired is not None:
                enemy_angles: list[MeleeGun.MeleeFiringAngle] = []
                aim_wave = gun_data.last_wave_fired
                aim_wave.set_bullet_power(bullet_power)
                nearest_neighbors = view.nearest_neighbors(aim_wave, True, k_size)
                total_scan_weight = 0.0
                for entry in nearest_neighbors:
                    scan_weight = inverse_sqrt(entry.distance)
                    total_scan_weight += scan_weight
                    firing_angle = self._get_firing_angle(my_next_location, current_time, entry.value.displacement_vector, scan_weight, aim_wave)
                    if firing_angle is not None:
                        enemy_angles.append(firing_angle)
                for enemy_angle in enemy_angles:
                    enemy_angle.scan_weight = java_div(enemy_angle.scan_weight, total_scan_weight)
                firing_angles.extend(enemy_angles)

        best_angle = None
        best_density = -math.inf
        for x_firing_angle in firing_angles:
            x_density = 0.0
            for y_firing_angle in firing_angles:
                ux = normal_relative_angle(x_firing_angle.angle - y_firing_angle.angle) / y_firing_angle.bandwidth
                x_density += y_firing_angle.scan_weight * math.exp(-0.5 * ux * ux) / y_firing_angle.distance
            if x_density > best_density:
                best_angle = x_firing_angle.angle
                best_density = x_density

        if not firing_angles or best_angle is None:
            return closest_bot.last_wave_fired.abs_bearing
        return normal_absolute_angle(best_angle)

    def _get_common_k_size(self, enemies_alive: int) -> int:
        k_size = self.MAX_SCANS // max(1, enemies_alive)
        for gun_data in self._gun_data_manager.get_all_enemy_data():
            view = gun_data.views.get(self.VIEW_NAME)
            if gun_data.alive and view is not None and view.size() >= 10 and gun_data.last_wave_fired is not None:
                k_size = min(k_size, view.size() // 10)
        return k_size

    def _get_firing_angle(self, my_next_location: Point, current_time: int, disp_vector: Point, scan_weight: float, aim_wave: Wave):
        projected_location = aim_wave.project_location_blind(my_next_location, disp_vector, current_time)
        if self._battle_field.contains_point(projected_location):
            distance = my_next_location.distance(projected_location)
            return MeleeGun.MeleeFiringAngle(
                absolute_bearing(my_next_location, projected_location), distance, bot_width_aim_angle(distance), scan_weight, aim_wave
            )
        return None

    def new_data_views(self) -> list[KnnView]:
        return [KnnView(MeleeFormula()).visits_on().virtual_waves_on().melee_on().set_name(self.VIEW_NAME)]


# VirtualGunsManager ----------------------------------------------------------------------
class VirtualGunsManager:
    TYPICAL_ANGULAR_BOT_WIDTH = 0.1
    TYPICAL_ESCAPE_RANGE = 0.9

    class GunStats:
        __slots__ = ("shots_fired", "shots_hit", "virtual_bullets")

        def __init__(self) -> None:
            self.shots_fired = 0
            self.shots_hit = 0.0
            self.virtual_bullets: dict[Wave, float] = {}

        def gun_rating(self) -> float:
            return 0.0 if self.shots_fired == 0 else self.shots_hit / self.shots_fired

    def __init__(self) -> None:
        self._guns: list[DuelGun] = []
        self._gun_ratings: dict[DuelGun, dict[object, VirtualGunsManager.GunStats]] = {}

    def add_gun(self, gun: DuelGun) -> None:
        self._guns.append(gun)
        self._gun_ratings[gun] = {}

    def get_guns(self) -> list[DuelGun]:
        return self._guns

    def get_rating(self, gun: DuelGun, bot_name) -> float:
        stats = self._gun_ratings.get(gun, {}).get(bot_name)
        return stats.gun_rating() if stats is not None else 0.0

    def get_formatted_rating(self, gun: DuelGun, bot_name) -> float:
        return round_to(self.get_rating(gun, bot_name) * 100, 2)

    def fire_virtual_bullets(self, w: Wave) -> None:
        for gun in self._guns:
            ratings = self._gun_ratings[gun]
            stats = ratings.get(w.bot_name)
            if stats is None:
                stats = VirtualGunsManager.GunStats()
                ratings[w.bot_name] = stats
            stats.virtual_bullets[w] = gun.aim(w)

    def register_wave_break(self, w: Wave, hit_angle: float, tolerance: float) -> None:
        for gun in self._guns:
            stats = self._gun_ratings[gun].get(w.bot_name)
            if stats is None:
                continue
            firing_angle = stats.virtual_bullets.get(w)
            if firing_angle is None:
                continue
            angular_bot_width = tolerance * 2
            hit_weight = (self.TYPICAL_ANGULAR_BOT_WIDTH / angular_bot_width) * (w.escape_angle_range() / self.TYPICAL_ESCAPE_RANGE)
            ux = abs(normal_relative_angle(firing_angle - hit_angle)) / tolerance
            stats.shots_hit += hit_weight * math.pow(1.6, -ux)
            stats.shots_fired += 1
            del stats.virtual_bullets[w]

    def init_round(self) -> None:
        for gun in self._guns:
            for stats in self._gun_ratings[gun].values():
                stats.virtual_bullets.clear()
            gun.clear_cache()

    def best_gun(self, bot_name) -> DuelGun | None:
        best_gun = None
        best_rating = 0.0
        for gun in self._guns:
            rating = self.get_rating(gun, bot_name)
            if best_gun is None or rating > best_rating:
                best_gun = gun
                best_rating = rating
        return best_gun

    def print_gun_ratings(self, bot_name) -> None:
        print(f"Virtual Gun ratings for {bot_name}:", file=sys.stderr)
        for gun in self._guns:
            stats = self._gun_ratings[gun].get(bot_name)
            if stats is not None:
                print(f"  {gun.get_label()}: {round_to(stats.gun_rating() * 100, 2)}", file=sys.stderr)

    # GunDataListener
    def on_1v1_firing_wave_break(self, w: Wave, hit_angle: float, tolerance: float) -> None:
        self.register_wave_break(w, hit_angle, tolerance)

    def on_mark_firing_wave(self, w: Wave) -> None:
        self.fire_virtual_bullets(w)


# DiamondFist --------------------------------------------------------------------------------
class DiamondFist:
    KNN_DATA_THRESHOLD = 9

    def __init__(self, robot, battle_field: BattleField) -> None:
        self._robot = robot
        self._battle_field = battle_field
        self._predictor = MovementPredictor(battle_field)
        self._enemies_total = robot.others
        self._gun_data_manager = GunDataManager(self._enemies_total, battle_field, self._predictor)
        self._virtual_guns = VirtualGunsManager()
        self._gun_data_manager.add_listener(self._virtual_guns)
        self._aimed_bullet_power = 0.0
        self._fire_listeners: list = []
        self._started_duel = False
        self._perceptual_gun: DuelGun | None = None
        self._current_gun: DuelGun | None = None
        self._melee_gun: MeleeGun | None = None
        self._init_guns()

    def _init_guns(self) -> None:
        if self._enemies_total > 1:
            self._perceptual_gun = None
            main_gun: DuelGun = MainGun(self._gun_data_manager, self._battle_field)
            self._current_gun = main_gun
        else:
            self._perceptual_gun = PerceptualGun()
            self._current_gun = self._perceptual_gun
            main_gun = TripHammerKnnGun(self._gun_data_manager)
        self._virtual_guns.add_gun(main_gun)
        self._virtual_guns.add_gun(AntiSurferGun(self._gun_data_manager, self._battle_field))
        self._melee_gun = MeleeGun(self._gun_data_manager, self._battle_field)

    def _init_gun_views(self, gun_data: GunEnemy) -> None:
        for gun in self._virtual_guns.get_guns():
            gun_data.add_views(gun.new_data_views())
        if self.is_melee():
            gun_data.add_views(self._melee_gun.new_data_views())

    def init_round(self, robot) -> None:
        self._robot = robot
        self._gun_data_manager.init_round()
        self._virtual_guns.init_round()
        self._started_duel = False

    def execute(self) -> None:
        robot = self._robot
        self._gun_data_manager.execute(robot.round_num, robot.time, self.calculate_bullet_power(), robot.gun_heat, self.my_location(), self.is_1v1())
        if self.is_1v1():
            duel_enemy = self._gun_data_manager.duel_enemy()
            if duel_enemy is not None:
                self._aim_and_fire(duel_enemy)
                if not self._started_duel:
                    self._started_duel = True
        else:
            self._aim_and_fire_at_everyone()

    def _aim_and_fire(self, gun_data: GunEnemy) -> None:
        robot = self._robot
        self.fire_if_gun_turned(self._aimed_bullet_power)
        aim_wave = gun_data.last_wave_fired
        if aim_wave is None:
            return
        self._aimed_bullet_power = aim_wave.bullet_power()
        my_next_location = self._predictor.next_location(robot)
        if gun_data.energy == 0 or self._ticks_until_gun_cool() > 3:
            firing_angle = absolute_bearing(my_next_location, aim_wave.target_location)
            self._evaluate_virtual_guns(gun_data)
        else:
            firing_angle = self._current_gun.aim(aim_wave)
        robot.set_turn_gun_right_radians(normal_relative_angle(firing_angle - robot.gun_heading_radians))

    def _aim_and_fire_at_everyone(self) -> None:
        robot = self._robot
        closest_bot = self._gun_data_manager.get_closest_living_bot(self.my_location())
        if closest_bot is None:
            return
        self.fire_if_gun_turned(self._aimed_bullet_power)
        my_next_location = self._predictor.next_location(robot)
        ticks_until_fire = self._ticks_until_gun_cool()
        if ticks_until_fire % 2 == 0 or ticks_until_fire <= 4:
            self._aimed_bullet_power = self.calculate_bullet_power()
            firing_angle = self._melee_gun.aim_at_everyone(my_next_location, robot.time, robot.others, self._aimed_bullet_power, closest_bot)
            robot.set_turn_gun_right_radians(normal_relative_angle(firing_angle - robot.gun_heading_radians))

    def my_location(self) -> Point:
        return Point(self._robot.x, self._robot.y)

    def calculate_bullet_power(self) -> float:
        robot = self._robot
        gun_data = self._gun_data_manager.get_closest_living_bot(self.my_location())
        bullet_power = 3.0
        if gun_data is None:
            return bullet_power
        my_energy = robot.energy
        if self.is_1v1():
            bullet_power = 1.95
            if gun_data.distance < 150 or gun_data.is_rammer():
                bullet_power = 2.95
            if gun_data.distance > 325:
                power_down_point = limit(35.0, 63 + ((gun_data.energy - my_energy) * 4), 63.0)
                if my_energy < power_down_point:
                    bullet_power = min(bullet_power, cube(my_energy / power_down_point) * 1.95)
            bullet_power = min(bullet_power, gun_data.energy / 4)
            bullet_power = max(bullet_power, 0.1)
            bullet_power = min(bullet_power, my_energy)
        else:
            avg_enemy_energy = self._gun_data_manager.get_average_energy()
            bullet_power = 2.999
            enemies_alive = robot.others
            if enemies_alive <= 3:
                bullet_power = 1.999
            if enemies_alive <= 5 and gun_data.distance > 500:
                bullet_power = 1.499
            if (my_energy < avg_enemy_energy and enemies_alive <= 5 and gun_data.distance > 300) or gun_data.distance > 700:
                bullet_power = 0.999
            if my_energy < 20 and my_energy < avg_enemy_energy:
                bullet_power = min(bullet_power, 2 - ((20 - my_energy) / 11))
            bullet_power = max(bullet_power, 0.1)
            bullet_power = min(bullet_power, my_energy)
        return bullet_power

    def _evaluate_virtual_guns(self, gun_data: GunEnemy) -> None:
        data_points = self._gun_data_manager.get_duel_data_size()
        if data_points < self.KNN_DATA_THRESHOLD:
            self._current_gun = self._perceptual_gun
            return
        if self._perceptual_gun is not None:
            self._perceptual_gun = None
        best_gun = self._virtual_guns.best_gun(gun_data.bot_name)
        if self._current_gun is not best_gun:
            self._current_gun = best_gun

    def fire_if_gun_turned(self, bullet_power: float) -> None:
        robot = self._robot
        if robot.gun_heat == 0 and robot.gun_turn_remaining == 0:
            if robot.energy > bullet_power:
                if self._set_fire_bullet_logged(bullet_power):
                    self._gun_data_manager.mark_firing_waves(robot.time, self.is_1v1())

    def on_scanned_robot(self, e: ScannedRobotEvent) -> None:
        robot = self._robot
        bot_name = e.name
        enemy_location = e.location
        abs_bearing = absolute_bearing(self.my_location(), enemy_location)
        if self._gun_data_manager.has_enemy(bot_name):
            self._gun_data_manager.update_enemy(e, enemy_location, abs_bearing, robot.round_num, self.is_1v1())
        else:
            gun_data = self._gun_data_manager.new_enemy(e, enemy_location, abs_bearing, robot.round_num, self.is_1v1())
            self._init_gun_views(gun_data)
        self._gun_data_manager.fire_next_tick_wave(
            self._predictor.next_location(robot),
            enemy_location,
            bot_name,
            robot.round_num,
            robot.time,
            self.calculate_bullet_power(),
            robot.energy,
            robot.gun_heat,
            robot.heading_radians,
            robot.velocity,
            robot.others,
        )

    def on_robot_death(self, bot_name) -> None:
        self._gun_data_manager.on_robot_death(bot_name)

    def round_over(self) -> None:
        duel_enemy = self._gun_data_manager.duel_enemy()
        if self.is_1v1() and duel_enemy is not None and self._robot.verbose:
            self._virtual_guns.print_gun_ratings(duel_enemy.bot_name)

    def on_bullet_hit(self, victim_name, bullet: BulletRecord) -> None:
        self._gun_data_manager.on_bullet_hit(victim_name, bullet, self._robot.time)

    def on_bullet_hit_bullet(self, my_bullet: BulletRecord, hit_bullet: BulletRecord) -> None:
        self._gun_data_manager.on_bullet_hit_bullet(my_bullet, hit_bullet, self._robot.time)

    def _ticks_until_gun_cool(self) -> int:
        return int(math.ceil(self._robot.gun_heat / self._robot.gun_cooling_rate))

    def is_1v1(self) -> bool:
        return self._robot.others <= 1

    def is_melee(self) -> bool:
        return self._robot.others > 1

    def get_enemies_alive(self) -> int:
        return self._robot.others

    def add_fire_listener(self, listener) -> None:
        self._fire_listeners.append(listener)

    def _set_fire_bullet_logged(self, bullet_power: float) -> bool:
        robot = self._robot
        fired = robot.set_fire_bullet(bullet_power)
        if fired:
            for listener in self._fire_listeners:
                listener.bullet_fired(FiredBullet(robot.time, self.my_location(), robot.gun_heading_radians, 20 - (3 * bullet_power)))
        return fired

    @property
    def current_gun_label(self) -> str:
        return self._current_gun.get_label() if self._current_gun is not None else "none"

    @property
    def gun_data_manager(self) -> GunDataManager:
        return self._gun_data_manager

    @property
    def virtual_guns(self) -> VirtualGunsManager:
        return self._virtual_guns

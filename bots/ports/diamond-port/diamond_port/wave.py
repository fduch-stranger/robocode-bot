"""``voidious.utils.Wave`` and ``WaveManager``: the wave record shared by the
gun (my bullets) and the movement (enemy bullets), bullet shadows, precise
intersections and the wave-position states."""
from __future__ import annotations

import math

from diamond_port.dia_utils import (
    BattleField,
    Circle,
    Interpolator,
    LineSeg,
    Point,
    RobotState,
    RobotStateLog,
    absolute_bearing,
    distance_point_to_bot_state,
    get_bullet_speed,
    non_zero_sign,
    normal_absolute_angle,
    normal_relative_angle,
    normalize_angle,
    project,
    project_sin_cos,
    square,
)
from diamond_port.movement_predictor import MovementPredictor

PRECISE_MEA_WALL_STICK = 120.0
ORIGIN = Point(0.0, 0.0)
MAX_BOT_RADIUS = 18 / math.cos(math.pi / 4)
CLOCKWISE = 1
COUNTERCLOCKWISE = -1
FIRING_WAVE = True
SURFABLE_WAVE = True
ANY_WAVE = False
POSITIVE_GUESSFACTOR = True
NEGATIVE_GUESSFACTOR = False
ANY_BULLET_POWER = -1.0
FIRST_WAVE = 0

# WavePosition
MIDAIR = 0
BREAKING_FRONT = 1
BREAKING_CENTER = 2
GONE = 3


def is_breaking(wave_position: int) -> bool:
    return wave_position == BREAKING_FRONT or wave_position == BREAKING_CENTER


# WallDistanceStyle
ORBITAL = 0
DIRECT = 1
PRECISE_MEA = 2


class Intersection:
    __slots__ = ("angle", "bandwidth")

    def __init__(self, angle: float, bandwidth: float) -> None:
        self.angle = angle
        self.bandwidth = bandwidth


class BulletShadow:
    __slots__ = ("min_angle", "max_angle")

    def __init__(self, min_angle: float, max_angle: float) -> None:
        self.min_angle = min_angle
        self.max_angle = max_angle

    def overlaps(self, that: "BulletShadow") -> bool:
        that_min_angle = normalize_angle(that.min_angle, self.min_angle)
        that_max_angle = normalize_angle(that.max_angle, that_min_angle)
        return (
            self._overlaps_angle(that.min_angle)
            or self._overlaps_angle(that.max_angle)
            or (that_min_angle <= self.min_angle and that_max_angle >= self.max_angle)
        )

    def _overlaps_angle(self, angle: float) -> bool:
        angle = normalize_angle(angle, self.min_angle)
        return self.min_angle <= angle <= self.max_angle


class Wave:
    __slots__ = (
        "bot_name",
        "source_location",
        "target_location",
        "abs_bearing",
        "fire_round",
        "fire_time",
        "_bullet_power",
        "_bullet_speed",
        "_max_escape_angle",
        "orbit_direction",
        "target_heading",
        "target_relative_heading",
        "target_velocity",
        "battle_field",
        "predictor",
        "hit_by_bullet",
        "bullet_hit_bullet",
        "firing_wave",
        "alt_wave",
        "target_accel",
        "target_velocity_sign",
        "target_distance",
        "target_distance_to_nearest_bot",
        "target_dchange_time",
        "target_vchange_time",
        "target_wall_distance",
        "target_rev_wall_distance",
        "target_dl8t",
        "target_dl20t",
        "target_dl40t",
        "target_energy",
        "source_energy",
        "gun_heat",
        "enemies_alive",
        "last_bullet_fired_time",
        "shadows",
        "_cached_positive_escape_angle",
        "_cached_negative_escape_angle",
        "used_negative_smoothing_mea",
        "used_positive_smoothing_mea",
    )

    def __init__(
        self,
        bot_name,
        source_location: Point,
        target_location: Point,
        fire_round: int,
        fire_time: int,
        bullet_power: float,
        target_heading: float,
        target_velocity: float,
        target_velocity_sign: int,
        battle_field: BattleField,
        predictor: MovementPredictor,
    ) -> None:
        self.bot_name = bot_name
        self.source_location = source_location
        self.target_location = target_location
        self.fire_round = fire_round
        self.fire_time = fire_time
        self._cached_positive_escape_angle: float | None = None
        self._cached_negative_escape_angle: float | None = None
        self.set_bullet_power(bullet_power)
        self.target_heading = target_heading
        self.target_velocity = target_velocity
        self.target_velocity_sign = target_velocity_sign
        self.battle_field = battle_field
        self.predictor = predictor
        self.abs_bearing = absolute_bearing(source_location, target_location)

        relative_heading = normal_relative_angle(self.effective_heading() - absolute_bearing(source_location, target_location))
        self.orbit_direction = COUNTERCLOCKWISE if relative_heading < 0 else CLOCKWISE
        self.target_relative_heading = abs(relative_heading)

        self.hit_by_bullet = False
        self.bullet_hit_bullet = False
        self.firing_wave = False
        self.alt_wave = False
        self.shadows: list[BulletShadow] = []

        self.target_accel = 0.0
        self.target_distance = 0.0
        self.target_distance_to_nearest_bot = 0.0
        self.target_dchange_time = 0
        self.target_vchange_time = 0
        self.target_wall_distance = 0.0
        self.target_rev_wall_distance = 0.0
        self.target_dl8t = 0.0
        self.target_dl20t = 0.0
        self.target_dl40t = 0.0
        self.target_energy = 0.0
        self.source_energy = 0.0
        self.gun_heat = 0.0
        self.enemies_alive = 0
        self.last_bullet_fired_time = 0
        self.used_negative_smoothing_mea = False
        self.used_positive_smoothing_mea = False

    # Fluent setters ---------------------------------------------------------------
    def set_abs_bearing(self, abs_bearing: float) -> "Wave":
        self.abs_bearing = abs_bearing
        return self

    def set_bullet_power(self, power: float) -> "Wave":
        self._bullet_power = power
        self._bullet_speed = 20 - (3 * power)
        self._max_escape_angle = math.asin(8.0 / self._bullet_speed)
        self.clear_cached_precise_escape_angles()
        return self

    def set_accel(self, accel: float) -> "Wave":
        self.target_accel = accel
        return self

    def set_distance(self, distance: float) -> "Wave":
        self.target_distance = distance
        return self

    def set_distance_to_nearest_bot(self, distance: float) -> "Wave":
        self.target_distance_to_nearest_bot = distance
        return self

    def set_dchange_time(self, dchange_time: int) -> "Wave":
        self.target_dchange_time = dchange_time
        return self

    def set_vchange_time(self, vchange_time: int) -> "Wave":
        self.target_vchange_time = vchange_time
        return self

    def set_distance_last_8_ticks(self, dl8t: float) -> "Wave":
        self.target_dl8t = dl8t
        return self

    def set_distance_last_20_ticks(self, dl20t: float) -> "Wave":
        self.target_dl20t = dl20t
        return self

    def set_distance_last_40_ticks(self, dl40t: float) -> "Wave":
        self.target_dl40t = dl40t
        return self

    def set_target_energy(self, energy: float) -> "Wave":
        self.target_energy = energy
        return self

    def set_source_energy(self, energy: float) -> "Wave":
        self.source_energy = energy
        return self

    def set_gun_heat(self, gun_heat: float) -> "Wave":
        self.gun_heat = gun_heat
        return self

    def set_enemies_alive(self, enemies_alive: int) -> "Wave":
        self.enemies_alive = enemies_alive
        return self

    def set_last_bullet_fired_time(self, last_bullet_fired_time: int) -> "Wave":
        self.last_bullet_fired_time = last_bullet_fired_time
        return self

    def set_alt_wave(self, alt_wave: bool) -> "Wave":
        self.alt_wave = alt_wave
        return self

    def _set_firing_wave(self, firing_wave: bool) -> "Wave":
        self.firing_wave = firing_wave
        return self

    def _set_hit_by_bullet(self, hit_by_bullet: bool) -> "Wave":
        self.hit_by_bullet = hit_by_bullet
        return self

    def _set_bullet_hit_bullet(self, bullet_hit_bullet: bool) -> "Wave":
        self.bullet_hit_bullet = bullet_hit_bullet
        return self

    # Accessors ------------------------------------------------------------------
    def bullet_power(self) -> float:
        return self._bullet_power

    def bullet_speed(self) -> float:
        return self._bullet_speed

    def max_escape_angle(self) -> float:
        return self._max_escape_angle

    def effective_heading(self) -> float:
        return normal_absolute_angle(self.target_heading + (0.0 if self.target_velocity_sign == 1 else math.pi))

    def distance_traveled(self, current_time: int) -> float:
        return (current_time - self.fire_time) * self._bullet_speed

    def lateral_velocity(self) -> float:
        return math.sin(self.target_relative_heading) * (self.target_velocity_sign * self.target_velocity)

    def processed_bullet_hit(self) -> bool:
        return self.hit_by_bullet or self.bullet_hit_bullet

    def set_wall_distances(self, style: int) -> None:
        if style == ORBITAL:
            self.target_wall_distance = self._orbital_wall_distance(self.orbit_direction)
            self.target_rev_wall_distance = self._orbital_wall_distance(-self.orbit_direction)
        elif style == DIRECT:
            self.target_wall_distance = self._direct_to_wall_distance(True)
            self.target_rev_wall_distance = self._direct_to_wall_distance(False)
        elif style == PRECISE_MEA:
            self.target_wall_distance = self.precise_escape_angle(POSITIVE_GUESSFACTOR) / self._max_escape_angle
            self.target_rev_wall_distance = self.precise_escape_angle(NEGATIVE_GUESSFACTOR) / self._max_escape_angle

    def _orbital_wall_distance(self, orientation: int) -> float:
        return min(
            1.5,
            self.battle_field.orbital_wall_distance(self.source_location, self.target_location, self.bullet_power(), orientation),
        )

    def _direct_to_wall_distance(self, forward: bool) -> float:
        return min(
            1.5,
            self.battle_field.direct_to_wall_distance(
                self.target_location,
                self.source_location.distance(self.target_location),
                self.effective_heading() + (0.0 if forward else math.pi),
                self.bullet_power(),
            ),
        )

    def virtuality(self) -> float:
        time_since_last_bullet = self.fire_time - self.last_bullet_fired_time
        time_to_next_bullet = int(math.ceil(self.gun_heat * 10))
        if self.firing_wave:
            return 0.0
        if self.last_bullet_fired_time > 0:
            return min(time_since_last_bullet, time_to_next_bullet) / 8.0
        return min(1.0, time_to_next_bullet / 8.0)

    def firing_angle(self, guess_factor: float) -> float:
        return self.abs_bearing + (guess_factor * self.orbit_direction * self._max_escape_angle)

    def firing_angle_from_target_location(self, firing_target: Point) -> float:
        return normal_absolute_angle(absolute_bearing(self.source_location, firing_target))

    def displacement_vector_of_state(self, wave_break_state: RobotState) -> Point:
        return self.displacement_vector(wave_break_state.location, wave_break_state.time)

    def displacement_vector(self, bot_location: Point, time: int) -> Point:
        vector_bearing = normal_relative_angle(absolute_bearing(self.target_location, bot_location) - self.effective_heading())
        vector_distance = self.target_location.distance(bot_location) / (time - self.fire_time)
        return project(ORIGIN, vector_bearing * self.orbit_direction, vector_distance)

    def project_location_from_displacement_vector(self, disp_vector: Point) -> Point:
        return self._project_location(self.source_location, disp_vector, 0)

    def project_location_blind(self, my_next_location: Point, disp_vector: Point, current_time: int) -> Point:
        return self._project_location(my_next_location, disp_vector, current_time - self.fire_time + 1)

    def _project_location(self, firing_location: Point, disp_vector: Point, extra_ticks: int) -> Point:
        disp_angle = self.effective_heading() + (absolute_bearing(ORIGIN, disp_vector) * self.orbit_direction)
        disp_distance = ORIGIN.distance(disp_vector)
        projected_location = self.target_location
        bullet_ticks = -1
        prev_bullet_ticks = -1
        da_sin = math.sin(disp_angle)
        da_cos = math.cos(disp_angle)
        bullet_speed = self._bullet_speed
        while True:
            prev_prev_bullet_ticks = prev_bullet_ticks
            prev_bullet_ticks = bullet_ticks
            bullet_ticks = int(math.ceil(firing_location.distance(projected_location) / bullet_speed)) - 1
            projected_location = project_sin_cos(self.target_location, da_sin, da_cos, (bullet_ticks + extra_ticks) * disp_distance)
            if bullet_ticks == prev_bullet_ticks or bullet_ticks == prev_prev_bullet_ticks:
                break
        return projected_location

    def guess_factor_of_location(self, target_location: Point) -> float:
        return self.guess_factor(absolute_bearing(self.source_location, target_location))

    def guess_factor(self, bearing_to_target: float) -> float:
        return self.guess_angle(bearing_to_target) / self._max_escape_angle

    def guess_angle(self, bearing_to_target: float) -> float:
        return self.orbit_direction * normal_relative_angle(bearing_to_target - self.abs_bearing)

    def guess_factor_precise_of_location(self, target_location: Point) -> float:
        return self.guess_factor_precise(absolute_bearing(self.source_location, target_location))

    def guess_factor_precise(self, new_bearing_to_target: float) -> float:
        guess_angle = self.orbit_direction * normal_relative_angle(new_bearing_to_target - self.abs_bearing)
        max_escape_angle = self.precise_escape_angle(guess_angle >= 0)
        return guess_angle / max_escape_angle

    def precise_escape_angle(self, guess_factor_sign: bool) -> float:
        if guess_factor_sign:
            if self._cached_positive_escape_angle is None:
                self._cached_positive_escape_angle = self.calculate_precise_escape_angle(True).angle
            return self._cached_positive_escape_angle
        if self._cached_negative_escape_angle is None:
            self._cached_negative_escape_angle = self.calculate_precise_escape_angle(False).angle
        return self._cached_negative_escape_angle

    def escape_angle_range(self) -> float:
        return self.precise_escape_angle(POSITIVE_GUESSFACTOR) + self.precise_escape_angle(NEGATIVE_GUESSFACTOR)

    def calculate_precise_escape_angle(self, positive_guess_factor: bool):
        start_state = RobotState(self.target_location.clone(), self.target_heading, self.target_velocity, self.fire_time)
        return self.predictor.precise_escape_angle(
            self.orbit_direction * (1 if positive_guess_factor else -1),
            self.source_location,
            self.fire_time,
            self._bullet_speed,
            start_state,
            0.0,
            PRECISE_MEA_WALL_STICK,
        )

    def clear_cached_precise_escape_angles(self) -> None:
        self._cached_positive_escape_angle = None
        self._cached_negative_escape_angle = None

    # Bullet shadows ---------------------------------------------------------------
    def shadowed(self, firing_angle: float) -> bool:
        for shadow in self.shadows:
            firing_angle = normalize_angle(firing_angle, shadow.min_angle)
            if shadow.min_angle <= firing_angle <= shadow.max_angle:
                return True
        return False

    def cast_shadow(self, p1: Point, p2: Point) -> None:
        self._cast_shadow(absolute_bearing(self.source_location, p1), absolute_bearing(self.source_location, p2))

    def _cast_shadow(self, shadow_angle1: float, shadow_angle2: float) -> None:
        shadow_angle1 = normalize_angle(shadow_angle1, self.abs_bearing)
        shadow_angle2 = normalize_angle(shadow_angle2, shadow_angle1)
        self.shadows.append(BulletShadow(min(shadow_angle1, shadow_angle2), max(shadow_angle1, shadow_angle2)))

        dead_shadows: list[BulletShadow] = []
        for shadow1 in self.shadows:
            if shadow1 in dead_shadows:
                continue
            for shadow2 in self.shadows:
                if shadow1 is not shadow2 and shadow2 not in dead_shadows and shadow1.overlaps(shadow2):
                    shadow1.min_angle = min(shadow1.min_angle, normalize_angle(shadow2.min_angle, shadow1.min_angle))
                    shadow1.max_angle = max(shadow1.max_angle, normalize_angle(shadow2.max_angle, shadow1.max_angle))
                    dead_shadows.append(shadow2)
        for dead_shadow in dead_shadows:
            self.shadows.remove(dead_shadow)

    def shadow_factor(self, intersection: Intersection) -> float:
        min_angle = intersection.angle - intersection.bandwidth
        max_angle = intersection.angle + intersection.bandwidth
        factor = 1.0
        for shadow in self.shadows:
            shadow_min = normalize_angle(shadow.min_angle, min_angle)
            shadow_max = normalize_angle(shadow.max_angle, shadow_min)
            if shadow_min <= min_angle and shadow_max >= max_angle:
                return 0.0
            if min_angle <= shadow_min <= max_angle:
                factor -= (min(max_angle, shadow_max) - shadow_min) / (max_angle - min_angle)
            elif min_angle <= shadow_max <= max_angle:
                factor -= (shadow_max - max(min_angle, shadow_min)) / (max_angle - min_angle)
        return factor

    # Intersections and positions ----------------------------------------------------
    def precise_intersection(self, wave_break_states: list[RobotState]) -> Intersection | None:
        if not wave_break_states:
            return None
        source = self.source_location
        bullet_speed = self._bullet_speed
        aim_angles: list[float] = []
        for state in wave_break_states:
            wave_start = Circle(source.x, source.y, bullet_speed * (state.time - self.fire_time))
            wave_end = Circle(source.x, source.y, bullet_speed * (state.time - self.fire_time + 1))
            for corner in state.bot_corners():
                if wave_end.contains(corner) and not wave_start.contains(corner):
                    aim_angles.append(absolute_bearing(source, corner))
            for x1, y1, x2, y2 in state.bot_sides():
                seg = LineSeg(x1, y1, x2, y2)
                for intersect in wave_start.intersects(seg):
                    if intersect is not None:
                        aim_angles.append(absolute_bearing(source, intersect))
                for intersect in wave_end.intersects(seg):
                    if intersect is not None:
                        aim_angles.append(absolute_bearing(source, intersect))
        if not aim_angles:
            # Java would throw here; the break states always intersect the wave
            # in practice, so treat the odd numerical miss as "no intersection".
            return None
        reference = aim_angles[0]
        min_angle = reference
        max_angle = reference
        for angle in aim_angles:
            angle = normalize_angle(angle, reference)
            if angle > max_angle:
                max_angle = angle
            if angle < min_angle:
                min_angle = angle
        center_angle = (max_angle + min_angle) / 2
        return Intersection(center_angle, max_angle - center_angle)

    def check_wave_position(self, current_state: RobotState, skip_midair: bool = False, max_position: int | None = None) -> int:
        location = current_state.location
        source = self.source_location
        enemy_dist_sq = source.distance_sq(location)
        end_bullet_distance = self.distance_traveled(current_state.time + 1)
        if not skip_midair and (
            max_position == MIDAIR
            or enemy_dist_sq > square(end_bullet_distance + MAX_BOT_RADIUS)
            or distance_point_to_bot_state(source, current_state) > end_bullet_distance
        ):
            return MIDAIR
        if max_position == BREAKING_FRONT or enemy_dist_sq > square(end_bullet_distance):
            return BREAKING_FRONT
        if max_position == BREAKING_CENTER:
            return BREAKING_CENTER
        start_bullet_distance_sq = square(self.distance_traveled(current_state.time))
        for corner in current_state.bot_corners():
            if corner.distance_sq(source) > start_bullet_distance_sq:
                return BREAKING_CENTER
        return GONE

    def clone(self) -> "Wave":
        wave = Wave(
            self.bot_name,
            self.source_location,
            self.target_location,
            self.fire_round,
            self.fire_time,
            self.bullet_power(),
            self.target_heading,
            self.target_velocity,
            self.target_velocity_sign,
            self.battle_field,
            self.predictor,
        )
        wave.set_abs_bearing(self.abs_bearing)
        wave.set_accel(self.target_accel)
        wave.set_distance(self.target_distance)
        wave.set_dchange_time(self.target_dchange_time)
        wave.set_vchange_time(self.target_vchange_time)
        wave.set_distance_last_8_ticks(self.target_dl8t)
        wave.set_distance_last_20_ticks(self.target_dl20t)
        wave.set_distance_last_40_ticks(self.target_dl40t)
        wave.set_target_energy(self.target_energy)
        wave.set_source_energy(self.source_energy)
        wave.set_alt_wave(self.alt_wave)
        wave._set_firing_wave(self.firing_wave)
        wave._set_hit_by_bullet(self.hit_by_bullet)
        wave._set_bullet_hit_bullet(self.bullet_hit_bullet)
        wave.set_enemies_alive(self.enemies_alive)
        wave.set_last_bullet_fired_time(self.last_bullet_fired_time)
        return wave


class WaveManager:
    WAVE_MATCH_THRESHOLD = 50.0
    COOLING_RATE = 0.1
    MAX_GUN_HEAT = 1.6

    def __init__(self) -> None:
        self._waves: list[Wave] = []
        self._state_logs: dict[Wave, RobotStateLog] = {}

    def init_round(self) -> None:
        self._waves.clear()
        self._state_logs.clear()

    def add_wave(self, wave: Wave) -> None:
        self._waves.append(wave)

    def current_waves(self, current_time: int) -> list[Wave]:
        return [w for w in self._waves if w.fire_time == current_time]

    def all_waves(self) -> list[Wave]:
        return list(self._waves)

    def check_active_waves(self, current_time: int, last_scan_state: RobotState, on_wave_break) -> None:
        if last_scan_state.time != current_time:
            return
        for wave in list(self._waves):
            self._add_robot_state(wave, last_scan_state)
            if wave.check_wave_position(last_scan_state) == GONE:
                wave_break_states = self._get_wave_break_states(wave, current_time)
                on_wave_break(wave, wave_break_states)
                self._waves.remove(wave)

    def _add_robot_state(self, wave: Wave, state: RobotState) -> None:
        state_log = self._state_logs.get(wave)
        if state_log is None:
            state_log = RobotStateLog()
            self._state_logs[wave] = state_log
        state_log.add_state(state)

    def _get_wave_break_states(self, wave: Wave, current_time: int) -> list[RobotState]:
        wave_break_states: list[RobotState] = []
        log = self._state_logs.get(wave)
        if log is not None:
            for time in range(wave.fire_time, current_time):
                state = log.get_state(time)
                if state is not None and is_breaking(wave.check_wave_position(state)):
                    wave_break_states.append(state)
        return wave_break_states

    def find_closest_wave(self, target_location: Point, current_time: int, only_firing: bool, bot_name, bullet_power: float) -> Wave | None:
        closest_distance = math.inf
        closest_wave = None
        for wave in self._waves:
            if (
                not wave.alt_wave
                and (not only_firing or wave.firing_wave)
                and (bullet_power == ANY_BULLET_POWER or abs(bullet_power - wave.bullet_power()) < 0.001)
                and (bot_name is None or bot_name == wave.bot_name or bot_name == "")
            ):
                target_distance_sq = wave.source_location.distance_sq(target_location)
                wave_distance_traveled = wave.distance_traveled(current_time)
                if target_distance_sq < square(wave_distance_traveled + self.WAVE_MATCH_THRESHOLD) and target_distance_sq > square(
                    max(0.0, wave_distance_traveled - self.WAVE_MATCH_THRESHOLD)
                ):
                    distance_from_target_to_wave = math.sqrt(target_distance_sq) - wave_distance_traveled
                    if abs(distance_from_target_to_wave) < closest_distance:
                        closest_distance = abs(distance_from_target_to_wave)
                        closest_wave = wave
        return closest_wave

    def find_surfable_wave(self, surf_index: int, target_state: RobotState, unsurfable_position: int) -> Wave | None:
        search_wave_index = 0
        for wave in self._waves:
            if wave.firing_wave and not wave.processed_bullet_hit():
                wave_position = wave.check_wave_position(target_state, False, unsurfable_position)
                if wave_position < unsurfable_position:
                    if search_wave_index == surf_index:
                        return wave
                    search_wave_index += 1
        return None

    def get_past_wave(self, x: int) -> Wave:
        return self._waves[len(self._waves) - 1 - x]

    def get_wave_by_fire_time(self, fire_time: int) -> Wave | None:
        for wave in self._waves:
            if wave.fire_time == fire_time:
                return wave
        return None

    def interpolate_wave_by_fire_time(
        self,
        fire_time: int,
        current_time: int,
        source_heading: float,
        source_velocity: float,
        state_log: RobotStateLog,
        battle_field: BattleField,
        predictor: MovementPredictor,
    ) -> Wave | None:
        before_wave = None
        after_wave = None
        for wave in self._waves:
            if wave.alt_wave:
                continue
            if wave.fire_time < fire_time and (before_wave is None or wave.fire_time > before_wave.fire_time):
                before_wave = wave
            if wave.fire_time > fire_time and (after_wave is None or wave.fire_time < after_wave.fire_time):
                after_wave = wave
        if before_wave is None and after_wave is None:
            return None
        if before_wave is None:
            return self._interpolate_wave_offset(after_wave, fire_time - after_wave.fire_time, source_heading, source_velocity, battle_field)
        if after_wave is None:
            return self._interpolate_wave_offset(before_wave, fire_time - before_wave.fire_time, source_heading, source_velocity, battle_field)
        return self._interpolate_wave(before_wave, after_wave, fire_time, state_log, battle_field, predictor)

    def _interpolate_wave(
        self, base_wave1: Wave, base_wave2: Wave, fire_time: int, state_log: RobotStateLog, battle_field: BattleField, predictor: MovementPredictor
    ) -> Wave:
        interpolator = Interpolator(fire_time, base_wave1.fire_time, base_wave2.fire_time)
        source_location = interpolator.get_location(base_wave1.source_location, base_wave2.source_location)
        target_location = interpolator.get_location(base_wave1.target_location, base_wave2.target_location)
        bullet_power = interpolator.avg(base_wave1.bullet_power(), base_wave2.bullet_power())
        target_heading = interpolator.get_heading(base_wave1.target_heading, base_wave2.target_heading)
        target_velocity = interpolator.avg(base_wave1.target_velocity, base_wave2.target_velocity)
        if non_zero_sign(target_velocity) == non_zero_sign(base_wave1.target_velocity):
            target_velocity_sign = base_wave1.target_velocity_sign
        else:
            target_velocity_sign = base_wave2.target_velocity_sign
        target_accel = interpolator.avg(base_wave1.target_accel, base_wave2.target_accel)
        target_dchange_time = interpolator.get_timer(base_wave1.target_dchange_time, base_wave2.target_dchange_time)
        target_vchange_time = interpolator.get_timer(base_wave1.target_vchange_time, base_wave2.target_vchange_time)
        target_dl8t = state_log.get_displacement_distance(target_location, fire_time, 8)
        target_dl20t = state_log.get_displacement_distance(target_location, fire_time, 20)
        target_dl40t = state_log.get_displacement_distance(target_location, fire_time, 40)
        target_energy = interpolator.avg(base_wave1.target_energy, base_wave2.target_energy)
        source_energy = interpolator.avg(base_wave1.source_energy, base_wave2.source_energy)

        last_bullet_fired_time = base_wave1.last_bullet_fired_time
        gun_heat = base_wave1.gun_heat - ((fire_time - base_wave1.fire_time) * self.COOLING_RATE)
        if gun_heat <= 0:
            last_bullet_fired_time = base_wave1.fire_time + int(math.ceil(base_wave1.gun_heat / self.COOLING_RATE))
            gun_heat = math.fmod(base_wave2.gun_heat + ((base_wave2.fire_time - fire_time) * self.COOLING_RATE), self.MAX_GUN_HEAT)

        wave = Wave(
            base_wave1.bot_name,
            source_location,
            target_location,
            base_wave1.fire_round,
            fire_time,
            bullet_power,
            target_heading,
            target_velocity,
            target_velocity_sign,
            battle_field,
            predictor,
        )
        wave.set_abs_bearing(absolute_bearing(source_location, target_location))
        wave.set_accel(target_accel)
        wave.set_distance(source_location.distance(target_location))
        wave.set_dchange_time(target_dchange_time)
        wave.set_vchange_time(target_vchange_time)
        wave.set_distance_last_8_ticks(target_dl8t)
        wave.set_distance_last_20_ticks(target_dl20t)
        wave.set_distance_last_40_ticks(target_dl40t)
        wave.set_target_energy(target_energy)
        wave.set_source_energy(source_energy)
        wave.set_gun_heat(gun_heat)
        wave.set_enemies_alive(base_wave2.enemies_alive)
        wave.set_last_bullet_fired_time(last_bullet_fired_time)
        return wave

    @staticmethod
    def _interpolate_wave_offset(base_wave: Wave, time_offset: int, source_heading: float, source_velocity: float, battle_field: BattleField) -> Wave:
        wave = base_wave.clone()
        wave.source_location = battle_field.translate_to_field(project(base_wave.source_location, source_heading, source_velocity * time_offset))
        wave.target_location = battle_field.translate_to_field(
            project(base_wave.target_location, base_wave.target_heading, base_wave.target_velocity * time_offset)
        )
        wave.abs_bearing = absolute_bearing(wave.source_location, wave.target_location)
        wave.fire_time = wave.fire_time + time_offset
        wave.target_distance = wave.source_location.distance(wave.target_location)
        return wave

    def get_last_fire_time(self) -> int:
        last_fire_time = -1
        for wave in self._waves:
            if not wave.alt_wave and wave.fire_time > last_fire_time:
                last_fire_time = wave.fire_time
        return last_fire_time

    def size(self) -> int:
        return len(self._waves)


__all__ = [
    "ANY_BULLET_POWER",
    "ANY_WAVE",
    "BREAKING_CENTER",
    "BREAKING_FRONT",
    "BulletShadow",
    "CLOCKWISE",
    "COUNTERCLOCKWISE",
    "DIRECT",
    "FIRING_WAVE",
    "FIRST_WAVE",
    "GONE",
    "Intersection",
    "MAX_BOT_RADIUS",
    "MIDAIR",
    "NEGATIVE_GUESSFACTOR",
    "ORBITAL",
    "ORIGIN",
    "POSITIVE_GUESSFACTOR",
    "PRECISE_MEA",
    "PRECISE_MEA_WALL_STICK",
    "SURFABLE_WAVE",
    "Wave",
    "WaveManager",
    "get_bullet_speed",
    "is_breaking",
]

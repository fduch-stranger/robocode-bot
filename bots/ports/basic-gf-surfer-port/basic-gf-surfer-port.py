from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


_DIRECT_BOOTSTRAP_REEXEC_ENV = "ROBOCODE_BASIC_GF_SURFER_PORT_REEXECED"
_MIN_DIRECT_PYTHON_VERSION = (3, 10)


def _bootstrap_direct_gui_launch() -> None:
    bot_dir = Path(__file__).resolve().parent
    for candidate in (bot_dir, *bot_dir.parents):
        if (candidate / "bots" / "bot_core").is_dir():
            _reexec_venv_python_if_needed(candidate)
            _add_import_path(candidate / "bots")
            _add_venv_site_packages(candidate)
            return
        if (candidate / "bot_core").is_dir():
            _reexec_venv_python_if_needed(candidate.parent)
            _add_import_path(candidate)
            _add_venv_site_packages(candidate)
            _add_venv_site_packages(candidate.parent)
            return


def _add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def _add_venv_site_packages(root: Path) -> None:
    venv = root / ".venv"
    if not venv.is_dir():
        return
    site_packages_root = venv / "lib"
    if not site_packages_root.is_dir():
        return
    current = site_packages_root / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if current.is_dir():
        _add_import_path(current)
    for site_packages in site_packages_root.glob("python*/site-packages"):
        if site_packages.is_dir():
            _add_import_path(site_packages)


def _reexec_venv_python_if_needed(root: Path) -> None:
    venv_python = root / ".venv" / "bin" / "python"
    if not _should_reexec_venv_python(venv_python):
        return

    env = os.environ.copy()
    env[_DIRECT_BOOTSTRAP_REEXEC_ENV] = "1"
    os.execve(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)


def _should_reexec_venv_python(
    venv_python: Path,
    *,
    executable: str | None = None,
    version_info: tuple[int, int] | None = None,
) -> bool:
    if os.environ.get(_DIRECT_BOOTSTRAP_REEXEC_ENV):
        return False
    version = version_info or sys.version_info[:2]
    if version >= _MIN_DIRECT_PYTHON_VERSION:
        return False
    if not venv_python.is_file():
        return False

    current_executable = Path(executable or sys.executable)
    try:
        return current_executable.resolve() != venv_python.resolve()
    except OSError:
        return True


_bootstrap_direct_gui_launch()

from robocode_tank_royale.bot_api import Bot, BotInfo, Color
from robocode_tank_royale.bot_api.events import (
    GameStartedEvent,
    HitByBulletEvent,
    HitWallEvent,
    RoundEndedEvent,
    RoundStartedEvent,
    ScannedBotEvent,
)


BINS = 47
GUN_BINS = 25
GUN_MIDDLE_BIN = (GUN_BINS - 1) // 2
BULLET_POWER = 1.9
WALL_MARGIN = 18.0
WALL_STICK = 160.0
WALL_SMOOTHING_MAX_ITERATIONS = 160
WALL_ESCAPE_MARGIN = 90.0
WALL_STUCK_DISTANCE = 0.25
WALL_ESCAPE_TICKS = 12
RADAR_LOCK_GRACE_TICKS = 2
MAX_DISTANCE = 900.0
DISTANCE_INDEXES = 5
VELOCITY_INDEXES = 5
MAX_ESCAPE_ANGLE = 0.7
GUN_BIN_WIDTH = MAX_ESCAPE_ANGLE / GUN_MIDDLE_BIN


@dataclass
class Point:
    x: float
    y: float


@dataclass
class EnemyWave:
    fire_location: Point
    fire_time: int
    bullet_velocity: float
    direct_angle: float
    distance_traveled: float
    direction: int


@dataclass
class GunWave:
    gun_location: Point
    target_location: Point
    bullet_power: float
    bearing: float
    lateral_direction: int
    buffer: list[int]
    distance_traveled: float = 0.0


def limit(minimum: float, value: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def normal_relative_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def normal_relative_degrees(angle: float) -> float:
    return ((angle + 180.0) % 360.0) - 180.0


def java_radians_to_tank_degrees(angle: float) -> float:
    return (90.0 - math.degrees(angle)) % 360.0


def tank_degrees_to_java_radians(angle: float) -> float:
    return math.radians(90.0 - angle)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def project(source: Point, angle: float, length: float) -> Point:
    return Point(source.x + math.sin(angle) * length, source.y + math.cos(angle) * length)


def absolute_bearing(source: Point, target: Point) -> float:
    return math.atan2(target.x - source.x, target.y - source.y)


def bullet_velocity(power: float) -> float:
    return 20.0 - 3.0 * power


def max_escape_angle(velocity: float) -> float:
    return math.asin(8.0 / velocity)


def sign(value: float) -> int:
    return -1 if value < 0 else 1


def factor_index(wave: EnemyWave, target_location: Point) -> int:
    offset_angle = absolute_bearing(wave.fire_location, target_location) - wave.direct_angle
    factor = normal_relative_angle(offset_angle) / max_escape_angle(wave.bullet_velocity) * wave.direction
    return int(limit(0, factor * ((BINS - 1) / 2.0) + ((BINS - 1) / 2.0), BINS - 1))


def gun_segment_index(distance_to_target: float, velocity: float, last_velocity: float) -> tuple[int, int, int]:
    distance_index = min(DISTANCE_INDEXES - 1, int(distance_to_target / (MAX_DISTANCE / DISTANCE_INDEXES)))
    velocity_index = min(VELOCITY_INDEXES - 1, int(abs(velocity / 2.0)))
    last_velocity_index = min(VELOCITY_INDEXES - 1, int(abs(last_velocity / 2.0)))
    return distance_index, velocity_index, last_velocity_index


def own_lateral_velocity(speed: float, heading: float, absolute_bearing_to_enemy: float) -> float:
    return speed * math.sin(normal_relative_angle(absolute_bearing_to_enemy - heading))


def new_gun_stats() -> list[list[list[list[int]]]]:
    return [
        [
            [[0 for _ in range(GUN_BINS)] for _ in range(VELOCITY_INDEXES)]
            for _ in range(VELOCITY_INDEXES)
        ]
        for _ in range(DISTANCE_INDEXES)
    ]


@dataclass
class BasicGFSurferState:
    surf_stats: list[float] = field(default_factory=lambda: [0.0 for _ in range(BINS)])
    gun_stats: list[list[list[list[int]]]] = field(default_factory=new_gun_stats)


class BasicGFSurferPort(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="BasicGFSurfer Port",
                version="1.0",
                authors=["robocode-bot"],
                description="Python Tank Royale port of the fixed BasicGFSurfer reference opponent.",
                game_types={"classic", "1v1"},
                programming_lang="Python 3",
            )
        )
        self._state = BasicGFSurferState()
        self._enemy_waves: list[EnemyWave] = []
        self._gun_waves: list[GunWave] = []
        self._surf_directions: list[int] = []
        self._surf_abs_bearings: list[float] = []
        self._enemy_location: Point | None = None
        self._opp_energy = 100.0
        self._lateral_direction = 1
        self._last_enemy_velocity = 0.0
        self._wall_escape_until = 0
        self._wall_stuck_ticks = 0
        self._last_wall_check_location: Point | None = None
        self._stationary_ticks = 0
        self._last_movement_check_location: Point | None = None
        self._last_turn_number = -1
        self._last_gun_wave_update_turn = -1
        self._last_scan_turn = -1

    def run(self) -> None:
        self.body_color = Color.from_rgb(40, 75, 210)
        self.turret_color = Color.from_rgb(12, 24, 34)
        self.radar_color = Color.from_rgb(238, 218, 50)
        self.bullet_color = Color.from_rgb(245, 225, 80)
        self.scan_color = Color.from_rgb(120, 170, 255)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.max_speed = 8
        self._reset_round_state()

        while self.running:
            self._reset_if_new_round()
            self._update_gun_waves()
            self._maintain_radar()
            self.go()

    def on_game_started(self, event: GameStartedEvent) -> None:
        self._reset_round_state()
        self._last_turn_number = -1

    def on_round_started(self, event: RoundStartedEvent) -> None:
        self._reset_round_state()
        self._last_turn_number = -1

    def on_round_ended(self, event: RoundEndedEvent) -> None:
        self._reset_round_state()
        self._last_turn_number = -1

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        self._reset_if_new_round()
        my_location = self._my_location()
        enemy_location = Point(event.x, event.y)
        abs_bearing = absolute_bearing(my_location, enemy_location)
        enemy_distance = distance(my_location, enemy_location)
        my_heading = tank_degrees_to_java_radians(self.direction)
        enemy_heading = tank_degrees_to_java_radians(event.direction)

        self._last_scan_turn = self.turn_number
        self._lock_radar(abs_bearing)

        lateral_velocity = own_lateral_velocity(self.speed, my_heading, abs_bearing)
        self._surf_directions.insert(0, 1 if lateral_velocity >= 0 else -1)
        self._surf_abs_bearings.insert(0, abs_bearing + math.pi)
        del self._surf_directions[8:]
        del self._surf_abs_bearings[8:]

        bullet_power = self._opp_energy - event.energy
        if (
            0.09 < bullet_power < 3.01
            and len(self._surf_directions) > 2
            and self._enemy_location is not None
        ):
            velocity = bullet_velocity(bullet_power)
            self._enemy_waves.append(
                EnemyWave(
                    fire_location=Point(self._enemy_location.x, self._enemy_location.y),
                    fire_time=max(0, self.turn_number - 1),
                    bullet_velocity=velocity,
                    direct_angle=self._surf_abs_bearings[2],
                    distance_traveled=velocity,
                    direction=self._surf_directions[2],
                )
            )

        self._opp_energy = event.energy
        self._enemy_location = enemy_location

        self._update_enemy_waves(my_location)
        self._do_surfing(my_location, abs_bearing)
        self._aim_and_fire(my_location, enemy_location, abs_bearing, enemy_distance, event.speed, enemy_heading)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if not self._enemy_waves:
            return
        my_location = self._my_location()
        bullet_location = Point(event.bullet.x, event.bullet.y)
        hit_wave = None
        for wave in self._enemy_waves:
            if (
                abs(wave.distance_traveled - distance(my_location, wave.fire_location)) < 50.0
                and abs(bullet_velocity(event.bullet.power) - wave.bullet_velocity) < 0.001
            ):
                hit_wave = wave
                break
        if hit_wave is not None:
            self._log_hit(hit_wave, bullet_location)
            self._enemy_waves.remove(hit_wave)

    def on_hit_wall(self, event: HitWallEvent) -> None:
        self._lateral_direction = -self._lateral_direction
        self._wall_escape_until = self.turn_number + WALL_ESCAPE_TICKS
        self._escape_toward_center(self._my_location())

    def _reset_round_state(self) -> None:
        self._enemy_waves = []
        self._gun_waves = []
        self._surf_directions = []
        self._surf_abs_bearings = []
        self._enemy_location = None
        self._opp_energy = 100.0
        self._lateral_direction = 1
        self._last_enemy_velocity = 0.0
        self._wall_escape_until = 0
        self._wall_stuck_ticks = 0
        self._last_wall_check_location = None
        self._stationary_ticks = 0
        self._last_movement_check_location = None
        self._last_gun_wave_update_turn = -1
        self._last_scan_turn = -1

    def _maintain_radar(self) -> None:
        if self._last_scan_turn >= 0 and self.turn_number - self._last_scan_turn <= RADAR_LOCK_GRACE_TICKS:
            return
        self.set_turn_radar_left(float("inf"))

    def _reset_if_new_round(self) -> None:
        if self._last_turn_number >= 0 and self.turn_number < self._last_turn_number:
            self._reset_round_state()
        self._last_turn_number = self.turn_number

    def _my_location(self) -> Point:
        return Point(self.x, self.y)

    def _update_enemy_waves(self, my_location: Point) -> None:
        kept = []
        for wave in self._enemy_waves:
            wave.distance_traveled = (self.turn_number - wave.fire_time) * wave.bullet_velocity
            if wave.distance_traveled <= distance(my_location, wave.fire_location) + 50.0:
                kept.append(wave)
        self._enemy_waves = kept

    def _closest_surfable_wave(self, my_location: Point) -> EnemyWave | None:
        closest_distance = 50000.0
        surf_wave = None
        for wave in self._enemy_waves:
            wave_distance = distance(my_location, wave.fire_location) - wave.distance_traveled
            if wave.bullet_velocity < wave_distance < closest_distance:
                closest_distance = wave_distance
                surf_wave = wave
        return surf_wave

    def _log_hit(self, wave: EnemyWave, target_location: Point) -> None:
        index = factor_index(wave, target_location)
        for i in range(BINS):
            self._state.surf_stats[i] += 1.0 / (((index - i) ** 2) + 1.0)

    def _predict_position(self, wave: EnemyWave, direction: int, start_location: Point) -> Point:
        predicted_position = Point(start_location.x, start_location.y)
        predicted_velocity = self.speed
        predicted_heading = tank_degrees_to_java_radians(self.direction)
        counter = 0
        intercepted = False

        while not intercepted and counter < 500:
            move_angle = (
                self._wall_smoothing(
                    predicted_position,
                    absolute_bearing(wave.fire_location, predicted_position) + direction * (math.pi / 2.0),
                    direction,
                )
                - predicted_heading
            )
            move_direction = 1
            if math.cos(move_angle) < 0:
                move_angle += math.pi
                move_direction = -1
            move_angle = normal_relative_angle(move_angle)
            max_turning = math.pi / 720.0 * (40.0 - 3.0 * abs(predicted_velocity))
            predicted_heading = normal_relative_angle(
                predicted_heading + limit(-max_turning, move_angle, max_turning)
            )
            predicted_velocity += 2.0 * move_direction if predicted_velocity * move_direction < 0 else move_direction
            predicted_velocity = limit(-8.0, predicted_velocity, 8.0)
            predicted_position = project(predicted_position, predicted_heading, predicted_velocity)
            predicted_position.x = limit(WALL_MARGIN, predicted_position.x, self.arena_width - WALL_MARGIN)
            predicted_position.y = limit(WALL_MARGIN, predicted_position.y, self.arena_height - WALL_MARGIN)
            counter += 1
            if (
                distance(predicted_position, wave.fire_location)
                < wave.distance_traveled + counter * wave.bullet_velocity + wave.bullet_velocity
            ):
                intercepted = True

        return predicted_position

    def _check_danger(self, wave: EnemyWave, direction: int, my_location: Point) -> float:
        index = factor_index(wave, self._predict_position(wave, direction, my_location))
        return self._state.surf_stats[index]

    def _do_surfing(self, my_location: Point, abs_bearing_to_enemy: float) -> None:
        if self._should_escape_wall(my_location):
            self._escape_toward_center(my_location)
            return
        if self._should_escape_stationary(my_location, abs_bearing_to_enemy):
            return

        surf_wave = self._closest_surfable_wave(my_location)
        if surf_wave is None:
            self._fallback_orbit(my_location, abs_bearing_to_enemy)
            return

        danger_left = self._check_danger(surf_wave, -1, my_location)
        danger_right = self._check_danger(surf_wave, 1, my_location)
        go_angle = absolute_bearing(surf_wave.fire_location, my_location)
        if danger_left < danger_right:
            go_angle = self._wall_smoothing(my_location, go_angle - math.pi / 2.0, -1)
        else:
            go_angle = self._wall_smoothing(my_location, go_angle + math.pi / 2.0, 1)
        self._set_back_as_front(go_angle)

    def _fallback_orbit(self, my_location: Point, abs_bearing_to_enemy: float) -> None:
        orientation = 1 if self._lateral_direction >= 0 else -1
        go_angle = self._wall_smoothing(my_location, abs_bearing_to_enemy + math.pi / 2.0 * orientation, orientation)
        self._set_back_as_front(go_angle)

    def _should_escape_wall(self, my_location: Point) -> bool:
        if self.turn_number < self._wall_escape_until:
            return True

        walls = self._near_wall_count(my_location)
        if (
            walls > 0
            and self._last_wall_check_location is not None
            and distance(my_location, self._last_wall_check_location) <= WALL_STUCK_DISTANCE
        ):
            self._wall_stuck_ticks += 1
        else:
            self._wall_stuck_ticks = 0
        self._last_wall_check_location = Point(my_location.x, my_location.y)

        if (walls >= 2 and self._wall_stuck_ticks >= 1) or (walls >= 1 and self._wall_stuck_ticks >= 3):
            self._lateral_direction = -self._lateral_direction
            self._wall_escape_until = self.turn_number + WALL_ESCAPE_TICKS
            self._wall_stuck_ticks = 0
            return True
        return False

    def _should_escape_stationary(self, my_location: Point, abs_bearing_to_enemy: float) -> bool:
        if (
            self._last_movement_check_location is not None
            and distance(my_location, self._last_movement_check_location) <= WALL_STUCK_DISTANCE
        ):
            self._stationary_ticks += 1
        else:
            self._stationary_ticks = 0
        self._last_movement_check_location = Point(my_location.x, my_location.y)

        if self._stationary_ticks < 3:
            return False

        self._stationary_ticks = 0
        self._lateral_direction = -self._lateral_direction
        orientation = 1 if self._lateral_direction >= 0 else -1
        go_angle = self._wall_smoothing(my_location, abs_bearing_to_enemy + math.pi / 2.0 * orientation, orientation)
        self._set_back_as_front(go_angle)
        return True

    def _near_wall_count(self, location: Point) -> int:
        count = 0
        if location.x <= WALL_ESCAPE_MARGIN or location.x >= self.arena_width - WALL_ESCAPE_MARGIN:
            count += 1
        if location.y <= WALL_ESCAPE_MARGIN or location.y >= self.arena_height - WALL_ESCAPE_MARGIN:
            count += 1
        return count

    def _escape_toward_center(self, location: Point) -> None:
        self._set_back_as_front(self._center_escape_angle(location))

    def _center_escape_angle(self, location: Point) -> float:
        return absolute_bearing(location, Point(self.arena_width / 2.0, self.arena_height / 2.0))

    def _wall_smoothing(self, location: Point, angle: float, orientation: int) -> float:
        smoothed = self._smooth_wall_angle(location, angle, orientation)
        if self._in_field(project(location, smoothed, WALL_STICK)):
            return smoothed

        smoothed = self._smooth_wall_angle(location, angle, -orientation)
        if self._in_field(project(location, smoothed, WALL_STICK)):
            return smoothed

        return self._center_escape_angle(location)

    def _smooth_wall_angle(self, location: Point, angle: float, orientation: int) -> float:
        iterations = 0
        while not self._in_field(project(location, angle, WALL_STICK)) and iterations < WALL_SMOOTHING_MAX_ITERATIONS:
            angle += orientation * 0.05
            iterations += 1
        return angle

    def _in_field(self, location: Point) -> bool:
        return (
            WALL_MARGIN <= location.x <= self.arena_width - WALL_MARGIN
            and WALL_MARGIN <= location.y <= self.arena_height - WALL_MARGIN
        )

    def _set_back_as_front(self, go_angle: float) -> None:
        tank_bearing = java_radians_to_tank_degrees(go_angle)
        relative = normal_relative_degrees(tank_bearing - self.direction)
        move_back = False
        if relative > 90.0:
            relative -= 180.0
            move_back = True
        elif relative < -90.0:
            relative += 180.0
            move_back = True
        self.set_turn_left(relative)
        if move_back:
            self.set_back(100.0)
        else:
            self.set_forward(100.0)

    def _aim_and_fire(
        self,
        my_location: Point,
        enemy_location: Point,
        enemy_absolute_bearing: float,
        enemy_distance: float,
        enemy_velocity: float,
        enemy_heading: float,
    ) -> None:
        lateral = enemy_velocity * math.sin(enemy_heading - enemy_absolute_bearing)
        if enemy_velocity != 0:
            self._lateral_direction = sign(lateral)

        buffer = self._gun_buffer(enemy_distance, enemy_velocity, self._last_enemy_velocity)
        self._last_enemy_velocity = enemy_velocity
        offset = self._gun_most_visited_bearing_offset(buffer, self._lateral_direction)
        aim_angle = enemy_absolute_bearing + offset
        self._turn_gun_to(aim_angle)
        if self.energy >= BULLET_POWER and self.set_fire(BULLET_POWER):
            self._gun_waves.append(
                GunWave(
                    gun_location=Point(my_location.x, my_location.y),
                    target_location=Point(enemy_location.x, enemy_location.y),
                    bullet_power=BULLET_POWER,
                    bearing=enemy_absolute_bearing,
                    lateral_direction=self._lateral_direction,
                    buffer=buffer,
                )
            )

    def _gun_buffer(self, enemy_distance: float, enemy_velocity: float, last_enemy_velocity: float) -> list[int]:
        distance_index, velocity_index, last_velocity_index = gun_segment_index(
            enemy_distance,
            enemy_velocity,
            last_enemy_velocity,
        )
        return self._state.gun_stats[distance_index][velocity_index][last_velocity_index]

    @staticmethod
    def _gun_most_visited_bearing_offset(buffer: list[int], lateral_direction: int) -> float:
        most_visited = GUN_MIDDLE_BIN
        for i, visits in enumerate(buffer):
            if visits > buffer[most_visited]:
                most_visited = i
        return lateral_direction * GUN_BIN_WIDTH * (most_visited - GUN_MIDDLE_BIN)

    def _update_gun_waves(self) -> None:
        if self._last_gun_wave_update_turn == self.turn_number:
            return
        self._last_gun_wave_update_turn = self.turn_number
        if self._enemy_location is None:
            return
        kept = []
        for wave in self._gun_waves:
            wave.target_location = Point(self._enemy_location.x, self._enemy_location.y)
            wave.distance_traveled += bullet_velocity(wave.bullet_power)
            if wave.distance_traveled > distance(wave.gun_location, wave.target_location) - WALL_MARGIN:
                bin_index = self._gun_current_bin(wave)
                wave.buffer[bin_index] += 1
            else:
                kept.append(wave)
        self._gun_waves = kept

    @staticmethod
    def _gun_current_bin(wave: GunWave) -> int:
        denominator = wave.lateral_direction * GUN_BIN_WIDTH
        if denominator == 0:
            return GUN_MIDDLE_BIN
        raw = normal_relative_angle(absolute_bearing(wave.gun_location, wave.target_location) - wave.bearing)
        index = round(raw / denominator + GUN_MIDDLE_BIN)
        return int(limit(0, index, GUN_BINS - 1))

    def _turn_gun_to(self, java_angle: float) -> None:
        tank_bearing = java_radians_to_tank_degrees(java_angle)
        self.set_turn_gun_left(normal_relative_degrees(tank_bearing - self.gun_direction))

    def _lock_radar(self, java_angle: float) -> None:
        tank_bearing = java_radians_to_tank_degrees(java_angle)
        self.set_turn_radar_left(normal_relative_degrees(tank_bearing - self.radar_direction) * 2.0)


if __name__ == "__main__":
    BasicGFSurferPort().start()

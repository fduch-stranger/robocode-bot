"""Tank Royale port of voidious.Diamond 1.8.28 (Voidious).

This file is the engine boundary: it presents the running Tank Royale bot as
the ``AdvancedRobot`` the ported ``diamond_port`` package expects (Robocode
radians with 0 up and clockwise, ``setAhead``-style movement commands,
per-turn events in Robocode order) and runs Diamond's turn loop. Everything
else lives in ``diamond_port/``.
"""
from __future__ import annotations

import gc
import math
import os
import sys
from pathlib import Path


_DIRECT_BOOTSTRAP_REEXEC_ENV = "ROBOCODE_DIAMOND_PORT_REEXECED"
_MIN_DIRECT_PYTHON_VERSION = (3, 10)


def _bootstrap_direct_gui_launch() -> None:
    bot_dir = Path(__file__).resolve().parent
    _add_import_path(bot_dir)
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

from robocode_tank_royale.bot_api import Bot, BotInfo, Color  # noqa: E402
from robocode_tank_royale.bot_api.events import (  # noqa: E402
    BotDeathEvent,
    BulletFiredEvent,
    BulletHitBotEvent,
    BulletHitBulletEvent,
    DeathEvent,
    GameStartedEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
    SkippedTurnEvent,
    WonRoundEvent,
)

from bot_core.debug import DebugLogger  # noqa: E402
from bot_core.telemetry.timing import TurnPhaseTimer, TurnTimingTelemetry  # noqa: E402

from diamond_port.dia_utils import HALF_PI, MAX_BULLET_POWER, MIN_BULLET_POWER, BattleField, Point, absolute_bearing, normal_relative_angle  # noqa: E402
from diamond_port.enemy import BulletRecord, ScannedRobotEvent  # noqa: E402
from diamond_port.gun import DiamondFist  # noqa: E402
from diamond_port.move import DiamondWhoosh  # noqa: E402
from diamond_port.radar import DiamondEyes  # noqa: E402

MAX_LOGGED_ERRORS = 5
# Diamond keeps every wave visit of the battle in kd-trees, so generation-2
# collections would grow into long pauses; freeze the survivors each round.
GC_THRESHOLDS = (700, 10, 50)


def tank_degrees_to_java_radians(angle: float) -> float:
    return math.radians(90.0 - angle)


def java_radians_to_tank_degrees(angle: float) -> float:
    return (90.0 - math.degrees(angle)) % 360.0


class RobotAdapter:
    """The ``Diamond extends AdvancedRobot`` view of the running bot.

    Getters return classic Robocode units (radians, 0 up, clockwise; signed
    velocity), setters take Robocode commands and stage the equivalent Tank
    Royale intent. ``max_velocity`` mirrors Diamond's own field, which a new
    robot instance reset to 0 every round.
    """

    def __init__(self, bot: DiamondPort) -> None:
        self.bot = bot
        self.max_velocity = 0.0
        self.verbose = False

    # State -------------------------------------------------------------------
    @property
    def x(self) -> float:
        return self.bot.x

    @property
    def y(self) -> float:
        return self.bot.y

    @property
    def heading_radians(self) -> float:
        return tank_degrees_to_java_radians(self.bot.direction)

    @property
    def gun_heading_radians(self) -> float:
        return tank_degrees_to_java_radians(self.bot.gun_direction)

    @property
    def radar_heading_radians(self) -> float:
        return tank_degrees_to_java_radians(self.bot.radar_direction)

    @property
    def velocity(self) -> float:
        return self.bot.speed

    @property
    def time(self) -> int:
        return self.bot.turn_number

    @property
    def round_num(self) -> int:
        return self.bot.round_number - 1

    @property
    def others(self) -> int:
        return self.bot.enemy_count

    @property
    def energy(self) -> float:
        return self.bot.energy

    @property
    def gun_heat(self) -> float:
        return self.bot.gun_heat

    @property
    def gun_cooling_rate(self) -> float:
        return self.bot.gun_cooling_rate

    @property
    def gun_turn_remaining(self) -> float:
        """Degrees left on the gun turn, Robocode sign (positive is clockwise)."""
        return -self.bot.gun_turn_remaining

    @property
    def distance_remaining(self) -> float:
        return self.bot.distance_remaining

    @property
    def turn_remaining_radians(self) -> float:
        return -math.radians(self.bot.turn_remaining)

    # Commands ------------------------------------------------------------------
    def set_turn_gun_right_radians(self, radians: float) -> None:
        self.bot.set_turn_gun_left(-math.degrees(radians))

    def set_turn_radar_right_radians(self, radians: float) -> None:
        self.bot.set_turn_radar_left(-math.degrees(radians))

    def set_turn_right_radians(self, radians: float) -> None:
        self.bot.set_turn_left(-math.degrees(radians))

    def set_turn_left_radians(self, radians: float) -> None:
        self.bot.set_turn_left(math.degrees(radians))

    def set_ahead(self, distance: float) -> None:
        self.bot.set_forward(distance)

    def set_back(self, distance: float) -> None:
        self.bot.set_forward(-distance)

    def set_max_velocity(self, max_velocity: float) -> None:
        self.max_velocity = max_velocity
        self.bot.max_speed = max_velocity

    def set_back_as_front(self, go_angle: float) -> None:
        """``DiaUtils.setBackAsFront``: drive toward ``go_angle`` with whichever end is closer."""
        angle = normal_relative_angle(go_angle - self.heading_radians)
        if abs(angle) > HALF_PI:
            if angle < 0:
                self.set_turn_right_radians(math.pi + angle)
            else:
                self.set_turn_left_radians(math.pi - angle)
            self.set_back(100.0)
        else:
            if angle < 0:
                self.set_turn_left_radians(-angle)
            else:
                self.set_turn_right_radians(angle)
            self.set_ahead(100.0)

    def set_fire_bullet(self, bullet_power: float) -> bool:
        """``setFireBullet``: true when the engine accepted the shot for next turn."""
        bullet_power = min(max(bullet_power, MIN_BULLET_POWER), MAX_BULLET_POWER)
        accepted = self.bot.set_fire(bullet_power)
        if accepted:
            self.bot.note_pending_fire(bullet_power)
        return accepted


class DiamondPort(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Diamond Port",
                version="1.8.28",
                authors=["robocode-bot"],
                description="Python Tank Royale port of voidious.Diamond 1.8.28 (wave surfing, dynamic clustering guns).",
                game_types={"classic", "1v1", "melee"},
                programming_lang="Python 3",
            )
        )
        self.robot = RobotAdapter(self)
        self.robot.verbose = bool(os.environ.get("ROBOCODE_DIAMOND_PORT_VERBOSE"))
        self.battle_field: BattleField | None = None
        self.radar: DiamondEyes | None = None
        self.move: DiamondWhoosh | None = None
        self.gun: DiamondFist | None = None
        self.is_alive = True
        self._pending_fire_power: float | None = None
        self._pending_energy_deltas: list[tuple[object, float]] = []
        self._last_turn_number = -1
        self._logged_errors = 0
        self._debug = DebugLogger(self, "diamond-port")
        self._timing_telemetry = TurnTimingTelemetry(self._debug, track_gc=True)
        self.phase_timer = TurnPhaseTimer()
        gc.set_threshold(*GC_THRESHOLDS)

    # Lifecycle ---------------------------------------------------------------------
    def run(self) -> None:
        self.body_color = Color.from_rgb(0, 0, 0)
        self.turret_color = Color.from_rgb(0, 0, 0)
        self.radar_color = Color.from_rgb(255, 255, 170)
        self.bullet_color = Color.from_rgb(255, 255, 170)
        self.scan_color = Color.from_rgb(255, 255, 170)
        self.adjust_gun_for_body_turn = True
        self.adjust_radar_for_gun_turn = True
        self.adjust_radar_for_body_turn = True
        self._init_round()
        while self.running and self.is_alive:
            timing_start = self._timing_telemetry.begin()
            self.phase_timer.start()
            if self._last_turn_number >= 0 and self.turn_number < self._last_turn_number:
                self._init_round()
            self._last_turn_number = self.turn_number
            try:
                self._apply_pending_energy_deltas()
                self.move.execute()
                self.phase_timer.mark("movement")
                self.gun.execute()
                self.phase_timer.mark("gun")
                self.radar.execute()
                self.phase_timer.mark("radar")
            except Exception as exc:  # Diamond logged and rethrew; the port keeps playing.
                self._log_error(exc)
            self._timing_telemetry.record_turn(self, timing_start, phase_us=self.phase_timer.snapshot(), **self._timing_fields())
            self.go()

    def _init_components(self) -> None:
        """``Diamond.initComponents``: the Java statics, created once per battle."""
        self.battle_field = BattleField(float(self.arena_width), float(self.arena_height))
        self.radar = DiamondEyes(self.robot, self.battle_field)
        self.move = DiamondWhoosh(self.robot, self.battle_field)
        self.gun = DiamondFist(self.robot, self.battle_field)
        self.gun.add_fire_listener(self.move)

    def _init_round(self) -> None:
        if self.gun is None:
            self._init_components()
        self.robot.max_velocity = 0.0
        self.is_alive = True
        self._pending_fire_power = None
        self._pending_energy_deltas.clear()
        self.max_speed = 8
        self.radar.init_round(self.robot)
        self.move.init_round(self.robot)
        self.gun.init_round(self.robot)
        gc.freeze()

    def _apply_pending_energy_deltas(self) -> None:
        """Tank Royale reports our bullet hits and the enemy's hit bonus one scan
        before the scanned energy reflects them; Diamond adjusted its tracked
        enemy energy at event time, so the port applies the same adjustments
        after the tick's scan has been read."""
        if not self._pending_energy_deltas:
            return
        for bot_name, delta in self._pending_energy_deltas:
            self.move.apply_energy_delta(bot_name, delta)
        self._pending_energy_deltas.clear()

    def note_pending_fire(self, bullet_power: float) -> None:
        self._pending_fire_power = bullet_power

    # Events ----------------------------------------------------------------------------
    def on_game_started(self, event: GameStartedEvent) -> None:
        self.gun = None
        self.move = None
        self.radar = None

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        if self.gun is None:
            return
        my_location = Point(self.x, self.y)
        enemy_location = Point(event.x, event.y)
        scan = ScannedRobotEvent(
            event.scanned_bot_id,
            self.turn_number,
            enemy_location,
            tank_degrees_to_java_radians(event.direction),
            event.speed,
            event.energy,
            my_location.distance(enemy_location),
        )
        try:
            self.radar.on_scanned_robot(scan)
            self.move.on_scanned_robot(scan)
            self.gun.on_scanned_robot(scan)
        except Exception as exc:
            self._log_error(exc)

    def on_bot_death(self, event: BotDeathEvent) -> None:
        if self.gun is None or event.victim_id == self.my_id:
            return
        self.radar.on_robot_death(event.victim_id)
        self.move.on_robot_death(event.victim_id)
        self.gun.on_robot_death(event.victim_id)

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if self.gun is None:
            return
        bullet = self._bullet_record(event.bullet)
        try:
            self.move.on_hit_by_bullet(bullet)
        except Exception as exc:
            self._log_error(exc)
        self._pending_energy_deltas.append((bullet.name, 3 * bullet.power))

    def on_bullet_hit(self, event: BulletHitBotEvent) -> None:
        if self.gun is None:
            return
        bullet = self._bullet_record(event.bullet)
        try:
            self.move.on_bullet_hit(event.victim_id, bullet)
            self.gun.on_bullet_hit(event.victim_id, bullet)
        except Exception as exc:
            self._log_error(exc)
        self._pending_energy_deltas.append((event.victim_id, -event.damage))

    def on_bullet_hit_bullet(self, event: BulletHitBulletEvent) -> None:
        if self.gun is None:
            return
        my_bullet = self._bullet_record(event.bullet)
        hit_bullet = self._bullet_record(event.hit_bullet)
        try:
            self.move.on_bullet_hit_bullet(my_bullet, hit_bullet)
            self.gun.on_bullet_hit_bullet(my_bullet, hit_bullet)
        except Exception as exc:
            self._log_error(exc)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        self._pending_fire_power = None

    def on_hit_wall(self, event: HitWallEvent) -> None:
        if self.robot.verbose:
            print(f"WARNING: I hit a wall ({self.turn_number}).", file=sys.stderr)

    def on_won_round(self, event: WonRoundEvent) -> None:
        self._round_over()

    def on_death(self, event: DeathEvent) -> None:
        self.is_alive = False
        self._round_over()

    def on_skipped_turn(self, event: SkippedTurnEvent) -> None:
        self._timing_telemetry.record_skipped_turn(self, event, **self._timing_fields())

    # Helpers ------------------------------------------------------------------------------
    def _round_over(self) -> None:
        if self.gun is None:
            return
        try:
            self.gun.round_over()
            self.move.round_over()
        except Exception as exc:
            self._log_error(exc)

    @staticmethod
    def _bullet_record(bullet) -> BulletRecord:
        return BulletRecord(bullet.owner_id, bullet.power, bullet.x, bullet.y, tank_degrees_to_java_radians(bullet.direction), bullet.bullet_id)

    def _timing_fields(self) -> dict[str, object]:
        gun = self.gun
        move = self.move
        gun_waves = 0
        movement_waves = 0
        known_targets = 0
        if gun is not None:
            manager = gun.gun_data_manager
            known_targets = sum(1 for enemy in manager.get_all_enemy_data() if enemy.alive)
            gun_waves = sum(enemy.wave_manager.size() for enemy in manager.get_all_enemy_data())
        if move is not None:
            movement_waves = sum(enemy.wave_manager.size() for enemy in move.move_data_manager.get_all_enemy_data())
        return {
            "known_targets": known_targets,
            "gun_heat": round(self.gun_heat, 3),
            "gun_waves": gun_waves,
            "movement_waves": movement_waves,
        }

    def _log_error(self, exc: Exception) -> None:
        self._logged_errors += 1
        if self._logged_errors <= MAX_LOGGED_ERRORS:
            import traceback

            print(f"[diamond-port] turn {self.turn_number}: {exc!r}", file=sys.stderr)
            traceback.print_exc()


if __name__ == "__main__":
    DiamondPort().start()

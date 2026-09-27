"""Tank Royale port of lxx.Tomcat 3.68 (Alexey "jdev" Zhidkov).

This file is the engine boundary: it turns Tank Royale state and events into
the classic Robocode view the ported ``tomcat_port`` package expects (radians
with 0 up and clockwise, per-turn events, ``setAhead``-style movement), runs
Tomcat's turn loop, and maps the resulting decision back to Tank Royale
commands. Everything else lives in ``tomcat_port/``.
"""
from __future__ import annotations

import math
import os
import sys
from collections import deque
from pathlib import Path


_DIRECT_BOOTSTRAP_REEXEC_ENV = "ROBOCODE_TOMCAT_PORT_REEXECED"
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
    BulletHitWallEvent,
    DeathEvent,
    GameStartedEvent,
    HitBotEvent,
    HitByBulletEvent,
    HitWallEvent,
    ScannedBotEvent,
    SkippedTurnEvent,
)

from bot_core.debug import DebugLogger  # noqa: E402
from bot_core.telemetry.timing import TurnPhaseTimer, TurnTimingTelemetry  # noqa: E402

from tomcat_port import enemy_gun_model, gun as gun_module, office as office_module, targeting  # noqa: E402
from tomcat_port.bullets import BulletInfo, LXXBullet  # noqa: E402
from tomcat_port.lxx_utils import ROBOT_SIDE_HALF_SIZE, ROBOT_SIDE_SIZE, BattleField, LXXPoint, PointLike, bullet_speed, sign  # noqa: E402
from tomcat_port.movement import MovementDecision  # noqa: E402
from tomcat_port.office import Office  # noqa: E402
from tomcat_port.snapshots import MySnapshot  # noqa: E402
from tomcat_port.strategies import StrategySelector, TurnDecision  # noqa: E402

MAX_LOGGED_ERRORS = 5


def tank_degrees_to_java_radians(angle: float) -> float:
    return math.radians(90.0 - angle)


def java_radians_to_tank_degrees(angle: float) -> float:
    return (90.0 - math.degrees(angle)) % 360.0


def reset_battle_persistent_state() -> None:
    targeting.reset_battle_persistent_state()
    enemy_gun_model.reset_battle_persistent_state()
    gun_module.reset_battle_persistent_state()
    gun_module.reset_targeting_profiles()
    office_module.reset_battle_statistics()


class RobotView(PointLike):
    """The ``LXXRobot`` view of the running bot used by every ported manager."""

    def __init__(self, bot: TomcatPort) -> None:
        self.bot = bot

    @property
    def name(self):
        return self.bot.my_id

    @property
    def time(self) -> int:
        return self.bot.turn_number

    @property
    def round(self) -> int:
        return self.bot.round_number

    @property
    def x(self) -> float:
        return self.bot.x

    @property
    def y(self) -> float:
        return self.bot.y

    @property
    def position(self) -> LXXPoint:
        return LXXPoint(self.bot.x, self.bot.y)

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
    def speed(self) -> float:
        return abs(self.bot.speed)

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
    def battle_field(self) -> BattleField:
        return self.bot.battle_field

    @property
    def width(self) -> float:
        return ROBOT_SIDE_SIZE

    @property
    def height(self) -> float:
        return ROBOT_SIDE_SIZE

    @property
    def is_alive(self) -> bool:
        return self.bot.is_alive

    @property
    def prev_snapshot(self) -> MySnapshot | None:
        return self.bot.prev_snapshot

    @property
    def current_snapshot(self) -> MySnapshot | None:
        return self.bot.current_snapshot

    @property
    def fire_power(self) -> float:
        decision = self.bot.turn_decision
        return decision.fire_power if decision is not None else 0.0

    @property
    def last_fire_time(self) -> int:
        return self.bot.last_fire_time

    @property
    def initial_others(self) -> int:
        return self.bot.initial_others

    @property
    def bullets_in_air(self) -> list:
        office = self.bot.office
        return office.bullet_manager.get_bullet_snapshots() if office is not None else []

    def turns_to_gun_cool(self) -> int:
        return int(round(self.bot.gun_heat / self.bot.gun_cooling_rate))

    def mark_phase(self, name: str) -> None:
        self.bot.phase_timer.mark(name)


class TomcatPort(Bot):
    def __init__(self) -> None:
        super().__init__(
            BotInfo(
                name="Tomcat Port",
                version="3.68",
                authors=["robocode-bot"],
                description="Python Tank Royale port of lxx.Tomcat 3.68 (wave surfing, Tomcat Claws gun).",
                game_types={"classic", "1v1"},
                programming_lang="Python 3",
            )
        )
        self.view = RobotView(self)
        self.battle_field: BattleField | None = None
        self.office: Office | None = None
        self.strategy_selector: StrategySelector | None = None
        self.turn_decision: TurnDecision | None = None
        self.prev_snapshot: MySnapshot | None = None
        self.current_snapshot: MySnapshot | None = None
        self.is_alive = True
        self.last_fire_time = 0
        self.initial_others = 1
        self._last10_positions: deque[LXXPoint] = deque(maxlen=10)
        self._pending_fire: tuple[float, float, float, float] | None = None
        self._fired_bullet = None
        self._last_turn_number = -1
        self._logged_errors = 0
        self._debug = DebugLogger(self, "tomcat-port")
        self._timing_telemetry = TurnTimingTelemetry(self._debug)
        self.phase_timer = TurnPhaseTimer()

    # Lifecycle -----------------------------------------------------------
    def run(self) -> None:
        self.body_color = Color.from_rgb(255, 67, 0)
        self.turret_color = Color.from_rgb(255, 144, 66)
        self.radar_color = Color.from_rgb(255, 192, 66)
        self.bullet_color = Color.from_rgb(255, 192, 66)
        self.scan_color = Color.from_rgb(255, 192, 66)
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
                self._on_status()
                self.phase_timer.mark("status")
                self._notify_listeners()
                self.phase_timer.mark("listeners")
                self._do_turn()
                self.phase_timer.mark("commands")
            except Exception as exc:  # Tomcat catches Throwable per turn and keeps running.
                self._log_error(exc)
            self._timing_telemetry.record_turn(self, timing_start, phase_us=self.phase_timer.snapshot(), **self._timing_fields())
            self.go()

    def _init_round(self) -> None:
        self.battle_field = BattleField(
            ROBOT_SIDE_HALF_SIZE,
            ROBOT_SIDE_HALF_SIZE,
            int(self.arena_width) - ROBOT_SIDE_SIZE,
            int(self.arena_height) - ROBOT_SIDE_SIZE,
        )
        self.initial_others = max(1, self.enemy_count)
        self.turn_decision = None
        self.prev_snapshot = None
        self.current_snapshot = None
        self.is_alive = True
        self.last_fire_time = 0
        self._last10_positions.clear()
        self._pending_fire = None
        self._fired_bullet = None
        self.max_speed = 8
        self.office = Office(self.view)
        self.strategy_selector = StrategySelector(self.view, self.office)

    def _on_status(self) -> None:
        """``BasicRobot.onStatus``: roll the snapshots and the 10-tick position window."""
        self.prev_snapshot = self.current_snapshot if self.current_snapshot is not None else MySnapshot(self.view)
        self._last10_positions.append(LXXPoint(self.x, self.y))
        last10_dist = self._last10_positions[0].a_distance(self._last10_positions[-1])
        self.current_snapshot = MySnapshot(self.view, self.prev_snapshot, last10_dist)

    def _notify_listeners(self) -> None:
        """``Tomcat.notifyListeners``: the fire event for last turn's shot, then the tick."""
        assert self.office is not None
        pending = self._pending_fire
        decision = self.turn_decision
        if pending is not None and decision is not None and decision.target is not None:
            power, heading, x, y = pending
            bullet_id = -1
            fired = self._fired_bullet
            if fired is not None and abs(fired.power - power) < 0.01:
                bullet_id = fired.bullet_id
                heading = tank_degrees_to_java_radians(fired.direction)
            target = decision.target
            source_state = self.prev_snapshot
            target_state = target.prev_snapshot if target.prev_snapshot is not None else target.current_snapshot
            if source_state is not None and target_state is not None:
                wave = self.office.wave_manager.launch_wave(source_state, target_state, target, bullet_speed(power), None)
                lxx_bullet = LXXBullet(BulletInfo(heading, power, x, y, bullet_id), wave, decision.aim_prediction_data)
                self.office.on_fire(lxx_bullet)
                self.last_fire_time = self.turn_number
        self._pending_fire = None
        self._fired_bullet = None
        self.office.on_tick()

    def _do_turn(self) -> None:
        assert self.strategy_selector is not None
        strategy = self.strategy_selector.select_strategy()
        if strategy is None:
            return
        decision = strategy.make_decision()
        self.turn_decision = decision
        if decision.gun_turn_rate is not None:
            self._handle_gun(decision)
        self._move(decision.movement_decision)
        if decision.radar_turn_rate is not None:
            self.set_turn_radar_left(-math.degrees(decision.radar_turn_rate))

    def _handle_gun(self, decision: TurnDecision) -> None:
        if self.gun_heat == 0:
            if abs(self.gun_turn_remaining) > 1:
                return
            if decision.fire_power > 0:
                if self.set_fire(decision.fire_power):
                    self._pending_fire = (decision.fire_power, self.view.gun_heading_radians, self.x, self.y)
                return
        assert decision.gun_turn_rate is not None
        self.set_turn_gun_left(-math.degrees(decision.gun_turn_rate))

    def _move(self, decision: MovementDecision) -> None:
        """``Tomcat.move``: per-turn turn rate plus ``setMaxVelocity`` and ``setAhead(100 * sign)``."""
        self.set_turn_left(-math.degrees(decision.turn_rate_radians))
        desired = decision.desired_velocity
        if sign(self.speed) != sign(desired) and abs(self.speed) > 0:
            self.max_speed = 0
        else:
            self.max_speed = abs(desired)
        self.set_forward(100.0 * sign(desired))

    # Events -----------------------------------------------------------------
    def on_game_started(self, event: GameStartedEvent) -> None:
        reset_battle_persistent_state()

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        if self.office is None:
            return
        self.office.on_scanned(
            event.scanned_bot_id,
            targeting.ScannedEvent(
                self.turn_number,
                event.x,
                event.y,
                tank_degrees_to_java_radians(event.direction),
                event.speed,
                event.energy,
            ),
        )

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        self._fired_bullet = event.bullet

    def on_hit_by_bullet(self, event: HitByBulletEvent) -> None:
        if self.office is None:
            return
        bullet = event.bullet
        self.office.on_hit_by_bullet(bullet.owner_id, self._bullet_info(bullet))

    def on_bullet_hit(self, event: BulletHitBotEvent) -> None:
        if self.office is None:
            return
        self.office.on_bullet_hit(event.victim_id, self._bullet_info(event.bullet), event.energy)

    def on_bullet_hit_bullet(self, event: BulletHitBulletEvent) -> None:
        if self.office is None:
            return
        self.office.on_bullet_hit_bullet(self._bullet_info(event.bullet), self._bullet_info(event.hit_bullet))

    def on_bullet_hit_wall(self, event: BulletHitWallEvent) -> None:
        if self.office is None:
            return
        self.office.on_bullet_missed(self._bullet_info(event.bullet))

    def on_hit_bot(self, event: HitBotEvent) -> None:
        if self.office is None:
            return
        self.office.on_hit_robot(event.victim_id, targeting.HitRobotEvent(self.turn_number, event.x, event.y, event.energy))

    def on_bot_death(self, event: BotDeathEvent) -> None:
        if self.office is None or event.victim_id == self.my_id:
            return
        self.office.on_robot_death(event.victim_id)

    def on_death(self, event: DeathEvent) -> None:
        self.is_alive = False

    def on_hit_wall(self, event: HitWallEvent) -> None:
        if self.office is not None:
            self.office.statistics_manager.on_hit_wall()

    def on_skipped_turn(self, event: SkippedTurnEvent) -> None:
        if self.office is not None:
            self.office.statistics_manager.on_skipped_turn()
        self._timing_telemetry.record_skipped_turn(self, event, **self._timing_fields())

    # Helpers ----------------------------------------------------------------
    @staticmethod
    def _bullet_info(bullet) -> BulletInfo:
        return BulletInfo(tank_degrees_to_java_radians(bullet.direction), bullet.power, bullet.x, bullet.y, bullet.bullet_id)

    def _timing_fields(self) -> dict[str, object]:
        office = self.office
        return {
            "known_targets": office.target_manager.get_alive_target_count() if office is not None else 0,
            "gun_heat": round(self.gun_heat, 3),
            "gun_waves": len(office.bullet_manager.get_bullets()) if office is not None else 0,
            "movement_waves": len(office.enemy_bullet_manager.get_all_bullets_on_air()) if office is not None else 0,
        }

    def _log_error(self, exc: Exception) -> None:
        self._logged_errors += 1
        if self._logged_errors <= MAX_LOGGED_ERRORS:
            import traceback

            print(f"[tomcat-port] turn {self.turn_number}: {exc!r}", file=sys.stderr)
            traceback.print_exc()


if __name__ == "__main__":
    TomcatPort().start()

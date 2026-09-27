import importlib.util
import json
import math
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "ports" / "tomcat-port"


def load_port_module():
    if str(BOT_DIR) not in sys.path:
        sys.path.insert(0, str(BOT_DIR))
    module_path = BOT_DIR / "tomcat-port.py"
    spec = importlib.util.spec_from_file_location("tomcat_port_bot", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["tomcat_port_bot"] = module
    spec.loader.exec_module(module)
    return module


port = load_port_module()

from tomcat_port import lxx_utils  # noqa: E402
from tomcat_port.bullets import BulletInfo  # noqa: E402
from tomcat_port.data_analysis import KdTree  # noqa: E402
from tomcat_port.movement import MovementDecision  # noqa: E402
from tomcat_port.office import Office  # noqa: E402
from tomcat_port.snapshots import MySnapshot, RobotImage  # noqa: E402
from tomcat_port.strategies import StrategySelector  # noqa: E402
from tomcat_port.targeting import ScannedEvent  # noqa: E402
from tomcat_port.waves import Wave  # noqa: E402


class FakeCommandBot:
    def __init__(self, speed: float = 0.0, gun_heat: float = 0.0, gun_turn_remaining: float = 0.0, fire_result: bool = True) -> None:
        self.speed = speed
        self.gun_heat = gun_heat
        self.gun_turn_remaining = gun_turn_remaining
        self.fire_result = fire_result
        self.max_speed = None
        self.commands: list[tuple] = []
        self.x = 100.0
        self.y = 100.0
        self.gun_direction = 90.0
        self.view = SimpleNamespace(gun_heading_radians=0.0)
        self._pending_fire = None

    def set_turn_left(self, degrees: float) -> None:
        self.commands.append(("turn_left", degrees))

    def set_forward(self, distance: float) -> None:
        self.commands.append(("forward", distance))

    def set_turn_gun_left(self, degrees: float) -> None:
        self.commands.append(("gun_left", degrees))

    def set_fire(self, power: float) -> bool:
        self.commands.append(("fire", power))
        return self.fire_result


class FakeView(lxx_utils.PointLike):
    """A scripted ``RobotView`` for driving the office without an engine."""

    def __init__(self, battle_field: lxx_utils.BattleField) -> None:
        self.name = 1
        self.time = 0
        self.round = 0
        self.x = 300.0
        self.y = 300.0
        self.heading_radians = 0.0
        self.gun_heading_radians = 0.0
        self.radar_heading_radians = 0.0
        self.velocity = 0.0
        self.energy = 100.0
        self.gun_heat = 0.0
        self.gun_cooling_rate = 0.1
        self.battle_field = battle_field
        self.width = 36.0
        self.height = 36.0
        self.is_alive = True
        self.prev_snapshot = None
        self.current_snapshot = None
        self.fire_power = 0.0
        self.last_fire_time = 0
        self.initial_others = 1
        self.office = None

    @property
    def speed(self) -> float:
        return abs(self.velocity)

    @property
    def position(self) -> lxx_utils.LXXPoint:
        return lxx_utils.LXXPoint(self.x, self.y)

    @property
    def bullets_in_air(self) -> list:
        return self.office.bullet_manager.get_bullet_snapshots() if self.office is not None else []

    def turns_to_gun_cool(self) -> int:
        return int(round(self.gun_heat / self.gun_cooling_rate))

    def advance(self) -> None:
        self.time += 1
        self.prev_snapshot = self.current_snapshot if self.current_snapshot is not None else MySnapshot(self)
        self.current_snapshot = MySnapshot(self, self.prev_snapshot, 0.0)


class TomcatPortTest(unittest.TestCase):
    def test_manifest_and_launcher_use_port_name(self) -> None:
        manifest = json.loads((BOT_DIR / "tomcat-port.json").read_text(encoding="utf-8"))
        self.assertEqual("Tomcat Port", manifest["name"])
        self.assertEqual("tomcat-port", manifest["base"])
        launcher = (BOT_DIR / "tomcat-port.sh").read_text(encoding="utf-8")
        self.assertIn('"$BOT_DIR/tomcat-port.py"', launcher)

    def test_tank_and_legacy_angle_conversions_are_inverse(self) -> None:
        for degrees in (0.0, 45.0, 90.0, 180.0, 270.0, 359.0):
            radians = port.tank_degrees_to_java_radians(degrees)
            self.assertAlmostEqual(degrees, port.java_radians_to_tank_degrees(radians))
        # Tank Royale 90 degrees (north) is legacy heading 0.
        self.assertAlmostEqual(0.0, port.tank_degrees_to_java_radians(90.0))

    def test_move_maps_turn_rate_max_velocity_and_ahead(self) -> None:
        bot = FakeCommandBot(speed=3.0)
        port.TomcatPort._move(bot, MovementDecision(8.0, math.radians(5.0)))
        self.assertEqual(("turn_left", -5.0), bot.commands[0])
        self.assertEqual(8.0, bot.max_speed)
        self.assertEqual(("forward", 100.0), bot.commands[1])

    def test_move_reversal_stops_first_like_the_robocode_workaround(self) -> None:
        bot = FakeCommandBot(speed=5.0)
        port.TomcatPort._move(bot, MovementDecision(-8.0, 0.0))
        self.assertEqual(0, bot.max_speed)
        self.assertEqual(("forward", -100.0), bot.commands[-1])

    def test_move_stop_uses_zero_ahead(self) -> None:
        bot = FakeCommandBot(speed=0.0)
        port.TomcatPort._move(bot, MovementDecision(0.0, 0.0))
        self.assertEqual(0.0, bot.max_speed)
        self.assertEqual(("forward", 0.0), bot.commands[-1])

    def test_handle_gun_fires_only_when_cool_and_aligned(self) -> None:
        decision = SimpleNamespace(fire_power=1.9, gun_turn_rate=math.radians(10.0))
        hot = FakeCommandBot(gun_heat=0.5)
        port.TomcatPort._handle_gun(hot, decision)
        self.assertEqual([("gun_left", -10.0)], hot.commands)

        misaligned = FakeCommandBot(gun_heat=0.0, gun_turn_remaining=3.0)
        port.TomcatPort._handle_gun(misaligned, decision)
        self.assertEqual([], misaligned.commands)

        ready = FakeCommandBot(gun_heat=0.0, gun_turn_remaining=0.5)
        port.TomcatPort._handle_gun(ready, decision)
        self.assertEqual([("fire", 1.9)], ready.commands)
        self.assertIsNotNone(ready._pending_fire)

        rejected = FakeCommandBot(gun_heat=0.0, gun_turn_remaining=0.5, fire_result=False)
        port.TomcatPort._handle_gun(rejected, decision)
        self.assertIsNone(rejected._pending_fire)

    def test_robot_image_accelerates_and_projects_forward(self) -> None:
        original = SimpleNamespace(
            x=100.0, y=100.0, velocity=0.0, heading_radians=0.0, battle_field=None, energy=100.0, name=1,
            acceleration=0.0, absolute_heading_radians=0.0, last_direction=1,
        )
        image = RobotImage(original)
        image.apply(MovementDecision(8.0, 0.0))
        self.assertAlmostEqual(1.0, image.speed)
        self.assertAlmostEqual(101.0, image.y)
        image.apply(MovementDecision(-8.0, 0.0))
        self.assertAlmostEqual(0.0, image.speed)

    def test_kd_tree_nearest_neighbours_match_brute_force(self) -> None:
        rng = random.Random(7)
        tree = KdTree(4)
        points = [[rng.random() for _ in range(4)] for _ in range(400)]
        for index, point in enumerate(points):
            tree.add_point(point, index)
        query = [0.5, 0.25, 0.75, 0.4]
        expected = sorted(range(len(points)), key=lambda i: sum((points[i][d] - query[d]) ** 2 for d in range(4)))[:12]
        result = [value for _, value in tree.nearest_neighbor(query, 12)]
        self.assertEqual(expected, result)

    def test_battle_field_wall_smoothing_leaves_open_field_headings_alone(self) -> None:
        field = lxx_utils.BattleField(18, 18, 800 - 36, 600 - 36)
        heading = math.radians(45.0)
        self.assertAlmostEqual(heading, field.smooth_walls(lxx_utils.LXXPoint(400, 300), heading, True))
        near_wall = field.smooth_walls(lxx_utils.LXXPoint(780, 300), math.radians(90.0), True)
        self.assertNotAlmostEqual(math.radians(90.0), near_wall)

    def test_wave_distance_and_hit_interval(self) -> None:
        target = SimpleNamespace(time=10, x=400.0, y=300.0, width=36.0, height=36.0, is_alive=True)
        source = lxx_utils.LXXPoint(400.0, 100.0)
        source_state = SimpleNamespace(x=400.0, y=100.0, name=2, angle_to=source.angle_to, project=source.project, a_distance=source.a_distance)
        wave = Wave(source_state, target, target, 11.0, 10)
        self.assertAlmostEqual(11.0, wave.traveled_distance)
        target.time = 27
        self.assertTrue(wave.check())
        self.assertIsNotNone(wave.hit_bearing_offset_interval)

    def test_office_detects_enemy_fire_and_surfs_it(self) -> None:
        field = lxx_utils.BattleField(18, 18, 800 - 36, 600 - 36)
        view = FakeView(field)
        office = Office(view)
        view.office = office
        selector = StrategySelector(view, office)
        enemy_id = 2
        # The enemy gun starts hot (3.0 heat, 0.1 cooling), so an energy drop only
        # reads as a shot once 30 turns have passed.
        energies = [100.0] * 33 + [98.1, 98.1, 98.1]
        decisions = []
        for step, energy in enumerate(energies):
            view.advance()
            # Move the enemy consistently with its reported speed, or the wall-hit
            # heuristic explains the energy drop away.
            office.on_scanned(enemy_id, ScannedEvent(view.time, 600.0, 100.0 + 8.0 * step, 0.0, 8.0, energy))
            office.on_tick()
            strategy = selector.select_strategy()
            self.assertIsNotNone(strategy)
            decisions.append(strategy.make_decision())
        target = office.target_manager.get_duel_opponent()
        self.assertIsNotNone(target)
        self.assertAlmostEqual(1.9, target.enemy_last_fire_power, places=6)
        self.assertEqual(1, len(office.enemy_bullet_manager.get_all_bullets_on_air()))
        last = decisions[-1]
        self.assertIsNotNone(last.movement_decision)
        self.assertLessEqual(abs(last.movement_decision.turn_rate_radians), lxx_utils.MAX_TURN_RATE_RADIANS + 1e-9)
        self.assertLessEqual(abs(last.movement_decision.desired_velocity), lxx_utils.MAX_VELOCITY)

    def test_fire_event_creates_own_wave_and_bullet(self) -> None:
        field = lxx_utils.BattleField(18, 18, 800 - 36, 600 - 36)
        view = FakeView(field)
        office = Office(view)
        view.office = office
        enemy_id = 2
        for step in range(3):
            view.advance()
            office.on_scanned(enemy_id, ScannedEvent(view.time, 600.0, 300.0 + step, math.radians(90.0), 8.0, 100.0))
            office.on_tick()
        target = office.target_manager.get_duel_opponent()
        wave = office.wave_manager.launch_wave(view.prev_snapshot, target.prev_snapshot, target, lxx_utils.bullet_speed(1.9), None)
        bullet = port.LXXBullet(BulletInfo(0.0, 1.9, view.x, view.y, 7), wave, None)
        office.on_fire(bullet)
        self.assertEqual(1, len(office.bullet_manager.get_bullets()))
        self.assertEqual(1, len(view.bullets_in_air))
        self.assertIs(bullet, office.bullet_manager.get_lxx_bullet(BulletInfo(0.0, 1.9, 0.0, 0.0, 7)))


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import math
import random
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "ports" / "diamond-port"


def load_port_module():
    if str(BOT_DIR) not in sys.path:
        sys.path.insert(0, str(BOT_DIR))
    module_path = BOT_DIR / "diamond-port.py"
    spec = importlib.util.spec_from_file_location("diamond_port_bot", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["diamond_port_bot"] = module
    spec.loader.exec_module(module)
    return module


port = load_port_module()

from diamond_port import dia_utils  # noqa: E402
from diamond_port.dia_utils import BattleField, Point, RobotState  # noqa: E402
from diamond_port.enemy import BulletRecord, ScannedRobotEvent  # noqa: E402
from diamond_port.gun import DiamondFist, PerceptualGun  # noqa: E402
from diamond_port.kd_tree import KdTree  # noqa: E402
from diamond_port.knn_view import KnnView  # noqa: E402
from diamond_port.move import DiamondWhoosh, NormalFormula  # noqa: E402
from diamond_port.movement_predictor import MovementPredictor  # noqa: E402
from diamond_port.radar import DiamondEyes  # noqa: E402
from diamond_port.wave import BREAKING_CENTER, BREAKING_FRONT, GONE, MIDAIR, Wave  # noqa: E402


class FakeTankRoyaleBot:
    """Just enough of ``robocode_tank_royale.bot_api.Bot`` for ``RobotAdapter``."""

    def __init__(self) -> None:
        self.direction = 90.0
        self.gun_direction = 90.0
        self.radar_direction = 90.0
        self.gun_heat = 0.0
        self.energy = 100.0
        self.max_speed = 8.0
        self.commands: list[tuple] = []
        self.fire_result = True
        self.pending: list[float] = []

    def set_turn_left(self, degrees: float) -> None:
        self.commands.append(("turn_left", round(degrees, 6)))

    def set_forward(self, distance: float) -> None:
        self.commands.append(("forward", distance))

    def set_turn_gun_left(self, degrees: float) -> None:
        self.commands.append(("gun_left", round(degrees, 6)))

    def set_turn_radar_left(self, degrees: float) -> None:
        self.commands.append(("radar_left", round(degrees, 6)))

    def set_fire(self, power: float) -> bool:
        self.commands.append(("fire", power))
        return self.fire_result

    def note_pending_fire(self, power: float) -> None:
        self.pending.append(power)


class FakeRobot:
    """A scripted ``RobotAdapter`` stand-in with crude Robocode physics."""

    def __init__(self, field: BattleField) -> None:
        self.field = field
        self.x = 200.0
        self.y = 200.0
        self.heading_radians = 0.0
        self.gun_heading_radians = 0.0
        self.radar_heading_radians = 0.0
        self.velocity = 0.0
        self.time = 0
        self.round_num = 0
        self.others = 1
        self.energy = 100.0
        self.gun_heat = 3.0
        self.gun_cooling_rate = 0.1
        self.gun_turn_remaining = 0.0
        self.distance_remaining = 0.0
        self.turn_remaining_radians = 0.0
        self.max_velocity = 0.0
        self.verbose = False
        self.fired: list[float] = []
        self.moves: list[float] = []
        self._turn = 0.0
        self._ahead = 0.0
        self._gun_turn = 0.0

    def set_turn_gun_right_radians(self, radians: float) -> None:
        self._gun_turn = radians

    def set_turn_radar_right_radians(self, radians: float) -> None:
        pass

    def set_turn_right_radians(self, radians: float) -> None:
        self._turn = radians

    def set_turn_left_radians(self, radians: float) -> None:
        self._turn = -radians

    def set_ahead(self, distance: float) -> None:
        self._ahead = distance
        self.moves.append(distance)

    def set_back(self, distance: float) -> None:
        self._ahead = -distance
        self.moves.append(-distance)

    def set_max_velocity(self, max_velocity: float) -> None:
        self.max_velocity = max_velocity

    def set_back_as_front(self, go_angle: float) -> None:
        angle = dia_utils.normal_relative_angle(go_angle - self.heading_radians)
        if abs(angle) > dia_utils.HALF_PI:
            self.set_turn_right_radians(math.pi + angle if angle < 0 else angle - math.pi)
            self.set_back(100.0)
        else:
            self.set_turn_right_radians(angle)
            self.set_ahead(100.0)

    def set_fire_bullet(self, power: float) -> bool:
        if self.gun_heat > 0 or self.energy < power:
            return False
        self.fired.append(power)
        self.gun_heat = 1 + power / 5
        self.energy -= power
        return True

    def step(self) -> None:
        max_turn = dia_utils.get_turn_rate_radians(self.velocity)
        turn = max(-max_turn, min(self._turn, max_turn))
        self.heading_radians = (self.heading_radians + turn) % (2 * math.pi)
        self._turn -= turn
        self.turn_remaining_radians = self._turn
        target = math.copysign(self.max_velocity, self._ahead) if self._ahead != 0 else 0.0
        if self.velocity < target:
            self.velocity = min(target, self.velocity + 1)
        elif self.velocity > target:
            self.velocity = max(target, self.velocity - 2)
        self.x = min(max(self.x + math.sin(self.heading_radians) * self.velocity, 18), self.field.width - 18)
        self.y = min(max(self.y + math.cos(self.heading_radians) * self.velocity, 18), self.field.height - 18)
        gun_turn = max(-math.radians(20), min(self._gun_turn, math.radians(20)))
        self.gun_heading_radians = (self.gun_heading_radians + gun_turn) % (2 * math.pi)
        self._gun_turn -= gun_turn
        self.gun_turn_remaining = math.degrees(self._gun_turn)
        self.gun_heat = max(0.0, self.gun_heat - self.gun_cooling_rate)
        self.time += 1


class ScriptedDuel:
    """Drives radar, movement and gun through a 1v1 against a scripted enemy."""

    def __init__(self, seed: int = 1) -> None:
        random.seed(seed)
        self.field = BattleField(800.0, 600.0)
        self.robot = FakeRobot(self.field)
        self.radar = DiamondEyes(self.robot, self.field)
        self.move = DiamondWhoosh(self.robot, self.field)
        self.gun = DiamondFist(self.robot, self.field)
        self.gun.add_fire_listener(self.move)
        self.radar.init_round(self.robot)
        self.move.init_round(self.robot)
        self.gun.init_round(self.robot)
        self.enemy_id = 7
        self.ex, self.ey = 600.0, 400.0
        self.eheading = math.radians(90)
        self.evel = 8.0
        self.eenergy = 100.0
        self.egun_heat = 3.0

    def tick(self, enemy_fires: bool = True, energy_override: float | None = None) -> None:
        robot = self.robot
        robot.step()
        bearing = dia_utils.absolute_bearing(Point(self.ex, self.ey), Point(robot.x, robot.y))
        self.eheading = bearing + dia_utils.HALF_PI * (1 if (robot.time // 40) % 2 == 0 else -1)
        self.ex = min(max(self.ex + math.sin(self.eheading) * self.evel, 18), self.field.width - 18)
        self.ey = min(max(self.ey + math.cos(self.eheading) * self.evel, 18), self.field.height - 18)
        self.egun_heat = max(0.0, self.egun_heat - 0.1)
        if enemy_fires and self.egun_heat == 0 and robot.time > 30:
            self.eenergy -= 1.9
            self.egun_heat = 1.38
        energy = self.eenergy if energy_override is None else energy_override
        my_location = Point(robot.x, robot.y)
        scan = ScannedRobotEvent(self.enemy_id, robot.time, Point(self.ex, self.ey), self.eheading, self.evel, energy, my_location.distance(Point(self.ex, self.ey)))
        self.radar.on_scanned_robot(scan)
        self.move.on_scanned_robot(scan)
        self.gun.on_scanned_robot(scan)
        self.move.execute()
        self.gun.execute()
        self.radar.execute()


class DiamondPortTest(unittest.TestCase):
    def test_manifest_and_launcher_use_port_name(self) -> None:
        manifest = json.loads((BOT_DIR / "diamond-port.json").read_text(encoding="utf-8"))
        self.assertEqual("Diamond Port", manifest["name"])
        self.assertEqual("diamond-port", manifest["base"])
        self.assertIn("melee", manifest["gameTypes"])
        launcher = (BOT_DIR / "diamond-port.sh").read_text(encoding="utf-8")
        self.assertIn('"$BOT_DIR/diamond-port.py"', launcher)

    def test_tank_and_legacy_angle_conversions_are_inverse(self) -> None:
        for degrees in (0.0, 45.0, 90.0, 180.0, 270.0, 359.0):
            radians = port.tank_degrees_to_java_radians(degrees)
            self.assertAlmostEqual(degrees, port.java_radians_to_tank_degrees(radians))
        self.assertAlmostEqual(0.0, port.tank_degrees_to_java_radians(90.0))

    def test_set_back_as_front_maps_every_branch_to_tank_commands(self) -> None:
        bot = FakeTankRoyaleBot()  # heading north, Robocode 0
        adapter = port.RobotAdapter(bot)
        cases = {
            math.radians(30): [("turn_left", -30.0), ("forward", 100.0)],
            math.radians(-30): [("turn_left", 30.0), ("forward", 100.0)],
            math.radians(150): [("turn_left", 30.0), ("forward", -100.0)],
            math.radians(-150): [("turn_left", -30.0), ("forward", -100.0)],
        }
        for go_angle, expected in cases.items():
            bot.commands.clear()
            adapter.set_back_as_front(go_angle)
            self.assertEqual(expected, bot.commands, msg=f"go angle {math.degrees(go_angle):.0f}")

    def test_fire_bullet_clamps_power_and_records_acceptance(self) -> None:
        bot = FakeTankRoyaleBot()
        adapter = port.RobotAdapter(bot)
        self.assertTrue(adapter.set_fire_bullet(0.0))
        self.assertEqual([("fire", 0.1)], bot.commands)
        self.assertEqual([0.1], bot.pending)
        bot.fire_result = False
        self.assertFalse(adapter.set_fire_bullet(5.0))
        self.assertEqual(("fire", 3.0), bot.commands[-1])
        self.assertEqual([0.1], bot.pending)

    def test_adapter_converts_remaining_turns_to_robocode_sign(self) -> None:
        bot = FakeTankRoyaleBot()
        bot.turn_remaining = 30.0
        bot.gun_turn_remaining = 0.0
        bot.distance_remaining = 100.0
        adapter = port.RobotAdapter(bot)
        self.assertAlmostEqual(-math.radians(30.0), adapter.turn_remaining_radians)
        self.assertEqual(0.0, adapter.gun_turn_remaining)
        adapter.set_max_velocity(0.0)
        self.assertEqual(0.0, bot.max_speed)
        self.assertEqual(0.0, adapter.max_velocity)

    def test_kd_tree_weighted_nearest_neighbours_match_brute_force(self) -> None:
        rng = random.Random(11)
        weights = [3.0, 1.0, 0.5, 2.0, 4.0]
        tree = KdTree(5)
        tree.set_weights(weights)
        points = [[rng.random() for _ in range(5)] for _ in range(500)]
        for index, point in enumerate(points):
            tree.add_point(point, index)
        query = [0.4, 0.6, 0.2, 0.9, 0.5]

        def weighted(index: int) -> float:
            return sum(((points[index][d] - query[d]) * weights[d]) ** 2 for d in range(5))

        expected = sorted(range(len(points)), key=weighted)[:20]
        result = sorted(entry.value for entry in tree.nearest_neighbor(query, 20))
        self.assertEqual(sorted(expected), result)
        for entry in tree.nearest_neighbor(query, 20):
            self.assertAlmostEqual(weighted(entry.value), entry.distance, places=9)

    def test_kd_tree_size_limit_evicts_oldest_points(self) -> None:
        tree = KdTree(2, size_limit=10)
        for index in range(60):
            tree.add_point([index / 60.0, (index * 7 % 60) / 60.0], index)
        self.assertEqual(10, tree.size())
        values = sorted(entry.value for entry in tree.nearest_neighbor([0.5, 0.5], 10))
        self.assertEqual(list(range(50, 60)), values)

    def test_knn_view_decay_weights_favour_recent_scans(self) -> None:
        view = KnnView(NormalFormula()).set_decay_rate(2.0)

        class Stamp(dia_utils.Timestamped):
            pass

        old = Stamp(0, 10)
        new = Stamp(1, 5)
        entries = [type("E", (), {"value": old, "distance": 0.1})(), type("E", (), {"value": new, "distance": 0.2})()]
        weights = view.get_decay_weights(entries)
        self.assertAlmostEqual(0.5, weights[old])
        self.assertAlmostEqual(1.0, weights[new])

    def test_perceptual_gun_decodes_the_embedded_tree(self) -> None:
        gun = PerceptualGun()
        self.assertEqual(1000, gun._tree.size())
        self.assertEqual(7, len(gun._weights))
        self.assertTrue(all(0.0 <= weight <= 1.0 for weight in gun._weights))

    def test_wall_smoothing_leaves_open_field_headings_alone(self) -> None:
        field = BattleField(800.0, 600.0)
        heading = math.radians(45.0)
        self.assertAlmostEqual(heading, field.wall_smoothing(Point(400, 300), heading, 1, 160.0))
        self.assertNotAlmostEqual(math.radians(90.0), field.wall_smoothing(Point(760, 300), math.radians(90.0), 1, 160.0))

    def test_predictor_accelerates_and_turns_in_robocode_order(self) -> None:
        predictor = MovementPredictor(BattleField(800.0, 600.0))
        state = predictor.predict(RobotState(Point(400, 300), 0.0, 0.0, 0), 1000.0, math.radians(30.0), 8.0, 1, False)
        self.assertAlmostEqual(1.0, state.velocity)
        self.assertAlmostEqual(math.radians(10.0), state.heading)
        self.assertAlmostEqual(300 + math.cos(math.radians(10.0)), state.location.y)
        self.assertEqual(1, state.time)

    def test_wave_position_progresses_from_midair_to_gone(self) -> None:
        field = BattleField(800.0, 600.0)
        predictor = MovementPredictor(field)
        wave = Wave("enemy", Point(100, 300), Point(400, 300), 0, 10, 1.9, math.radians(90), 8.0, 1, field, predictor)
        positions = [wave.check_wave_position(RobotState(Point(400, 300), time=time)) for time in range(10, 40)]
        self.assertEqual(MIDAIR, positions[0])
        self.assertIn(BREAKING_FRONT, positions)
        self.assertIn(BREAKING_CENTER, positions)
        self.assertEqual(GONE, positions[-1])
        self.assertEqual(sorted(positions), positions)
        breaking = [RobotState(Point(400, 300), time=time) for time in range(10, 40) if wave.check_wave_position(RobotState(Point(400, 300), time=time)) in (BREAKING_FRONT, BREAKING_CENTER)]
        intersection = wave.precise_intersection(breaking)
        self.assertIsNotNone(intersection)
        self.assertAlmostEqual(0.0, dia_utils.normal_relative_angle(intersection.angle - wave.abs_bearing), places=6)
        self.assertGreater(intersection.bandwidth, 0.03)

    def test_duel_detects_enemy_fire_surfs_and_shoots(self) -> None:
        duel = ScriptedDuel()
        for _ in range(120):
            duel.tick()
        move_enemy = duel.move.move_data_manager.duel_enemy()
        self.assertIsNotNone(move_enemy)
        self.assertAlmostEqual(1.9, move_enemy.last_bullet_power, places=6)
        self.assertGreater(move_enemy.raw_1v1_shots_fired, 0)
        self.assertEqual(8.0, duel.robot.max_velocity)
        self.assertTrue(duel.robot.moves)
        self.assertGreater(len(duel.robot.fired), 0)
        self.assertTrue(all(1.5 <= power <= 2.95 for power in duel.robot.fired))
        gun_enemy = duel.gun.gun_data_manager.duel_enemy()
        self.assertGreater(gun_enemy.get_wave_breaks(), 9)
        self.assertEqual("Main Gun", duel.gun.current_gun_label)

    def test_deferred_energy_delta_keeps_fire_detection_honest(self) -> None:
        # Tank Royale scans lag our bullet damage by one turn: the hit event
        # arrives at T while the scan at T still shows the old energy.
        duel = ScriptedDuel(seed=2)
        for _ in range(40):
            duel.tick(enemy_fires=False)
        move_enemy = duel.move.move_data_manager.duel_enemy()
        self.assertEqual(0.0, move_enemy.last_bullet_power)
        damage = dia_utils.get_bullet_damage(1.95)
        bullet = BulletRecord(1, 1.95, duel.ex, duel.ey, 0.0, 5)
        # Turn T: hit event, scan unchanged, then the deferred delta.
        duel.move.on_bullet_hit(duel.enemy_id, bullet)
        duel.tick(enemy_fires=False)
        duel.move.apply_energy_delta(duel.enemy_id, -damage)
        # Turn T+1: the scan now carries the damage; no shot must be inferred.
        duel.eenergy -= damage
        duel.tick(enemy_fires=False)
        self.assertEqual(0.0, move_enemy.last_bullet_power)
        # A real shot in the same scan is still seen as its own power.
        duel.move.on_bullet_hit(duel.enemy_id, bullet)
        duel.tick(enemy_fires=False)
        duel.move.apply_energy_delta(duel.enemy_id, -damage)
        duel.eenergy -= damage + 1.9
        duel.tick(enemy_fires=False)
        self.assertAlmostEqual(1.9, move_enemy.last_bullet_power, places=6)


if __name__ == "__main__":
    unittest.main()

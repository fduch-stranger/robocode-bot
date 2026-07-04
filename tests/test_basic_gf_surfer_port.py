import importlib.util
import json
import math
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "ports" / "basic-gf-surfer-port"


def load_port_module():
    module_path = BOT_DIR / "basic-gf-surfer-port.py"
    spec = importlib.util.spec_from_file_location("basic_gf_surfer_port", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["basic_gf_surfer_port"] = module
    spec.loader.exec_module(module)
    return module


port = load_port_module()


class FakeAimBot:
    def __init__(self, fire_result: bool) -> None:
        self.energy = 100.0
        self._last_enemy_velocity = 0.0
        self._move_direction = 1
        self._gun_lateral_direction = 1
        self._gun_waves = []
        self.buffer = [0 for _ in range(port.GUN_BINS)]
        self.fire_result = fire_result
        self.fire_attempts = 0
        self.aim_angle = None

    def _gun_buffer(self, enemy_distance: float, enemy_velocity: float, last_enemy_velocity: float) -> list[int]:
        return self.buffer

    def _gun_most_visited_bearing_offset(self, buffer: list[int], lateral_direction: int) -> float:
        return port.BasicGFSurferPort._gun_most_visited_bearing_offset(buffer, lateral_direction)

    def _turn_gun_to(self, java_angle: float) -> None:
        self.aim_angle = java_angle

    def set_fire(self, firepower: float) -> bool:
        self.fire_attempts += 1
        return self.fire_result


class BasicGFSurferPortTest(unittest.TestCase):
    def test_manifest_and_launcher_use_requested_name(self) -> None:
        manifest = json.loads((BOT_DIR / "basic-gf-surfer-port.json").read_text(encoding="utf-8"))

        self.assertEqual("BasicGFSurfer Port", manifest["name"])
        self.assertEqual("basic-gf-surfer-port", manifest["base"])
        self.assertTrue(os.access(BOT_DIR / "basic-gf-surfer-port.sh", os.X_OK))

    def test_tank_and_legacy_angle_conversions_are_inverse(self) -> None:
        for degrees in (0.0, 45.0, 90.0, 180.0, 270.0, 359.0):
            with self.subTest(degrees=degrees):
                java = port.tank_degrees_to_java_radians(degrees)
                tank = port.java_radians_to_tank_degrees(java)

                self.assertAlmostEqual(degrees, tank)

    def test_project_matches_legacy_coordinate_convention(self) -> None:
        origin = port.Point(100.0, 100.0)

        north = port.project(origin, 0.0, 50.0)
        east = port.project(origin, math.pi / 2.0, 50.0)

        self.assertAlmostEqual(100.0, north.x)
        self.assertAlmostEqual(150.0, north.y)
        self.assertAlmostEqual(150.0, east.x)
        self.assertAlmostEqual(100.0, east.y)

    def test_factor_index_centers_direct_bearing(self) -> None:
        wave = port.EnemyWave(
            fire_location=port.Point(100.0, 100.0),
            fire_time=1,
            bullet_velocity=port.bullet_velocity(1.9),
            direct_angle=0.0,
            distance_traveled=0.0,
            direction=1,
        )

        self.assertEqual(23, port.factor_index(wave, port.Point(100.0, 300.0)))

    def test_surf_direction_uses_own_lateral_velocity(self) -> None:
        self.assertGreater(port.own_lateral_velocity(8.0, 0.0, math.pi / 2.0), 0.0)
        self.assertLess(port.own_lateral_velocity(8.0, 0.0, -math.pi / 2.0), 0.0)

    def test_gun_segment_index_clamps_legacy_bins(self) -> None:
        self.assertEqual((0, 0, 0), port.gun_segment_index(0.0, 0.0, 0.0))
        self.assertEqual((4, 4, 4), port.gun_segment_index(1200.0, 12.0, -12.0))

    def test_gun_current_bin_centers_unchanged_bearing(self) -> None:
        buffer = [0 for _ in range(port.GUN_BINS)]
        wave = port.GunWave(
            gun_location=port.Point(100.0, 100.0),
            target_location=port.Point(100.0, 300.0),
            bullet_power=1.9,
            bearing=0.0,
            lateral_direction=1,
            buffer=buffer,
        )

        self.assertEqual(port.GUN_MIDDLE_BIN, port.BasicGFSurferPort._gun_current_bin(wave))

    def test_rejected_fire_does_not_create_gun_wave(self) -> None:
        bot = FakeAimBot(fire_result=False)

        port.BasicGFSurferPort._aim_and_fire(
            bot,
            port.Point(100.0, 100.0),
            port.Point(100.0, 300.0),
            0.0,
            200.0,
            0.0,
            0.0,
        )

        self.assertEqual(1, bot.fire_attempts)
        self.assertEqual([], bot._gun_waves)

    def test_accepted_fire_creates_one_gun_wave(self) -> None:
        bot = FakeAimBot(fire_result=True)

        port.BasicGFSurferPort._aim_and_fire(
            bot,
            port.Point(100.0, 100.0),
            port.Point(100.0, 300.0),
            0.0,
            200.0,
            0.0,
            0.0,
        )

        self.assertEqual(1, bot.fire_attempts)
        self.assertEqual(1, len(bot._gun_waves))

    def test_gun_lateral_direction_does_not_change_movement_direction(self) -> None:
        bot = FakeAimBot(fire_result=True)
        bot._move_direction = 1

        port.BasicGFSurferPort._aim_and_fire(
            bot,
            port.Point(100.0, 100.0),
            port.Point(100.0, 300.0),
            0.0,
            200.0,
            -8.0,
            math.pi / 2.0,
        )

        self.assertEqual(1, bot._move_direction)
        self.assertEqual(-1, bot._gun_lateral_direction)
        self.assertEqual(-1, bot._gun_waves[0].lateral_direction)


if __name__ == "__main__":
    unittest.main()

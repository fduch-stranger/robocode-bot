import importlib.util
import json
import math
import os
import subprocess
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
    def __init__(self, fire_result: bool, energy: float = 100.0) -> None:
        self.energy = energy
        self._last_enemy_velocity = 0.0
        self._lateral_direction = 1
        self._gun_waves = []
        self._enemy_location = port.Point(100.0, 300.0)
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

    def _gun_current_bin(self, wave: port.GunWave) -> int:
        return port.BasicGFSurferPort._gun_current_bin(wave)

    def set_fire(self, firepower: float) -> bool:
        self.fire_attempts += 1
        return self.fire_result


class FakeMoveBot:
    def __init__(self, direction: float = 0.0) -> None:
        self.direction = direction
        self.commands = []

    def set_turn_left(self, degrees: float) -> None:
        self.commands.append(("turn_left", degrees))

    def set_turn_right(self, degrees: float) -> None:
        self.commands.append(("turn_right", degrees))

    def set_forward(self, distance: float) -> None:
        self.commands.append(("forward", distance))

    def set_back(self, distance: float) -> None:
        self.commands.append(("back", distance))


class FakeRadarBot:
    def __init__(self) -> None:
        self.turn_number = 10
        self._last_scan_turn = -1
        self.commands = []

    def set_turn_radar_left(self, degrees: float) -> None:
        self.commands.append(("radar_left", degrees))


class FakeGunWaveBot:
    def __init__(self) -> None:
        self.turn_number = 10
        self._last_gun_wave_update_turn = -1
        self._enemy_location = port.Point(100.0, 500.0)
        self._gun_waves = [
            port.GunWave(
                gun_location=port.Point(100.0, 100.0),
                target_location=port.Point(100.0, 500.0),
                bullet_power=port.BULLET_POWER,
                bearing=0.0,
                lateral_direction=1,
                buffer=[0 for _ in range(port.GUN_BINS)],
            )
        ]

    def _gun_current_bin(self, wave: port.GunWave) -> int:
        return port.BasicGFSurferPort._gun_current_bin(wave)


class BasicGFSurferPortTest(unittest.TestCase):
    def assertCommandsAlmostEqual(self, expected, actual) -> None:
        self.assertEqual(len(expected), len(actual))
        for expected_command, actual_command in zip(expected, actual, strict=True):
            self.assertEqual(expected_command[0], actual_command[0])
            self.assertAlmostEqual(expected_command[1], actual_command[1])

    def test_manifest_and_launcher_use_requested_name(self) -> None:
        manifest = json.loads((BOT_DIR / "basic-gf-surfer-port.json").read_text(encoding="utf-8"))

        self.assertEqual("BasicGFSurfer Port", manifest["name"])
        self.assertEqual("basic-gf-surfer-port", manifest["base"])
        self.assertTrue(os.access(BOT_DIR / "basic-gf-surfer-port.sh", os.X_OK))

    def test_direct_gui_style_import_bootstraps_venv_dependency_path(self) -> None:
        code = f"""
import importlib.util
import sys
module_path = {str(BOT_DIR / "basic-gf-surfer-port.py")!r}
spec = importlib.util.spec_from_file_location("basic_gf_surfer_direct_bootstrap", module_path)
module = importlib.util.module_from_spec(spec)
sys.modules["basic_gf_surfer_direct_bootstrap"] = module
spec.loader.exec_module(module)
print(module.BasicGFSurferPort.__name__)
"""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)

        result = subprocess.run(
            [sys.executable, "-S", "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual("BasicGFSurferPort", result.stdout.strip())
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)

    def test_direct_gui_bootstrap_reexecs_old_python_to_venv_python(self) -> None:
        venv_python = ROOT / ".venv" / "bin" / "python"

        self.assertTrue(
            port._should_reexec_venv_python(
                venv_python,
                executable="/usr/bin/python3",
                version_info=(3, 9),
            )
        )
        self.assertFalse(
            port._should_reexec_venv_python(
                venv_python,
                executable=str(venv_python),
                version_info=(3, 9),
            )
        )
        self.assertFalse(
            port._should_reexec_venv_python(
                venv_python,
                executable="/usr/bin/python3",
                version_info=(3, 13),
            )
        )

    def test_maintain_radar_searches_before_first_scan(self) -> None:
        bot = FakeRadarBot()

        port.BasicGFSurferPort._maintain_radar(bot)

        self.assertEqual("radar_left", bot.commands[0][0])
        self.assertTrue(math.isinf(bot.commands[0][1]))
        self.assertGreater(bot.commands[0][1], 0.0)

    def test_maintain_radar_does_not_overwrite_recent_scan_lock(self) -> None:
        bot = FakeRadarBot()
        bot._last_scan_turn = bot.turn_number

        port.BasicGFSurferPort._maintain_radar(bot)

        self.assertEqual([], bot.commands)

    def test_maintain_radar_resumes_search_after_stale_scan(self) -> None:
        bot = FakeRadarBot()
        bot._last_scan_turn = bot.turn_number - port.RADAR_LOCK_GRACE_TICKS - 1

        port.BasicGFSurferPort._maintain_radar(bot)

        self.assertEqual("radar_left", bot.commands[0][0])
        self.assertTrue(math.isinf(bot.commands[0][1]))

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

    def test_insufficient_energy_rejected_fire_does_not_track_gun_wave(self) -> None:
        bot = FakeAimBot(fire_result=False, energy=port.BULLET_POWER - 0.1)

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

    def test_set_back_as_front_uses_forward_positive_turn_branch(self) -> None:
        bot = FakeMoveBot()

        port.BasicGFSurferPort._set_back_as_front(bot, port.tank_degrees_to_java_radians(30.0))

        self.assertCommandsAlmostEqual([("turn_left", 30.0), ("forward", 100.0)], bot.commands)

    def test_set_back_as_front_uses_forward_negative_turn_branch(self) -> None:
        bot = FakeMoveBot()

        port.BasicGFSurferPort._set_back_as_front(bot, port.tank_degrees_to_java_radians(-30.0))

        self.assertCommandsAlmostEqual([("turn_left", -30.0), ("forward", 100.0)], bot.commands)

    def test_set_back_as_front_uses_back_negative_turn_branch(self) -> None:
        bot = FakeMoveBot()

        port.BasicGFSurferPort._set_back_as_front(bot, port.tank_degrees_to_java_radians(120.0))

        self.assertCommandsAlmostEqual([("turn_left", -60.0), ("back", 100.0)], bot.commands)

    def test_set_back_as_front_uses_back_positive_turn_branch(self) -> None:
        bot = FakeMoveBot()

        port.BasicGFSurferPort._set_back_as_front(bot, port.tank_degrees_to_java_radians(-120.0))

        self.assertCommandsAlmostEqual([("turn_left", 60.0), ("back", 100.0)], bot.commands)

    def test_gun_and_movement_share_legacy_lateral_direction(self) -> None:
        bot = FakeAimBot(fire_result=True)
        bot._lateral_direction = 1

        port.BasicGFSurferPort._aim_and_fire(
            bot,
            port.Point(100.0, 100.0),
            port.Point(100.0, 300.0),
            0.0,
            200.0,
            -8.0,
            math.pi / 2.0,
        )

        self.assertEqual(-1, bot._lateral_direction)
        self.assertEqual(-1, bot._gun_waves[0].lateral_direction)

    def test_gun_waves_advance_once_per_turn(self) -> None:
        bot = FakeGunWaveBot()

        port.BasicGFSurferPort._update_gun_waves(bot)
        first_distance = bot._gun_waves[0].distance_traveled
        port.BasicGFSurferPort._update_gun_waves(bot)

        self.assertAlmostEqual(port.bullet_velocity(port.BULLET_POWER), first_distance)
        self.assertAlmostEqual(first_distance, bot._gun_waves[0].distance_traveled)

        bot.turn_number += 1
        port.BasicGFSurferPort._update_gun_waves(bot)

        self.assertAlmostEqual(first_distance + port.bullet_velocity(port.BULLET_POWER), bot._gun_waves[0].distance_traveled)

    def test_gun_wave_logs_arrival_and_is_removed(self) -> None:
        bot = FakeGunWaveBot()
        bot._enemy_location = port.Point(100.0, 120.0)
        bot._gun_waves[0].target_location = port.Point(100.0, 120.0)
        buffer = bot._gun_waves[0].buffer

        port.BasicGFSurferPort._update_gun_waves(bot)

        self.assertEqual(1, buffer[port.GUN_MIDDLE_BIN])
        self.assertEqual([], bot._gun_waves)

    def test_round_reset_preserves_battle_persistent_stats(self) -> None:
        bot = port.BasicGFSurferPort()
        bot._state.surf_stats[0] = 7.0
        bot._state.gun_stats[0][0][0][0] = 3
        bot._enemy_waves = [
            port.EnemyWave(
                fire_location=port.Point(100.0, 100.0),
                fire_time=1,
                bullet_velocity=port.bullet_velocity(port.BULLET_POWER),
                direct_angle=0.0,
                distance_traveled=0.0,
                direction=1,
            )
        ]
        bot._gun_waves = [
            port.GunWave(
                gun_location=port.Point(100.0, 100.0),
                target_location=port.Point(100.0, 500.0),
                bullet_power=port.BULLET_POWER,
                bearing=0.0,
                lateral_direction=1,
                buffer=[0 for _ in range(port.GUN_BINS)],
            )
        ]
        bot._last_turn_number = 42
        bot._last_gun_wave_update_turn = 42
        bot._last_scan_turn = 42

        bot.on_round_ended(object())

        self.assertEqual([], bot._enemy_waves)
        self.assertEqual([], bot._gun_waves)
        self.assertEqual(-1, bot._last_turn_number)
        self.assertEqual(-1, bot._last_gun_wave_update_turn)
        self.assertEqual(-1, bot._last_scan_turn)
        self.assertEqual(7.0, bot._state.surf_stats[0])
        self.assertEqual(3, bot._state.gun_stats[0][0][0][0])


if __name__ == "__main__":
    unittest.main()

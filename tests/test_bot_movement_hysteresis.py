import importlib.util
import sys
import unittest
from pathlib import Path
from types import MethodType, ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"


def _load_bot_module(bot_dir: str, file_name: str) -> ModuleType:
    bot_path = BOTS_ROOT / bot_dir / file_name
    module_name = f"_test_movement_{bot_dir.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, bot_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load bot module from {bot_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path[:0] = [str(BOTS_ROOT), str(bot_path.parent)]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
        for path in (str(bot_path.parent), str(BOTS_ROOT)):
            try:
                sys.path.remove(path)
            except ValueError:
                pass
    return module


class FakeMovementTelemetry:
    def __init__(self) -> None:
        self.feints: list[dict[str, object]] = []

    def record_feint(
        self,
        target_id: int,
        mode: str,
        reason: str,
        duration: int,
        move_direction: int,
        near_wall: bool,
        variant: str | None = None,
        turn_scale: float | None = None,
    ) -> None:
        self.feints.append(
            {
                "target": target_id,
                "mode": mode,
                "reason": reason,
                "duration": duration,
                "move_direction": move_direction,
                "near_wall": near_wall,
                "variant": variant,
                "turn_scale": turn_scale,
            }
        )


def _bind_circle_wall_methods(module: ModuleType, bot: SimpleNamespace) -> None:
    bot._near_wall = MethodType(module.CircleStrafer._near_wall, bot)
    bot._projected_wall_position = MethodType(module.CircleStrafer._projected_wall_position, bot)
    bot._wall_risk = MethodType(module.CircleStrafer._wall_risk, bot)


class BotMovementHysteresisTest(unittest.TestCase):
    def test_circle_wall_escape_holds_until_clear_margin(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=module.MOVEMENT_POLICY.wall_margin - 1,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=90.0,
            turn_number=20,
            _move_direction=1,
            _wall_escape_until_turn=-1,
        )
        _bind_circle_wall_methods(module, bot)

        self.assertTrue(module.CircleStrafer._wall_escape_active(bot))
        self.assertEqual(20 + module.MOVEMENT_POLICY.wall_escape_turns, bot._wall_escape_until_turn)

        bot.x = module.MOVEMENT_POLICY.wall_margin + 5
        self.assertTrue(module.CircleStrafer._wall_escape_active(bot))

        bot.x = module.MOVEMENT_POLICY.wall_clear_margin + 5
        self.assertFalse(module.CircleStrafer._wall_escape_active(bot))

    def test_circle_wall_escape_starts_on_projected_wall_risk(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=module.MOVEMENT_POLICY.wall_margin + 20,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=180.0,
            turn_number=24,
            _move_direction=1,
            _wall_escape_until_turn=-1,
        )
        _bind_circle_wall_methods(module, bot)

        self.assertTrue(module.CircleStrafer._wall_escape_active(bot))
        self.assertEqual(24 + module.MOVEMENT_POLICY.wall_escape_turns, bot._wall_escape_until_turn)

    def test_circle_wall_escape_destination_clamps_to_interior_margin(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=60.0,
            y=580.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            _move_direction=1,
        )
        _bind_circle_wall_methods(module, bot)

        destination = module.CircleStrafer._wall_escape_destination(bot)

        self.assertEqual(
            (
                400.0,
                300.0,
            ),
            destination,
        )

    def test_circle_wall_escape_destination_moves_inward_on_projected_risk(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=800.0 - module.MOVEMENT_POLICY.wall_escape_destination_margin,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            _move_direction=1,
        )
        _bind_circle_wall_methods(module, bot)

        destination = module.CircleStrafer._wall_escape_destination(bot)

        self.assertEqual((400.0, 300.0), destination)
        self.assertNotEqual((bot.x, bot.y), destination)

    def test_circle_separation_holds_until_clear_distance(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(turn_number=30, _separation_escape_until_turn=-1)

        self.assertTrue(
            module.CircleStrafer._separation_active(
                bot,
                module.MOVEMENT_POLICY.separation_distance - 1,
                escaping_collision=False,
            )
        )
        self.assertEqual(
            30 + module.MOVEMENT_POLICY.separation_escape_turns,
            bot._separation_escape_until_turn,
        )

        self.assertTrue(
            module.CircleStrafer._separation_active(
                bot,
                module.MOVEMENT_POLICY.separation_distance + 5,
                escaping_collision=False,
            )
        )
        self.assertFalse(
            module.CircleStrafer._separation_active(
                bot,
                module.MOVEMENT_POLICY.separation_clear_distance + 5,
                escaping_collision=False,
            )
        )

    def test_sweep_wall_escape_holds_projected_risk_until_clear_margin(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        bot = SimpleNamespace(
            x=800.0 - module.MOVEMENT_POLICY.wall_margin - 1,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            turn_number=40,
            _move_direction=1,
            _wall_escape_until_turn=-1,
        )
        bot._near_wall = MethodType(module.SweepPressure._near_wall, bot)
        bot._wall_risk = MethodType(module.SweepPressure._wall_risk, bot)

        self.assertTrue(module.SweepPressure._wall_escape_active(bot))
        self.assertEqual(40 + module.MOVEMENT_POLICY.wall_escape_turns, bot._wall_escape_until_turn)

        bot.x = 800.0 - module.MOVEMENT_POLICY.wall_clear_margin - 5
        self.assertTrue(module.SweepPressure._wall_escape_active(bot))

        bot.x = 800.0 - module.MOVEMENT_POLICY.wall_clear_margin - 100
        self.assertFalse(module.SweepPressure._wall_escape_active(bot))

    def test_sweep_wall_escape_also_holds_direct_near_wall_position(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        bot = SimpleNamespace(
            x=400.0,
            y=module.MOVEMENT_POLICY.wall_margin - 1,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            turn_number=50,
            _move_direction=1,
            _wall_escape_until_turn=-1,
        )
        bot._near_wall = MethodType(module.SweepPressure._near_wall, bot)
        bot._wall_risk = MethodType(module.SweepPressure._wall_risk, bot)

        self.assertTrue(module.SweepPressure._wall_escape_active(bot))
        self.assertEqual(50 + module.MOVEMENT_POLICY.wall_escape_turns, bot._wall_escape_until_turn)

        bot.y = module.MOVEMENT_POLICY.wall_margin + 5
        self.assertTrue(module.SweepPressure._wall_escape_active(bot))

        bot.y = module.MOVEMENT_POLICY.wall_clear_margin + 5
        self.assertFalse(module.SweepPressure._wall_escape_active(bot))

    def test_sweep_wall_hit_flip_has_cooldown(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        turns: list[float] = []
        bot = SimpleNamespace(
            turn_number=100,
            _move_direction=1,
            _last_wall_hit_turn=-1000,
            _wall_escape_until_turn=-1,
            set_turn_left=turns.append,
            _log=lambda *args, **kwargs: None,
        )

        module.SweepPressure.on_hit_wall(bot, object())
        self.assertEqual(-1, bot._move_direction)

        bot.turn_number += 2
        module.SweepPressure.on_hit_wall(bot, object())
        self.assertEqual(-1, bot._move_direction)

        bot.turn_number += module.MOVEMENT_POLICY.wall_hit_flip_cooldown + 1
        module.SweepPressure.on_hit_wall(bot, object())
        self.assertEqual(1, bot._move_direction)

    def test_circle_enemy_fire_feint_changes_orbit_shape_without_direction_flip(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        telemetry = FakeMovementTelemetry()
        bot = SimpleNamespace(
            x=400.0,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            turn_number=60,
            enemy_count=1,
            _move_direction=1,
            _last_feint_turn=-1000,
            _feint_until_turn=-1,
            _feint_turn_scale=1.0,
            _evade_until_turn=-1,
            _movement_telemetry=telemetry,
        )
        _bind_circle_wall_methods(module, bot)
        bot._feint_allowed = MethodType(module.CircleStrafer._feint_allowed, bot)

        self.assertTrue(
            module.CircleStrafer._maybe_start_enemy_fire_feint(
                bot,
                target_id=2,
                distance=module.MOVEMENT_POLICY.separation_clear_distance + 50,
                evade_ticks=8,
            )
        )
        self.assertEqual(1, bot._move_direction)
        self.assertEqual(60 + module.MOVEMENT_POLICY.feint_ticks, bot._feint_until_turn)
        self.assertEqual(1, len(telemetry.feints))
        self.assertIn(telemetry.feints[0]["variant"], {"tight", "wide"})

        bot.turn_number += 1
        self.assertFalse(
            module.CircleStrafer._maybe_start_enemy_fire_feint(
                bot,
                target_id=2,
                distance=module.MOVEMENT_POLICY.separation_clear_distance + 50,
                evade_ticks=8,
            )
        )

    def test_circle_enemy_fire_feint_is_blocked_near_separation_distance(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=400.0,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            _move_direction=1,
            turn_number=60,
            enemy_count=1,
        )
        _bind_circle_wall_methods(module, bot)

        self.assertFalse(
            module.CircleStrafer._feint_allowed(
                bot,
                module.MOVEMENT_POLICY.separation_clear_distance - 1,
            )
        )

    def test_circle_enemy_fire_feint_is_blocked_inside_feint_wall_margin(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=module.MOVEMENT_POLICY.feint_wall_margin - 1,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            _move_direction=1,
            turn_number=60,
            enemy_count=1,
        )
        _bind_circle_wall_methods(module, bot)

        self.assertFalse(
            module.CircleStrafer._feint_allowed(
                bot,
                module.MOVEMENT_POLICY.separation_clear_distance + 50,
            )
        )

    def test_circle_enemy_fire_feint_is_blocked_on_projected_wall_risk(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=module.MOVEMENT_POLICY.feint_wall_margin + 10,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=180.0,
            _move_direction=1,
            turn_number=60,
            enemy_count=1,
        )
        _bind_circle_wall_methods(module, bot)

        self.assertFalse(
            module.CircleStrafer._feint_allowed(
                bot,
                module.MOVEMENT_POLICY.separation_clear_distance + 50,
            )
        )

    def test_sweep_enemy_fire_feint_starts_counter_sweep_without_direction_flip(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        telemetry = FakeMovementTelemetry()
        bot = SimpleNamespace(
            x=400.0,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            direction=90.0,
            turn_number=80,
            enemy_count=1,
            _move_direction=-1,
            _last_feint_turn=-1000,
            _feint_until_turn=-1,
            _evade_until_turn=-1,
            _movement_telemetry=telemetry,
        )
        bot._near_wall = MethodType(module.SweepPressure._near_wall, bot)
        bot._wall_risk = MethodType(module.SweepPressure._wall_risk, bot)
        bot._feint_allowed = MethodType(module.SweepPressure._feint_allowed, bot)

        self.assertTrue(module.SweepPressure._maybe_start_enemy_fire_feint(bot, target_id=3, evade_ticks=9))
        self.assertEqual(-1, bot._move_direction)
        self.assertEqual(80 + module.MOVEMENT_POLICY.feint_ticks, bot._feint_until_turn)
        self.assertEqual(1, len(telemetry.feints))
        self.assertEqual("counter_sweep", telemetry.feints[0]["mode"])

        bot.turn_number += 1
        self.assertFalse(module.SweepPressure._maybe_start_enemy_fire_feint(bot, target_id=3, evade_ticks=9))

    def test_sweep_enemy_fire_feint_changes_move_command_for_both_directions(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        for direction in (1, -1):
            with self.subTest(direction=direction):
                bot = SimpleNamespace(
                    turn_number=100,
                    _move_direction=direction,
                    _feint_until_turn=-1,
                    _targets={},
                    target_speed=0.0,
                    turn_rate=0.0,
                    _wall_escape_active=lambda: False,
                )

                module.SweepPressure._move(bot)
                normal_command = (bot.target_speed, bot.turn_rate)

                bot._feint_until_turn = bot.turn_number
                module.SweepPressure._move(bot)
                feint_command = (bot.target_speed, bot.turn_rate)

                self.assertEqual(module.MOVEMENT_POLICY.sweep_speed * direction, feint_command[0])
                self.assertEqual(-module.MOVEMENT_POLICY.sweep_turn_rate, feint_command[1])
                self.assertNotEqual(normal_command, feint_command)

    def test_sweep_enemy_fire_feint_is_blocked_near_wall(self) -> None:
        module = _load_bot_module("sweep-pressure", "sweep-pressure.py")
        bot = SimpleNamespace(
            x=400.0,
            y=module.MOVEMENT_POLICY.wall_clear_margin - 1,
            arena_width=800.0,
            arena_height=600.0,
            direction=0.0,
            enemy_count=1,
            _move_direction=1,
        )
        bot._near_wall = MethodType(module.SweepPressure._near_wall, bot)
        bot._wall_risk = MethodType(module.SweepPressure._wall_risk, bot)

        self.assertFalse(module.SweepPressure._feint_allowed(bot))


if __name__ == "__main__":
    unittest.main()

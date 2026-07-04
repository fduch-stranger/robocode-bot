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


class BotMovementHysteresisTest(unittest.TestCase):
    def test_circle_wall_escape_holds_until_clear_margin(self) -> None:
        module = _load_bot_module("circle-strafer", "circle-strafer.py")
        bot = SimpleNamespace(
            x=module.MOVEMENT_POLICY.wall_margin - 1,
            y=300.0,
            arena_width=800.0,
            arena_height=600.0,
            turn_number=20,
            _wall_escape_until_turn=-1,
        )
        bot._near_wall = MethodType(module.CircleStrafer._near_wall, bot)

        self.assertTrue(module.CircleStrafer._wall_escape_active(bot))
        self.assertEqual(20 + module.MOVEMENT_POLICY.wall_escape_turns, bot._wall_escape_until_turn)

        bot.x = module.MOVEMENT_POLICY.wall_margin + 5
        self.assertTrue(module.CircleStrafer._wall_escape_active(bot))

        bot.x = module.MOVEMENT_POLICY.wall_clear_margin + 5
        self.assertFalse(module.CircleStrafer._wall_escape_active(bot))

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


if __name__ == "__main__":
    unittest.main()

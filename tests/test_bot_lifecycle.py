import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from bot_core.combat import FireUtilityCalibrator, build_fire_utility_context


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"


def _load_bot_module(bot_dir: str, file_name: str) -> ModuleType:
    bot_path = BOTS_ROOT / bot_dir / file_name
    module_name = f"_test_{bot_dir.replace('-', '_')}"
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


class BotLifecycleTest(unittest.TestCase):
    def test_battle_reset_helpers_do_not_require_tick_state(self) -> None:
        cases = [
            ("adaptive-prime", "adaptive-prime.py", "AdaptivePrime"),
            ("chase-lock", "chase-lock.py", "ChaseLock"),
            ("circle-strafer", "circle-strafer.py", "CircleStrafer"),
            ("sweep-pressure", "sweep-pressure.py", "SweepPressure"),
        ]

        for bot_dir, file_name, class_name in cases:
            with self.subTest(bot=bot_dir):
                module = _load_bot_module(bot_dir, file_name)
                bot = getattr(module, class_name)()
                bot._clear_opponent_learning()

    def test_adaptive_hold_does_not_discard_pending_fire_utility(self) -> None:
        module = _load_bot_module("adaptive-prime", "adaptive-prime.py")
        context = build_fire_utility_context(
            "dynamic_cluster",
            420.0,
            0.7,
            solution_quality=0.1,
            model_support=100,
        )
        bot = SimpleNamespace(
            _fire_utility=FireUtilityCalibrator(),
            _fire_utility_context=Mock(return_value=context),
            _fire_utility_telemetry=Mock(),
            _pending_fire_utility=None,
            turn_number=10,
            gun_cooling_rate=0.1,
        )
        target = SimpleNamespace(bot_id=1)
        aim = SimpleNamespace()

        module.AdaptivePrime._record_fire_utility_opportunity(
            bot,
            target,
            420.0,
            0.7,
            aim,
            None,
            can_fire=True,
            reason="ready",
        )
        pending_fire = bot._pending_fire_utility
        bot.turn_number = 11
        module.AdaptivePrime._record_fire_utility_opportunity(
            bot,
            target,
            420.0,
            0.7,
            aim,
            None,
            can_fire=False,
            reason="gun_alignment",
        )

        self.assertIsNotNone(pending_fire)
        self.assertIs(pending_fire, bot._pending_fire_utility)

    def test_adaptive_logs_durable_hit_before_derived_resolution(self) -> None:
        module = _load_bot_module("adaptive-prime", "adaptive-prime.py")
        calls: list[str] = []
        bot = SimpleNamespace(
            _record_enemy_energy_correction=lambda *args: calls.append("energy"),
            _resolve_own_bullet=lambda *args, **kwargs: calls.append("resolve"),
            _fired_bullets=SimpleNamespace(fields_for=lambda bullet_id: {}),
            _fire_telemetry=SimpleNamespace(
                record_bullet_hit_bot=lambda *args: calls.append("durable_hit")
            ),
        )
        event = SimpleNamespace(
            victim_id=1,
            damage=4.0,
            energy=20.0,
            bullet=SimpleNamespace(bullet_id=7, power=1.0),
        )

        module.AdaptivePrime.on_bullet_hit(bot, event)

        self.assertEqual(["energy", "durable_hit", "resolve"], calls)

    def test_adaptive_preserves_pending_wave_when_target_dies_before_fire_callback(self) -> None:
        module = _load_bot_module("adaptive-prime", "adaptive-prime.py")
        bot = SimpleNamespace(
            _targets={7: SimpleNamespace()},
            _gun=Mock(),
            _movement=Mock(),
            _enemy_fire_detector=Mock(),
            _enemy_gun_heat=Mock(),
            _last_enemy_power_prediction={7: 1.0},
            _target_id=7,
            _log=Mock(),
        )

        module.AdaptivePrime.on_bot_death(bot, SimpleNamespace(victim_id=7))

        bot._gun.remove_target.assert_called_once_with(7, preserve_pending=True)
        self.assertIsNone(bot._target_id)


if __name__ == "__main__":
    unittest.main()

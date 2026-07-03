import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


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


if __name__ == "__main__":
    unittest.main()

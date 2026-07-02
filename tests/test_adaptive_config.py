import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


def _load_adaptive_config() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "bots" / "adaptive-prime" / "adaptive_config.py"
    spec = importlib.util.spec_from_file_location("adaptive_prime_config_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load adaptive config from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdaptiveConfigTest(unittest.TestCase):
    def test_anti_surfer_is_force_testable_but_not_live_selectable(self) -> None:
        config = _load_adaptive_config()

        self.assertEqual(
            frozenset({"linear", "traditional_gf", "dynamic_cluster"}),
            config.ADAPTIVE_SELECTABLE_GUN_MODES,
        )
        self.assertEqual(
            frozenset({"linear", "traditional_gf", "dynamic_cluster", "anti_surfer", "displacement"}),
            config.ADAPTIVE_FORCE_GUN_MODES,
        )
        self.assertNotIn("anti_surfer", config.GunPolicy().selectable_modes)


if __name__ == "__main__":
    unittest.main()

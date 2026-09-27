import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from bot_core.gun import AntiSurferPolicy, anti_surfer_config_from_policy
from bot_core.gun.config import GunSelectorConfig
from bot_core.gun.context import TargetHistoryStore
from bot_core.gun.factory import standard_runtime_config
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.anti_surfer.gun import AntiSurferGun
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.gun import DynamicClusterGun
from bot_core.gun.models import GunSample


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"
FEATURES = (0.5,) * 7
QUERY = (0.503,) * 7
OFFSETS = (-0.02, -0.01, 0.0, 0.01, 0.02)


def _load_config(path: Path, env: dict[str, str] | None = None) -> ModuleType:
    sys.path.insert(0, str(BOTS_ROOT))
    module_name = f"_test_anti_surfer_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load config module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with patch.dict(os.environ, env or {}, clear=True):
            spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
        try:
            sys.path.remove(str(BOTS_ROOT))
        except ValueError:
            pass
    return module


def _features(index: int) -> tuple[float, ...]:
    # Cycle through small offsets so no sample sits at the query point and
    # both the old and the recent group share the same distance distribution.
    return tuple(value + OFFSETS[(index * 7) % len(OFFSETS)] for value in FEATURES)


def _fill(gun: DynamicClusterGun, old_count: int, recent_count: int) -> None:
    turn = 0
    for _ in range(old_count):
        turn += 1
        gun.memory.add(GunSample(1, turn, _features(turn), 0.6))
    for _ in range(recent_count):
        turn += 1
        gun.memory.add(GunSample(1, turn, _features(turn), -0.6))
    gun.sequence = turn


class AntiSurferGunTest(unittest.TestCase):
    def test_mode_and_policy_traits(self) -> None:
        gun = AntiSurferGun(AntiSurferGunConfig())
        self.assertEqual(gun.mode, "anti_surfer")
        self.assertEqual(gun.mode_policy.mode, "anti_surfer")
        self.assertEqual(gun.mode_policy.traits.role, "situational")
        self.assertEqual(gun.mode_policy.traits.family, "knn_gf")
        self.assertIn("surfer", gun.mode_policy.traits.strengths)

    def test_recent_samples_dominate_the_anti_surfer_aim(self) -> None:
        anti_surfer = AntiSurferGun(AntiSurferGunConfig(min_samples=4, neighbors=7, decay_half_life=10.0))
        primary = DynamicClusterGun(DynamicClusterGunConfig(min_samples=4))
        _fill(anti_surfer, old_count=60, recent_count=8)
        _fill(primary, old_count=60, recent_count=8)

        anti_surfer_gf = anti_surfer.guess_factor(1, QUERY)
        primary_gf = primary.guess_factor(1, QUERY)
        self.assertIsNotNone(anti_surfer_gf)
        self.assertIsNotNone(primary_gf)
        self.assertLess(anti_surfer_gf, -0.3)
        self.assertGreater(primary_gf, 0.3)

    def test_factory_only_builds_the_gun_when_selectable(self) -> None:
        default_runtime = standard_runtime_config()
        default_modes = {component.mode for component in default_runtime.component_factory(TargetHistoryStore(64))}
        self.assertNotIn("anti_surfer", default_modes)

        selector = GunSelectorConfig(
            selectable_modes=frozenset({"linear", "dynamic_cluster", "anti_surfer"}),
        )
        runtime = standard_runtime_config(selector=selector)
        components = {component.mode: component for component in runtime.component_factory(TargetHistoryStore(64))}
        self.assertIn("anti_surfer", components)
        self.assertIsInstance(components["anti_surfer"], AntiSurferGun)
        self.assertIsNot(components["anti_surfer"].memory, components["dynamic_cluster"].memory)

    def test_config_from_policy_keeps_dynamic_cluster_tuning_and_overrides_knn(self) -> None:
        policy = SimpleNamespace(
            anti_surfer=AntiSurferPolicy(neighbors=5, decay_half_life=40.0, min_samples=12),
            min_visits=90,
            min_switch_score=0.3,
        )
        config = anti_surfer_config_from_policy(policy)
        self.assertIsInstance(config, AntiSurferGunConfig)
        self.assertEqual(config.neighbors, 5)
        self.assertEqual(config.decay_half_life, 40.0)
        self.assertEqual(config.min_samples, 12)
        self.assertEqual(config.min_switch_visits, 60)
        self.assertEqual(config.min_switch_score, 0.08)
        self.assertEqual(config.bandwidth, DynamicClusterGunConfig().bandwidth)

    def test_policy_env_and_validation(self) -> None:
        with patch.dict(os.environ, {"ROBOCODE_TEST_ANTI_SURFER_NEIGHBORS": "9", "ROBOCODE_TEST_ANTI_SURFER_HALF_LIFE": "30"}, clear=True):
            policy = AntiSurferPolicy.from_env("ROBOCODE_TEST")
        self.assertEqual(policy.neighbors, 9)
        self.assertEqual(policy.decay_half_life, 30.0)
        with self.assertRaises(ValueError):
            AntiSurferPolicy(decay_half_life=0.0)

    def test_adaptive_selects_the_gun_by_default(self) -> None:
        config = _load_config(BOTS_ROOT / "adaptive-prime" / "adaptive_config.py")
        self.assertIn("anti_surfer", config.GUN_POLICY.selectable_modes)
        self.assertEqual(config.GUN_POLICY.anti_surfer.neighbors, 7)
        pinned = _load_config(
            BOTS_ROOT / "adaptive-prime" / "adaptive_config.py",
            {"ROBOCODE_ADAPTIVE_GUN_MODE": "anti_surfer"},
        )
        self.assertEqual(pinned.GUN_POLICY.forced_mode, "anti_surfer")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


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
            frozenset({"linear", "traditional_gf", "dynamic_cluster", "displacement"}),
            config.ADAPTIVE_SELECTABLE_GUN_MODES,
        )
        self.assertEqual(
            frozenset({
                "linear",
                "traditional_gf",
                "dynamic_cluster",
                "head_on",
                "anti_surfer",
                "displacement",
            }),
            config.ADAPTIVE_FORCE_GUN_MODES,
        )
        self.assertNotIn("anti_surfer", config.GunPolicy().selectable_modes)
        self.assertIn("displacement", config.GunPolicy().selectable_modes)

    def test_effective_shared_configs_preserve_adaptive_defaults(self) -> None:
        config = _load_adaptive_config()

        self.assertTrue(config.MOVEMENT_FLATTENING_CONFIG.bullet_shadow_enabled)
        self.assertTrue(config.MOVEMENT_FLATTENING_CONFIG.goto_use_expected_waves)
        self.assertEqual(config.MOVEMENT_FLATTENING_CONFIG.goto_expected_wave_min_confidence, 0.62)
        self.assertEqual(config.MINIMUM_RISK_CONFIG.candidate_distances, (220.0, 320.0, 430.0, 560.0))
        self.assertEqual(config.MINIMUM_RISK_CONFIG.field_margin, 105.0)
        self.assertEqual(config.MINIMUM_RISK_CONFIG.destination_switch_risk_ratio, 0.86)
        self.assertEqual(config.ENERGY_DROP_CONFIG, config.EnergyDropConfig())
        self.assertEqual(config.RADAR_CONFIG.lock_rate, 24)
        self.assertEqual(config.RADAR_CONFIG.reacquire_rate, 24)
        self.assertEqual(config.RADAR_CONFIG.reacquire_overscan, 18)

    def test_effective_config_snapshot_is_complete_and_fingerprinted(self) -> None:
        config = _load_adaptive_config()

        snapshot = config.adaptive_config_snapshot()
        encoded = json.dumps(snapshot, sort_keys=True)
        fingerprint = config.adaptive_config_fingerprint(snapshot)

        self.assertIn('"movement_flattening"', encoded)
        self.assertIn('"minimum_risk"', encoded)
        self.assertIn('"duel"', encoded)
        self.assertEqual(len(fingerprint), 16)
        self.assertEqual(fingerprint, config.adaptive_config_fingerprint(snapshot))

        candidate = deepcopy(snapshot)
        candidate["movement"]["wall_margin"] = 91
        self.assertNotEqual(fingerprint, config.adaptive_config_fingerprint(candidate))

        status = config.adaptive_config_status_fields()
        self.assertEqual(status["config_profile"], config.ADAPTIVE_CONFIG_PROFILE)
        self.assertEqual(status["config_fingerprint"], fingerprint)
        self.assertEqual(status["effective_config"], snapshot)
        self.assertEqual(status["selectable_guns"], sorted(config.GUN_POLICY.selectable_modes))

    def test_coarse_movement_controls_are_explicit_environment_overrides(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ROBOCODE_ADAPTIVE_GOTO_SURFING": "0",
                "ROBOCODE_ADAPTIVE_FLATTENER_DIRECTION_CONTROL": "false",
            },
            clear=False,
        ):
            config = _load_adaptive_config()

        self.assertFalse(config.MOVEMENT_POLICY.goto_surfing_active)
        self.assertFalse(config.MOVEMENT_POLICY.flattener_direction_control_active)

    def test_policy_invariants_reject_invalid_experiment_values(self) -> None:
        config = _load_adaptive_config()

        with self.assertRaises(ValueError):
            config.DuelMovementPolicy(critical_distance=500)
        with self.assertRaises(ValueError):
            config.DuelFirepowerPolicy(close_distance=300, near_distance=200)
        with self.assertRaises(ValueError):
            config.TargetPolicy(reacquire_turns=10, drop_lost_turns=9)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"


def _load_config(path: Path, env: dict[str, str] | None = None) -> ModuleType:
    sys.path.insert(0, str(BOTS_ROOT))
    module_name = f"_test_{path.stem}"
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


class BotConfigTest(unittest.TestCase):
    def test_adaptive_traditional_gf_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "adaptive-prime" / "adaptive_config.py"

        default_config = _load_config(path)
        default_policy = default_config.GunPolicy()
        default_traditional_gf = default_policy.traditional_gf
        default_gun_config = TraditionalGfGunConfig()
        default_dynamic_config = DynamicClusterGunConfig()
        self.assertEqual(default_policy.selectable_modes, {"linear", "traditional_gf", "dynamic_cluster"})
        self.assertIsNone(default_policy.forced_mode)
        self.assertIsInstance(default_traditional_gf, default_config.TraditionalGfPolicy)
        self.assertEqual(default_traditional_gf.min_switch_visits, 45)
        self.assertEqual(default_traditional_gf.min_switch_score, 0.10)
        self.assertEqual(default_traditional_gf.global_source_min_switch_visits, 60)
        self.assertEqual(default_traditional_gf.global_source_min_switch_score, 0.16)
        self.assertEqual(default_traditional_gf.trusted_source_min_switch_visits, 32)
        self.assertEqual(default_traditional_gf.trusted_source_min_switch_score, 0.08)
        self.assertGreater(default_traditional_gf.min_switch_visits, default_policy.min_visits)
        self.assertGreater(default_traditional_gf.trusted_source_min_switch_visits, default_policy.min_visits)
        self.assertEqual(default_policy.knn_min_samples, 30)
        self.assertEqual(default_policy.min_visits, 12)
        self.assertEqual(default_policy.min_switch_score, 0.03)
        self.assertEqual(default_policy.primary_over_fallback_margin, 0.02)
        self.assertEqual(default_policy.situational_over_primary_margin, 0.08)
        self.assertEqual(default_policy.primary_slump_visits, 80)
        self.assertEqual(default_policy.primary_slump_score, 0.13)
        self.assertEqual(default_policy.primary_slump_situational_margin, 0.025)
        self.assertEqual(default_policy.primary_confidence_penalty_scale, 0.25)
        self.assertEqual(default_policy.dynamic_cluster.bandwidth_min, default_dynamic_config.bandwidth_min)
        self.assertEqual(default_policy.dynamic_cluster.bandwidth_max, default_dynamic_config.bandwidth_max)
        self.assertEqual(default_policy.dynamic_cluster.centroid_window_bandwidth_scale, 1.0)
        self.assertEqual(default_policy.dynamic_cluster.ambiguous_peak_score_ratio, 0.85)
        self.assertEqual(default_policy.dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertTrue(default_policy.dynamic_cluster.shot_quality_enabled)
        self.assertTrue(default_config.FIRE_POLICY.dynamic_shot_quality_power_scaling_enabled)
        self.assertTrue(default_config.FIRE_POLICY.low_energy_endgame_fire_enabled)
        self.assertEqual(default_config.FIRE_POLICY.energy_margin, 5)
        self.assertEqual(default_traditional_gf.min_samples, default_gun_config.min_samples)
        self.assertEqual(default_traditional_gf.coarse_segment_min_samples, default_gun_config.coarse_segment_min_samples)
        self.assertEqual(default_traditional_gf.coarse_segment_full_weight_samples, default_gun_config.coarse_segment_full_weight_samples)
        self.assertEqual(default_traditional_gf.global_source_centering_factor, default_gun_config.global_source_centering_factor)
        self.assertEqual(default_traditional_gf.coarse_source_centering_factor, default_gun_config.coarse_source_centering_factor)
        self.assertEqual(
            default_traditional_gf.coarse_blend_source_centering_factor,
            default_gun_config.coarse_blend_source_centering_factor,
        )
        self.assertEqual(default_traditional_gf.peak_selection, default_gun_config.peak_selection)
        self.assertEqual(default_gun_config.segment_min_samples, 12)
        self.assertEqual(default_gun_config.global_source_penalty, 0.06)
        self.assertEqual(default_gun_config.smoothing_bins, 1.25)
        self.assertEqual(default_gun_config.decay, 0.985)

        env_config = _load_config(
            path,
            {
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_MIN_SAMPLES": "9",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_COARSE_SEGMENT_MIN_SAMPLES": "8",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_COARSE_SEGMENT_FULL_WEIGHT_SAMPLES": "36",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_GLOBAL_SOURCE_CENTERING_FACTOR": "1.0",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_COARSE_SOURCE_CENTERING_FACTOR": "1.0",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_COARSE_BLEND_SOURCE_CENTERING_FACTOR": "1.0",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_PEAK_SELECTION": "max",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_SMOOTHING_BINS": "0.5",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_SEGMENT_MIN_SAMPLES": "2",
                "ROBOCODE_ADAPTIVE_TRADITIONAL_GF_GLOBAL_SOURCE_PENALTY": "0.5",
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN": "0.08",
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX": "0.22",
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_HIT_WIDTH_SCALE": "1.1",
                "ROBOCODE_ADAPTIVE_DYNAMIC_CENTROID_WINDOW_BANDWIDTH_SCALE": "0.75",
                "ROBOCODE_ADAPTIVE_DYNAMIC_AMBIGUOUS_PEAK_SCORE_RATIO": "0.7",
                "ROBOCODE_ADAPTIVE_DYNAMIC_AMBIGUOUS_PEAK_CENTERING_FACTOR": "0.6",
                "ROBOCODE_ADAPTIVE_DYNAMIC_CONFIDENCE_MATURE_SAMPLES": "90",
                "ROBOCODE_ADAPTIVE_DYNAMIC_TAG_MATCH_BONUS": "0.2",
                "ROBOCODE_ADAPTIVE_DYNAMIC_CONTEXT_WEIGHT_MAX": "1.2",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_GOOD_THRESHOLD": "0.6",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_WEAK_THRESHOLD": "0.4",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_LOW_POWER_SCALE": "0.5",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_POWER_SCALING": "1",
                "ROBOCODE_ADAPTIVE_LOW_ENERGY_ENDGAME_FIRE": "1",
                "ROBOCODE_ADAPTIVE_LOW_ENERGY_ENDGAME_MAX_ENERGY": "6.5",
            },
        )
        env_policy = env_config.GunPolicy()
        env_traditional_gf = env_policy.traditional_gf
        env_dynamic = env_policy.dynamic_cluster
        self.assertEqual(env_traditional_gf.min_samples, 9)
        self.assertEqual(env_traditional_gf.coarse_segment_min_samples, 8)
        self.assertEqual(env_traditional_gf.coarse_segment_full_weight_samples, 36)
        self.assertEqual(env_traditional_gf.global_source_centering_factor, 1.0)
        self.assertEqual(env_traditional_gf.coarse_source_centering_factor, 1.0)
        self.assertEqual(env_traditional_gf.coarse_blend_source_centering_factor, 1.0)
        self.assertEqual(env_traditional_gf.peak_selection, "max")
        self.assertFalse(hasattr(env_traditional_gf, "segment_min_samples"))
        self.assertFalse(hasattr(env_traditional_gf, "global_source_penalty"))
        self.assertFalse(hasattr(env_traditional_gf, "smoothing_bins"))
        self.assertEqual(env_dynamic.bandwidth_min, 0.08)
        self.assertEqual(env_dynamic.bandwidth_max, 0.22)
        self.assertEqual(env_dynamic.bandwidth_hit_width_scale, 1.1)
        self.assertEqual(env_dynamic.centroid_window_bandwidth_scale, 0.75)
        self.assertEqual(env_dynamic.ambiguous_peak_score_ratio, 0.7)
        self.assertEqual(env_dynamic.ambiguous_peak_centering_factor, 0.6)
        self.assertEqual(env_dynamic.confidence_mature_samples, 90)
        self.assertEqual(env_dynamic.tag_match_bonus, 0.2)
        self.assertEqual(env_dynamic.context_weight_max, 1.2)
        self.assertEqual(env_dynamic.shot_quality_good_threshold, 0.6)
        self.assertEqual(env_dynamic.shot_quality_weak_threshold, 0.4)
        self.assertEqual(env_dynamic.shot_quality_low_power_scale, 0.5)
        self.assertTrue(env_config.FIRE_POLICY.dynamic_shot_quality_power_scaling_enabled)
        self.assertTrue(env_config.FIRE_POLICY.low_energy_endgame_fire_enabled)
        self.assertEqual(env_config.FIRE_POLICY.low_energy_endgame_max_energy, 6.5)

        inverted_dynamic_config = _load_config(
            path,
            {
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MIN": "0.5",
                "ROBOCODE_ADAPTIVE_DYNAMIC_BANDWIDTH_MAX": "0.1",
                "ROBOCODE_ADAPTIVE_DYNAMIC_CONTEXT_WEIGHT_MIN": "1.8",
                "ROBOCODE_ADAPTIVE_DYNAMIC_CONTEXT_WEIGHT_MAX": "0.6",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_GOOD_THRESHOLD": "0.2",
                "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_WEAK_THRESHOLD": "0.8",
            },
        )
        inverted_dynamic = inverted_dynamic_config.GunPolicy().dynamic_cluster
        self.assertEqual(inverted_dynamic.bandwidth_min, 0.1)
        self.assertEqual(inverted_dynamic.bandwidth_max, 0.5)
        self.assertEqual(inverted_dynamic.context_weight_min, 0.6)
        self.assertEqual(inverted_dynamic.context_weight_max, 1.8)
        self.assertEqual(inverted_dynamic.shot_quality_weak_threshold, 0.2)
        self.assertEqual(inverted_dynamic.shot_quality_good_threshold, 0.8)

    def test_chase_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "chase-lock" / "chase_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, {"linear", "traditional_gf", "dynamic_cluster"})
        self.assertIsNone(default_config.GunPolicy().forced_mode)
        self.assertFalse(default_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(default_config.GunPolicy().eval_wave_min_interval, 8)
        self.assertEqual(default_config.GunPolicy().knn_min_samples, 30)
        self.assertEqual(default_config.GunPolicy().min_visits, 12)
        self.assertEqual(default_config.GunPolicy().min_switch_score, 0.03)
        self.assertEqual(default_config.GunPolicy().primary_over_fallback_margin, 0.02)
        self.assertEqual(default_config.GunPolicy().situational_over_primary_margin, 0.08)
        self.assertEqual(default_config.GunPolicy().primary_slump_visits, 80)
        self.assertEqual(default_config.GunPolicy().primary_slump_score, 0.13)
        self.assertEqual(default_config.GunPolicy().primary_slump_situational_margin, 0.025)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_visits, 45)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_score, 0.10)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.finish_target_energy, 18)
        self.assertEqual(default_config.TARGET_POLICY.reacquire_turns, 4)
        self.assertEqual(default_config.RADAR_POLICY.gun_search_rate, 18)
        self.assertEqual(default_config.MOVEMENT_POLICY.preferred_min_distance, 320)
        self.assertEqual(default_config.build_fire_gate().config.fire_memory_turns, default_config.FIRE_POLICY.memory_turns)
        self.assertEqual(default_config.build_radar_config().search_rate, default_config.RADAR_POLICY.search_rate)

        env_config = _load_config(
            path,
            {
                "ROBOCODE_CHASE_GUN_MODE": "displacement",
                "ROBOCODE_CHASE_GUN_EVAL": "true",
                "ROBOCODE_CHASE_GUN_EVAL_INTERVAL": "0",
                "ROBOCODE_CHASE_DYNAMIC_AMBIGUOUS_PEAK_CENTERING_FACTOR": "0.55",
            },
        )
        self.assertEqual(env_config.GunPolicy().forced_mode, "displacement")
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 1)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.55)

    def test_circle_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "circle-strafer" / "circle_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, {"linear", "traditional_gf", "dynamic_cluster"})
        self.assertIsNone(default_config.GunPolicy().forced_mode)
        self.assertEqual(default_config.GunPolicy().knn_min_samples, 30)
        self.assertEqual(default_config.GunPolicy().min_visits, 12)
        self.assertEqual(default_config.GunPolicy().min_switch_score, 0.03)
        self.assertEqual(default_config.GunPolicy().primary_over_fallback_margin, 0.02)
        self.assertEqual(default_config.GunPolicy().situational_over_primary_margin, 0.08)
        self.assertEqual(default_config.GunPolicy().primary_slump_visits, 80)
        self.assertEqual(default_config.GunPolicy().primary_slump_score, 0.13)
        self.assertEqual(default_config.GunPolicy().primary_slump_situational_margin, 0.025)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_visits, 45)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_score, 0.10)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.low_energy_max_distance, 180)
        self.assertEqual(default_config.TARGET_POLICY.switch_margin, 110)
        self.assertEqual(default_config.RADAR_POLICY.search_rate, -16)
        self.assertEqual(default_config.MOVEMENT_POLICY.orbit_speed, 8)
        self.assertEqual(default_config.build_fire_gate().config.low_energy_hold, default_config.FIRE_POLICY.low_energy_hold)
        self.assertEqual(default_config.build_radar_config().rescan_interval, default_config.RADAR_POLICY.rescan_interval)

        env_config = _load_config(
            path,
            {
                "ROBOCODE_CIRCLE_GUN_MODE": "anti_surfer",
                "ROBOCODE_CIRCLE_GUN_EVAL": "on",
                "ROBOCODE_CIRCLE_GUN_EVAL_INTERVAL": "bad",
                "ROBOCODE_CIRCLE_DYNAMIC_BANDWIDTH_MIN": "0.4",
                "ROBOCODE_CIRCLE_DYNAMIC_BANDWIDTH_MAX": "0.2",
            },
        )
        self.assertIsNone(env_config.GunPolicy().forced_mode)
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 8)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.bandwidth_min, 0.2)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.bandwidth_max, 0.4)

    def test_sweep_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "sweep-pressure" / "sweep_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, {"linear", "traditional_gf", "dynamic_cluster"})
        self.assertIsNone(default_config.GunPolicy().forced_mode)
        self.assertEqual(default_config.GunPolicy().switch_diagnostics_interval, 24)
        self.assertEqual(default_config.GunPolicy().knn_min_samples, 30)
        self.assertEqual(default_config.GunPolicy().min_visits, 12)
        self.assertEqual(default_config.GunPolicy().min_switch_score, 0.03)
        self.assertEqual(default_config.GunPolicy().primary_over_fallback_margin, 0.02)
        self.assertEqual(default_config.GunPolicy().situational_over_primary_margin, 0.08)
        self.assertEqual(default_config.GunPolicy().primary_slump_visits, 80)
        self.assertEqual(default_config.GunPolicy().primary_slump_score, 0.13)
        self.assertEqual(default_config.GunPolicy().primary_slump_situational_margin, 0.025)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_visits, 45)
        self.assertEqual(default_config.GunPolicy().traditional_gf_min_switch_score, 0.10)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.low_energy_max_distance, 220)
        self.assertEqual(default_config.TARGET_POLICY.force_switch_target_age, 10)
        self.assertEqual(default_config.RADAR_POLICY.reacquire_overscan, 24)
        self.assertEqual(default_config.MOVEMENT_POLICY.sweep_turn_rate, 3.5)
        self.assertEqual(default_config.MOVEMENT_POLICY.wall_lookahead_ticks, 12)
        self.assertEqual(
            default_config.build_fire_gate().config.far_alignment_distance,
            default_config.FIRE_POLICY.far_alignment_distance,
        )

        env_config = _load_config(
            path,
            {
                "ROBOCODE_SWEEP_GUN_MODE": "linear",
                "ROBOCODE_SWEEP_GUN_EVAL": "1",
                "ROBOCODE_SWEEP_GUN_EVAL_INTERVAL": "12",
                "ROBOCODE_SWEEP_DYNAMIC_CONTEXT_WEIGHT_MIN": "1.4",
                "ROBOCODE_SWEEP_DYNAMIC_CONTEXT_WEIGHT_MAX": "0.6",
            },
        )
        self.assertEqual(env_config.GunPolicy().forced_mode, "linear")
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 12)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.context_weight_min, 0.6)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.context_weight_max, 1.4)


if __name__ == "__main__":
    unittest.main()

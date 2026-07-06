import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from bot_core.gun import displacement_config_from_policy, gun_policy_status_fields, selector_config_from_policy
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig


ROOT = Path(__file__).resolve().parents[1]
BOTS_ROOT = ROOT / "bots"
DEFAULT_LIVE_MODES = {"linear", "traditional_gf", "dynamic_cluster", "displacement"}


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
        default_displacement_config = DisplacementGunConfig()
        default_gun_config = TraditionalGfGunConfig()
        default_dynamic_config = DynamicClusterGunConfig()
        self.assertEqual(default_policy.selectable_modes, DEFAULT_LIVE_MODES)
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
        self.assertEqual(default_policy.displacement_min_switch_visits, 60)
        self.assertEqual(default_policy.displacement_min_switch_score, 0.08)
        self.assertTrue(default_policy.displacement_markov_enabled)
        self.assertEqual(default_displacement_config.min_switch_visits, 90)
        self.assertEqual(default_displacement_config.min_switch_score, 0.30)
        self.assertEqual(default_policy.dynamic_cluster.bandwidth_min, default_dynamic_config.bandwidth_min)
        self.assertEqual(default_policy.dynamic_cluster.bandwidth_max, default_dynamic_config.bandwidth_max)
        self.assertEqual(default_policy.dynamic_cluster.centroid_window_bandwidth_scale, 1.0)
        self.assertEqual(default_policy.dynamic_cluster.ambiguous_peak_score_ratio, 0.85)
        self.assertEqual(default_policy.dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertTrue(default_policy.dynamic_cluster.shot_quality_enabled)
        self.assertTrue(default_config.FIRE_POLICY.dynamic_shot_quality_power_scaling_enabled)
        self.assertEqual(default_config.FIRE_POLICY.energy_margin, 5)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_energy, 7)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_firepower, 0.6)
        self.assertEqual(
            default_config.FIRE_GATE.config.last_stand_alignment_degrees,
            default_config.FIRE_POLICY.last_stand_alignment_degrees,
        )
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
        self.assertEqual(default_gun_config.global_source_penalty, 0.10)
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
                "ROBOCODE_ADAPTIVE_DISPLACEMENT_MARKOV": "0",
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
        self.assertFalse(env_policy.displacement_markov_enabled)
        self.assertFalse(displacement_config_from_policy(env_policy).markov_enabled)
        self.assertTrue(env_config.FIRE_POLICY.dynamic_shot_quality_power_scaling_enabled)
        self.assertEqual(env_config.FIRE_GATE.config.last_stand_energy, env_config.FIRE_POLICY.last_stand_energy)

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

    def test_gun_mode_and_set_env_overrides(self) -> None:
        adaptive_path = ROOT / "bots" / "adaptive-prime" / "adaptive_config.py"
        circle_path = ROOT / "bots" / "circle-strafer" / "circle_config.py"

        global_pin_config = _load_config(adaptive_path, {"ROBOCODE_GUN_MODE": "linear"})
        self.assertEqual(global_pin_config.GunPolicy().forced_mode, "linear")

        per_bot_pin_config = _load_config(
            adaptive_path,
            {
                "ROBOCODE_GUN_MODE": "linear",
                "ROBOCODE_ADAPTIVE_GUN_MODE": "traditional_gf",
            },
        )
        self.assertEqual(per_bot_pin_config.GunPolicy().forced_mode, "traditional_gf")

        global_set_config = _load_config(
            adaptive_path,
            {"ROBOCODE_GUN_SET": "dynamic_cluster,traditional_gf"},
        )
        global_set_policy = global_set_config.GunPolicy()
        self.assertEqual(global_set_policy.selectable_modes, {"dynamic_cluster", "traditional_gf"})
        self.assertEqual(selector_config_from_policy(global_set_policy).default_mode, "dynamic_cluster")

        situational_set_config = _load_config(
            adaptive_path,
            {"ROBOCODE_GUN_SET": "anti_surfer,dynamic_cluster"},
        )
        situational_set_policy = situational_set_config.GunPolicy()
        self.assertEqual(situational_set_policy.selectable_modes, {"anti_surfer", "dynamic_cluster"})
        self.assertEqual(selector_config_from_policy(situational_set_policy).default_mode, "dynamic_cluster")

        per_bot_set_config = _load_config(
            adaptive_path,
            {
                "ROBOCODE_GUN_SET": "linear,dynamic_cluster",
                "ROBOCODE_ADAPTIVE_GUN_SET": "traditional_gf",
            },
        )
        self.assertEqual(per_bot_set_config.GunPolicy().selectable_modes, {"traditional_gf"})

        invalid_per_bot_config = _load_config(
            adaptive_path,
            {
                "ROBOCODE_GUN_MODE": "linear",
                "ROBOCODE_ADAPTIVE_GUN_MODE": "unknown_gun",
                "ROBOCODE_GUN_SET": "linear,dynamic_cluster",
                "ROBOCODE_ADAPTIVE_GUN_SET": "unknown_gun",
            },
        )
        self.assertIsNone(invalid_per_bot_config.GunPolicy().forced_mode)
        self.assertEqual(
            invalid_per_bot_config.GunPolicy().selectable_modes,
            DEFAULT_LIVE_MODES,
        )

        unsupported_global_set_config = _load_config(
            circle_path,
            {"ROBOCODE_GUN_SET": "linear,unknown_gun"},
        )
        self.assertEqual(
            unsupported_global_set_config.GunPolicy().selectable_modes,
            DEFAULT_LIVE_MODES,
        )

        forceable_global_set_config = _load_config(
            circle_path,
            {"ROBOCODE_GUN_SET": "linear,anti_surfer"},
        )
        self.assertEqual(forceable_global_set_config.GunPolicy().selectable_modes, {"linear", "anti_surfer"})

    def test_gun_policy_status_fields_report_effective_gun_setup(self) -> None:
        path = ROOT / "bots" / "adaptive-prime" / "adaptive_config.py"
        config = _load_config(
            path,
            {
                "ROBOCODE_ADAPTIVE_GUN_SET": "traditional_gf,dynamic_cluster",
                "ROBOCODE_ADAPTIVE_GUN_MODE": "traditional_gf",
                "ROBOCODE_ADAPTIVE_GUN_EVAL": "1",
            },
        )

        fields = gun_policy_status_fields(config.GunPolicy(), config.ADAPTIVE_FORCE_GUN_MODES)

        self.assertEqual(fields["selectable_guns"], ["dynamic_cluster", "traditional_gf"])
        self.assertEqual(fields["forced_gun"], "traditional_gf")
        self.assertTrue(fields["eval_waves"])
        self.assertIn("anti_surfer", fields["force_guns"])
        self.assertIn("head_on", fields["force_guns"])

    def test_all_bots_can_pin_every_standard_gun(self) -> None:
        cases = (
            ("adaptive-prime", "adaptive_config.py", "ROBOCODE_ADAPTIVE_GUN_MODE", "ADAPTIVE_FORCE_GUN_MODES"),
            ("chase-lock", "chase_config.py", "ROBOCODE_CHASE_GUN_MODE", "CHASE_FORCE_GUN_MODES"),
            ("circle-strafer", "circle_config.py", "ROBOCODE_CIRCLE_GUN_MODE", "CIRCLE_FORCE_GUN_MODES"),
            ("sweep-pressure", "sweep_config.py", "ROBOCODE_SWEEP_GUN_MODE", "SWEEP_FORCE_GUN_MODES"),
        )
        expected_modes = {
            "anti_surfer",
            "displacement",
            "dynamic_cluster",
            "head_on",
            "linear",
            "linear_wall_aware",
            "traditional_gf",
        }

        for bot_dir, file_name, env_name, force_modes_name in cases:
            with self.subTest(bot=bot_dir):
                path = ROOT / "bots" / bot_dir / file_name
                config = _load_config(path)
                self.assertEqual(getattr(config, force_modes_name), expected_modes)
                for mode in expected_modes:
                    forced_config = _load_config(path, {env_name: mode})
                    self.assertEqual(forced_config.GunPolicy().forced_mode, mode)


    def test_chase_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "chase-lock" / "chase_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, DEFAULT_LIVE_MODES)
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
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_visits, 60)
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_score, 0.08)
        self.assertTrue(default_config.GunPolicy().displacement_markov_enabled)
        self.assertEqual(displacement_config_from_policy(default_config.GunPolicy()).min_switch_visits, 60)
        self.assertEqual(displacement_config_from_policy(default_config.GunPolicy()).min_switch_score, 0.08)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.finish_target_energy, 18)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_energy, 7)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_firepower, 0.6)
        self.assertEqual(
            default_config.build_fire_gate().config.last_stand_alignment_degrees,
            default_config.FIRE_POLICY.last_stand_alignment_degrees,
        )
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
                "ROBOCODE_CHASE_DISPLACEMENT_MARKOV": "false",
            },
        )
        self.assertEqual(env_config.GunPolicy().forced_mode, "displacement")
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 1)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.55)
        self.assertFalse(env_config.GunPolicy().displacement_markov_enabled)
        self.assertFalse(displacement_config_from_policy(env_config.GunPolicy()).markov_enabled)

    def test_circle_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "circle-strafer" / "circle_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, DEFAULT_LIVE_MODES)
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
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_visits, 60)
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_score, 0.08)
        self.assertTrue(default_config.GunPolicy().displacement_markov_enabled)
        self.assertTrue(displacement_config_from_policy(default_config.GunPolicy()).markov_enabled)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.low_energy_max_distance, 180)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_firepower, 0.6)
        self.assertEqual(
            default_config.build_fire_gate().config.last_stand_energy,
            default_config.FIRE_POLICY.last_stand_energy,
        )
        self.assertEqual(default_config.TARGET_POLICY.switch_margin, 110)
        self.assertEqual(default_config.RADAR_POLICY.search_rate, -16)
        self.assertEqual(default_config.MOVEMENT_POLICY.orbit_speed, 8)
        self.assertEqual(default_config.MOVEMENT_POLICY.wall_escape_speed, 7)
        self.assertEqual(default_config.MOVEMENT_POLICY.flattener_strafe_offset, 105)
        self.assertGreater(default_config.MOVEMENT_POLICY.wall_clear_margin, default_config.MOVEMENT_POLICY.wall_margin)
        self.assertGreater(
            default_config.MOVEMENT_POLICY.wall_escape_destination_margin,
            default_config.MOVEMENT_POLICY.wall_clear_margin,
        )
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.wall_lookahead_ticks, 8)
        self.assertGreater(default_config.MOVEMENT_POLICY.feint_wall_margin, default_config.MOVEMENT_POLICY.wall_clear_margin)
        self.assertLessEqual(default_config.MOVEMENT_POLICY.wall_escape_turn_limit, 10)
        self.assertGreater(
            default_config.MOVEMENT_POLICY.separation_clear_distance,
            default_config.MOVEMENT_POLICY.separation_distance,
        )
        self.assertGreater(default_config.MOVEMENT_POLICY.flattener_switch_margin, 1.5)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.flattener_switch_cooldown, 30)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.feint_ticks, 8)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.feint_cooldown, 30)
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
                "ROBOCODE_CIRCLE_DISPLACEMENT_MARKOV": "0",
            },
        )
        self.assertEqual(env_config.GunPolicy().forced_mode, "anti_surfer")
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 8)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.bandwidth_min, 0.2)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.bandwidth_max, 0.4)
        self.assertFalse(env_config.GunPolicy().displacement_markov_enabled)

    def test_sweep_gun_policy_defaults_and_env(self) -> None:
        path = ROOT / "bots" / "sweep-pressure" / "sweep_config.py"

        default_config = _load_config(path)
        self.assertEqual(default_config.GunPolicy().selectable_modes, DEFAULT_LIVE_MODES)
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
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_visits, 60)
        self.assertEqual(default_config.GunPolicy().displacement_min_switch_score, 0.08)
        self.assertTrue(default_config.GunPolicy().displacement_markov_enabled)
        self.assertEqual(displacement_config_from_policy(default_config.GunPolicy()).min_switch_score, 0.08)
        self.assertEqual(default_config.GunPolicy().dynamic_cluster.ambiguous_peak_centering_factor, 0.8)
        self.assertEqual(default_config.FIRE_POLICY.low_energy_max_distance, 220)
        self.assertEqual(default_config.FIRE_POLICY.last_stand_firepower, 0.6)
        self.assertEqual(
            default_config.build_fire_gate().config.last_stand_energy,
            default_config.FIRE_POLICY.last_stand_energy,
        )
        self.assertEqual(default_config.TARGET_POLICY.force_switch_target_age, 10)
        self.assertEqual(default_config.RADAR_POLICY.reacquire_overscan, 24)
        self.assertEqual(default_config.MOVEMENT_POLICY.sweep_turn_rate, 3.5)
        self.assertEqual(default_config.MOVEMENT_POLICY.wall_lookahead_ticks, 12)
        self.assertGreater(default_config.MOVEMENT_POLICY.wall_clear_margin, default_config.MOVEMENT_POLICY.wall_margin)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.wall_escape_turns, 10)
        self.assertGreater(default_config.MOVEMENT_POLICY.flattener_switch_margin, 1.5)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.flattener_switch_cooldown, 30)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.wall_hit_flip_cooldown, 8)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.feint_ticks, 8)
        self.assertGreaterEqual(default_config.MOVEMENT_POLICY.feint_cooldown, 30)
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
                "ROBOCODE_SWEEP_DISPLACEMENT_MARKOV": "off",
            },
        )
        self.assertEqual(env_config.GunPolicy().forced_mode, "linear")
        self.assertTrue(env_config.GunPolicy().eval_waves_enabled)
        self.assertEqual(env_config.GunPolicy().eval_wave_min_interval, 12)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.context_weight_min, 0.6)
        self.assertEqual(env_config.GunPolicy().dynamic_cluster.context_weight_max, 1.4)
        self.assertFalse(env_config.GunPolicy().displacement_markov_enabled)


if __name__ == "__main__":
    unittest.main()

import math
import os
import unittest
from types import SimpleNamespace
from typing import cast

from robocode_tank_royale.bot_api import Bot

from bot_core.gun import (
    AimContext,
    AimSolution,
    AimModeSelector,
    FireContext,
    GunDecisionContext,
    GunRuntimeConfig,
    GunScoringConfig,
    GunSelectorConfig,
    GunSystemConfig,
    GunSample,
    GunStats,
    GunSwitchCandidate,
    GunVisit,
    GunWave,
    GunWaveTracker,
    LINEAR_MODE,
    TargetHistoryStore,
    TargetMotion,
    TargetPosition,
    VirtualGunScorer,
    VirtualGunSystem,
    build_fire_context,
    displacement_config_from_policy,
    dynamic_cluster_config_from_policy,
    movement_context_tags,
    should_log_switch_decision,
)
from bot_core.gun.context import build_gun_features
from bot_core.gun.factory import standard_runtime_config
from bot_core.gun.policy import DynamicClusterPolicy, selector_config_from_policy
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.anti_surfer.gun import AntiSurferGun
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.displacement.gun import DisplacementGun, _ReplayBearing
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.gun import DynamicClusterGun
from bot_core.gun.guns.dynamic_cluster.memory import RollingKnnBuffer
from bot_core.gun.guns.traditional_gf.gun import TraditionalGfGun
from bot_core.gun.guns.traditional_gf.profile import GuessFactorProfile
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.gun.features import (
    GUN_FEATURE_COUNT,
    GUN_FEATURE_WEIGHTS,
    feature_distance,
    segment_features,
)
from bot_core.target_snapshot import TargetSnapshot


def fake_bot(**attributes: object) -> Bot:
    return cast(Bot, cast(object, SimpleNamespace(**attributes)))


def make_wave(target_id: int = 1, fire_turn: int = 0, aim_mode: str = "linear") -> GunWave:
    return GunWave(
        source_x=100.0,
        source_y=100.0,
        fire_turn=fire_turn,
        fire_bearing=0.0,
        target_id=target_id,
        bullet_power=2.0,
        bullet_speed=14.0,
        max_escape_angle_positive=30.0,
        max_escape_angle_negative=30.0,
        lateral_direction=1,
        features=(0.0,) * 7,
        segment_key=(0, 0, 0, 0, 0, 0),
        aim_mode=aim_mode,
        aim_guess_factor=None,
        virtual_bearings={"linear": 0.0, "dynamic_cluster": 1.0},
    )


def runtime_config(
    *,
    system: GunSystemConfig | None = None,
    selector: GunSelectorConfig | None = None,
    scoring: GunScoringConfig | None = None,
    min_visits: int = 90,
    min_switch_score: float = 0.30,
    displacement: DisplacementGunConfig | None = None,
    dynamic_cluster: DynamicClusterGunConfig | None = None,
    traditional_gf: TraditionalGfGunConfig | None = None,
    anti_surfer: AntiSurferGunConfig | None = None,
) -> GunRuntimeConfig:
    selector_config = selector or GunSelectorConfig()
    scoring_config = scoring or GunScoringConfig(selectable_modes=selector_config.selectable_modes)
    return standard_runtime_config(
        system=system,
        selector=selector_config,
        scoring=scoring_config,
        min_visits=min_visits,
        min_switch_score=min_switch_score,
        displacement=displacement,
        dynamic_cluster=dynamic_cluster,
        traditional_gf=traditional_gf,
        anti_surfer=anti_surfer,
    )


def system_config(config: GunSystemConfig | None = None) -> GunSystemConfig:
    return config or GunSystemConfig()


def scoring_config(config: GunScoringConfig | GunRuntimeConfig | None = None) -> GunScoringConfig:
    if isinstance(config, GunRuntimeConfig):
        return config.scoring
    return config or GunScoringConfig()


def selector_config(config: GunSelectorConfig | GunRuntimeConfig | None = None) -> GunSelectorConfig:
    if isinstance(config, GunRuntimeConfig):
        return config.selector
    return config or GunSelectorConfig()


def mode_policies(config: GunRuntimeConfig | None = None):
    history = TargetHistoryStore(max_history=80)
    runtime = config or runtime_config()
    return {component.mode: component.mode_policy for component in runtime.component_factory(history)}


def component_config(config: GunRuntimeConfig, mode: str):
    history = TargetHistoryStore(max_history=80)
    for component in config.component_factory(history):
        if component.mode == mode:
            return component.config
    raise AssertionError(f"missing component {mode}")


def make_selector(
    config: GunRuntimeConfig,
    scorer: VirtualGunScorer,
    active_modes: dict[int, str],
    stats: dict[tuple[int, str], GunStats],
    eval_scorer: VirtualGunScorer | None = None,
) -> AimModeSelector:
    return AimModeSelector(selector_config(config), scorer, active_modes, stats, mode_policies(config), eval_scorer)


class GunStatsTest(unittest.TestCase):
    def test_selector_config_from_policy_forwards_all_selector_knobs(self) -> None:
        policy = SimpleNamespace(
            selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
            forced_mode="traditional_gf",
            switch_margin=0.04,
            primary_over_fallback_margin=0.01,
            fallback_over_primary_margin=0.12,
            situational_over_primary_margin=0.07,
            primary_slump_visits=42,
            primary_slump_score=0.11,
            primary_slump_situational_margin=0.02,
            switch_confidence_visits=14,
            switch_confidence_penalty=0.03,
            primary_confidence_penalty_scale=0.5,
            primary_role_bonus=0.06,
            fallback_role_penalty=0.01,
            experimental_role_penalty=0.02,
            context_match_bonus=0.05,
            sample_maturity_bonus=0.025,
            sample_maturity_visits=33,
            eval_influence_min_visits=9,
            eval_influence_weight=0.4,
            eval_influence_cap=0.02,
            eval_visit_credit_ratio=0.25,
        )

        config = selector_config_from_policy(policy)

        self.assertEqual(policy.selectable_modes, config.selectable_modes)
        self.assertEqual(policy.forced_mode, config.forced_mode)
        self.assertAlmostEqual(policy.switch_margin, config.switch_margin)
        self.assertAlmostEqual(policy.fallback_over_primary_margin, config.fallback_over_primary_margin)
        self.assertAlmostEqual(policy.primary_role_bonus, config.primary_role_bonus)
        self.assertAlmostEqual(policy.fallback_role_penalty, config.fallback_role_penalty)
        self.assertAlmostEqual(policy.experimental_role_penalty, config.experimental_role_penalty)
        self.assertAlmostEqual(policy.context_match_bonus, config.context_match_bonus)
        self.assertAlmostEqual(policy.sample_maturity_bonus, config.sample_maturity_bonus)
        self.assertEqual(policy.sample_maturity_visits, config.sample_maturity_visits)
        self.assertEqual(policy.eval_influence_min_visits, config.eval_influence_min_visits)
        self.assertAlmostEqual(policy.eval_influence_weight, config.eval_influence_weight)
        self.assertAlmostEqual(policy.eval_influence_cap, config.eval_influence_cap)
        self.assertAlmostEqual(policy.eval_visit_credit_ratio, config.eval_visit_credit_ratio)

    def test_default_knn_memory_keeps_previous_duel_depth(self) -> None:
        config = DynamicClusterGunConfig()

        self.assertGreaterEqual(config.max_samples_per_target, 900)
        self.assertGreaterEqual(config.max_samples, config.max_samples_per_target)

    def test_standard_runtime_dynamic_cluster_uses_shared_defaults(self) -> None:
        policy = SimpleNamespace(knn_min_samples=30, min_visits=12, min_switch_score=0.03)
        runtime = standard_runtime_config(
            dynamic_cluster=dynamic_cluster_config_from_policy(policy)
        )
        config = component_config(runtime, "dynamic_cluster")

        self.assertEqual(30, config.min_samples)
        self.assertEqual(12, config.min_switch_visits)
        self.assertEqual(0.03, config.min_switch_score)
        self.assertEqual(0.85, config.ambiguous_peak_score_ratio)
        self.assertEqual(0.8, config.ambiguous_peak_centering_factor)

    def test_dynamic_cluster_geometry_overrides(self) -> None:
        names = {
            "ROBOCODE_TEST_DYNAMIC_MIN_SAMPLES": "44",
            "ROBOCODE_TEST_DYNAMIC_NEIGHBORS": "25",
            "ROBOCODE_TEST_DYNAMIC_DECAY_HALF_LIFE": "900",
            "ROBOCODE_TEST_DYNAMIC_MIN_EFFECTIVE_SAMPLES": "18.5",
            "ROBOCODE_TEST_DYNAMIC_GUESS_FACTOR_BINS": "41",
        }
        previous = {name: os.environ.get(name) for name in names}
        try:
            os.environ.update(names)
            dynamic = DynamicClusterPolicy.from_env("ROBOCODE_TEST")
            config = dynamic_cluster_config_from_policy(SimpleNamespace(dynamic_cluster=dynamic))
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertEqual(44, config.min_samples)
        self.assertEqual(25, config.neighbors)
        self.assertEqual(900.0, config.decay_half_life)
        self.assertEqual(18.5, config.min_effective_samples)
        self.assertEqual(41, config.guess_factor_bins)
        self.assertEqual(DynamicClusterGunConfig().bandwidth_min, config.bandwidth_min)
        self.assertEqual(DynamicClusterGunConfig().bandwidth_max, config.bandwidth_max)
        self.assertTrue(config.context_weighting_enabled)
        self.assertTrue(config.shot_quality_enabled)

    def test_displacement_config_from_policy_uses_shared_live_defaults(self) -> None:
        config = displacement_config_from_policy(SimpleNamespace())

        self.assertEqual(60, config.min_switch_visits)
        self.assertEqual(0.08, config.min_switch_score)

        configured = displacement_config_from_policy(
            SimpleNamespace(
                displacement_min_switch_visits=45,
                displacement_min_switch_score=0.06,
            )
        )

        self.assertEqual(45, configured.min_switch_visits)
        self.assertEqual(0.06, configured.min_switch_score)

    def test_runtime_config_maps_to_runtime_components(self) -> None:
        runtime = runtime_config(
            system=GunSystemConfig(max_waves=7, eval_waves_enabled=True, eval_wave_min_interval=3),
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                forced_mode="dynamic_cluster",
            ),
            dynamic_cluster=DynamicClusterGunConfig(min_samples=5),
            traditional_gf=TraditionalGfGunConfig(
                min_switch_visits=12,
                global_source_penalty=0.07,
            ),
        )
        components = runtime.component_factory(TargetHistoryStore(max_history=80))
        by_mode = {component.mode: component for component in components}

        self.assertIn(LINEAR_MODE, by_mode)
        self.assertEqual(7, runtime.system.max_waves)
        self.assertTrue(runtime.system.eval_waves_enabled)
        self.assertEqual(3, runtime.system.eval_wave_min_interval)
        self.assertEqual(frozenset({"linear", "dynamic_cluster"}), runtime.selector.selectable_modes)
        self.assertEqual("dynamic_cluster", runtime.selector.forced_mode)
        self.assertEqual(5, by_mode["dynamic_cluster"].config.min_samples)
        self.assertEqual(12, by_mode["traditional_gf"].mode_policy.min_switch_visits)
        penalty, source = by_mode["traditional_gf"].mode_policy.decision_score_penalty(
            GunDecisionContext("traditional_gf", {"source": "global"})
        )
        self.assertAlmostEqual(0.07, penalty)
        self.assertEqual("global", source)

    def test_runtime_config_uses_shared_traditional_gf_model_defaults(self) -> None:
        traditional_gf = component_config(runtime_config(), "traditional_gf")

        self.assertIsInstance(traditional_gf, TraditionalGfGunConfig)
        self.assertEqual(12, traditional_gf.min_samples)
        self.assertEqual(8, traditional_gf.segment_min_samples)
        self.assertEqual(36, traditional_gf.segment_full_weight_samples)
        self.assertEqual(31, traditional_gf.guess_factor_bins)
        self.assertAlmostEqual(1.25, traditional_gf.smoothing_bins)
        self.assertAlmostEqual(0.985, traditional_gf.decay)
        self.assertAlmostEqual(0.10, traditional_gf.global_source_penalty)
        self.assertAlmostEqual(0.06, traditional_gf.blend_source_penalty)

    def test_gun_feature_tuple_contract_stays_seven_values(self) -> None:
        bot = fake_bot(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 100.0, 300.0, 100.0, 90.0, 8.0, 12)

        features = build_gun_features(bot, target, 200.0, 2.0, TargetMotion())

        self.assertEqual(GUN_FEATURE_COUNT, len(features))
        self.assertEqual(GUN_FEATURE_COUNT, len(GUN_FEATURE_WEIGHTS))

    def test_segment_features_rejects_feature_count_drift(self) -> None:
        self.assertEqual(6, len(segment_features((0.0,) * GUN_FEATURE_COUNT)))

        with self.assertRaises(AssertionError):
            segment_features((0.0,) * (GUN_FEATURE_COUNT + 1))

    def test_feature_distance_rejects_feature_count_drift(self) -> None:
        self.assertEqual(
            0.0,
            feature_distance((0.0,) * GUN_FEATURE_COUNT, (0.0,) * GUN_FEATURE_COUNT),
        )

        with self.assertRaises(AssertionError):
            feature_distance((0.0,) * GUN_FEATURE_COUNT, (0.0,) * (GUN_FEATURE_COUNT + 1))

    def test_direct_runtime_config_bypasses_legacy_gun_config(self) -> None:
        runtime = standard_runtime_config(
            system=GunSystemConfig(max_waves=3),
            dynamic_cluster=DynamicClusterGunConfig(min_samples=4),
        )

        components = runtime.component_factory(TargetHistoryStore(max_history=80))
        by_mode = {component.mode: component for component in components}

        self.assertEqual(3, runtime.system.max_waves)
        self.assertEqual(4, by_mode["dynamic_cluster"].config.min_samples)







    def test_rolling_knn_buffer_keeps_targets_isolated(self) -> None:
        buffer = RollingKnnBuffer(max_samples=5, max_samples_per_target=3)

        for turn in range(4):
            buffer.add(GunSample(1, turn, (0.0,) * 7, -0.5))
        for turn in range(4, 7):
            buffer.add(GunSample(2, turn, (1.0,) * 7, 0.5))

        self.assertEqual(5, buffer.sample_count)
        self.assertEqual(2, buffer.target_sample_count(1))
        self.assertEqual(3, buffer.target_sample_count(2))
        self.assertEqual([2, 3], [sample.turn for sample in buffer.samples_for(1)])
        self.assertEqual([4, 5, 6], [sample.turn for sample in buffer.samples_for(2)])

    def test_rolling_knn_buffer_decays_by_half_life(self) -> None:
        buffer = RollingKnnBuffer(max_samples=10, max_samples_per_target=10)
        buffer.add(GunSample(1, 0, (0.0,) * 7, 0.0))
        buffer.add(GunSample(1, 100, (0.0,) * 7, 0.0))

        self.assertAlmostEqual(0.5, buffer.decayed_weight(buffer.samples_for(1)[0], 100, 100.0))
        self.assertAlmostEqual(1.5, buffer.effective_count(1, 100, 100.0))

    def test_gun_wave_tracker_records_pending_fire_and_trims_old_waves(self) -> None:
        waves = [make_wave(fire_turn=0), make_wave(fire_turn=1)]
        tracker = GunWaveTracker(system_config(GunSystemConfig(max_waves=2)), waves)
        pending = make_wave(fire_turn=2)

        tracker.set_pending_wave(pending)
        recorded = tracker.record_pending_fire()

        self.assertIs(pending, recorded)
        self.assertIsNone(tracker.pending_wave)
        self.assertEqual([1, 2], [wave.fire_turn for wave in waves])

    def test_gun_wave_tracker_clears_matching_pending_wave_on_target_remove(self) -> None:
        waves: list[GunWave] = []
        tracker = GunWaveTracker(system_config(), waves)
        tracker.set_pending_wave(make_wave(target_id=7))

        tracker.remove_target(7)

        self.assertIsNone(tracker.pending_wave)
        self.assertIsNone(tracker.record_pending_fire())
        self.assertEqual([], waves)


    def test_gun_wave_tracker_can_preserve_pending_terminal_fire(self) -> None:
        waves: list[GunWave] = []
        tracker = GunWaveTracker(system_config(), waves)
        pending = make_wave(target_id=7)
        tracker.set_pending_wave(pending)

        tracker.remove_target(7, preserve_pending=True)

        self.assertIs(pending, tracker.pending_wave)
        self.assertIs(pending, tracker.record_pending_fire())
        self.assertEqual([pending], waves)

    def test_gun_wave_visit_position_interpolates_between_scans(self) -> None:
        bot = SimpleNamespace(turn_number=12)
        history = TargetHistoryStore(max_history=80)
        previous = TargetSnapshot(1, 100.0, 140.0, 40.0, 0.0, 0.0, 8)
        current = TargetSnapshot(1, 100.0, 80.0, 80.0, 0.0, 0.0, 12)
        wave = make_wave(fire_turn=0)
        wave.source_x = 0.0
        wave.source_y = 0.0
        wave.bullet_speed = 10.0

        history.observe_target(previous)
        history.observe_target(current)
        visit_x, visit_y, traveled, distance = history.wave_visit_position(bot, wave, current, visit_margin=0)

        self.assertGreater(traveled, 80.0)
        self.assertLess(traveled, 120.0)
        self.assertGreater(visit_x, current.x)
        self.assertLess(visit_x, previous.x)
        self.assertAlmostEqual(distance, traveled, delta=0.1)
        self.assertGreater(visit_y, previous.y)
        self.assertLess(visit_y, current.y)

    def test_virtual_gun_scorer_updates_global_and_segment_scores(self) -> None:
        stats: dict[tuple[int, str], GunStats] = {}
        segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats] = {}
        scorer = VirtualGunScorer(scoring_config(GunScoringConfig(score_alpha=0.5)), stats, segment_stats)
        wave = make_wave()

        scores = scorer.score_virtual_guns(wave, actual_bearing=0.0, target_distance=300.0)

        self.assertEqual(1.0, scores["linear"])
        self.assertEqual(1, stats[(1, "linear")].visits)
        self.assertEqual(1, stats[(1, "linear")].hits)
        self.assertEqual(1, segment_stats[(1, "linear", wave.segment_key)].visits)

    def test_virtual_gun_scorer_reports_mode_confidence(self) -> None:
        stats = {
            (1, "linear"): GunStats(visits=30, hits=9, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=4, hits=4, rolling_score=0.8),
        }
        scorer = VirtualGunScorer(scoring_config(), stats, {})

        score, visits = scorer.mode_confidence(1, "linear")

        self.assertAlmostEqual(0.23, score)
        self.assertEqual(30, visits)
        self.assertEqual((0.0, 0), scorer.mode_confidence(1, None))

    def test_traditional_gf_error_reports_aim_vs_actual_guess_factor(self) -> None:
        wave = make_wave()
        wave.virtual_bearings["traditional_gf"] = 15.0

        error = TraditionalGfGun.error(wave, actual_guess_factor=0.75)

        self.assertIsNotNone(error)
        aim_guess_factor, signed_error, abs_error = error or (0.0, 0.0, 0.0)
        self.assertAlmostEqual(0.5, aim_guess_factor)
        self.assertAlmostEqual(0.25, signed_error)
        self.assertAlmostEqual(0.25, abs_error)











    def test_aim_mode_selector_respects_visit_and_score_thresholds(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(switch_margin=0.05),
            min_visits=2,
            min_switch_score=0.25,
        )
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=1, hits=1, rolling_score=1.0),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        active_modes = {1: "linear"}
        selector = make_selector(config, scorer, active_modes, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0, "dynamic_cluster": 1.0}, None)
        self.assertEqual("linear", selected)
        self.assertEqual("linear", previous)
        self.assertFalse(changed)

        stats[(1, "dynamic_cluster")].visits = 2
        selected, previous, changed = selector.select(1, {"linear": 0.0, "dynamic_cluster": 1.0}, None)
        self.assertEqual("dynamic_cluster", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_aim_mode_selector_reports_blocked_candidate_reasons(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                switch_margin=0.05,
                selectable_modes=frozenset({"linear", "dynamic_cluster", "traditional_gf"}),
            ),
            min_visits=2,
            min_switch_score=0.25,
        )
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=1, hits=1, rolling_score=1.0),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "dynamic_cluster": 1.0}, None)

        self.assertEqual("linear", selected)
        reasons = {candidate.mode: candidate.reason for candidate in candidates}
        self.assertEqual("current", reasons["linear"])
        self.assertEqual("visits", reasons["dynamic_cluster"])
        self.assertEqual("unavailable", reasons["traditional_gf"])

    def test_aim_mode_selector_reports_superseded_candidate_reason(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                switch_margin=0.05,
                selectable_modes=frozenset({"linear", "dynamic_cluster", "traditional_gf"}),
            ),
            min_visits=2,
            min_switch_score=0.1,
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=2, min_switch_score=0.1),
        )
        stats = {
            (1, "linear"): GunStats(visits=10, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=10, hits=3, rolling_score=0.6),
            (1, "traditional_gf"): GunStats(visits=10, hits=2, rolling_score=0.4),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 1.0, "traditional_gf": -1.0},
            None,
        )

        self.assertEqual("dynamic_cluster", selected)
        reasons = {candidate.mode: candidate.reason for candidate in candidates}
        self.assertEqual("selected", reasons["dynamic_cluster"])
        self.assertEqual("superseded", reasons["traditional_gf"])

    def test_aim_mode_selector_uses_displacement_specific_thresholds(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "displacement"}),
                switch_margin=0.03,
            ),
            displacement=DisplacementGunConfig(min_switch_visits=5, min_switch_score=0.10),
        )
        stats = {
            (1, "linear"): GunStats(visits=10, hits=1, rolling_score=0.1),
            (1, "displacement"): GunStats(visits=4, hits=4, rolling_score=0.7),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "displacement": 0.5}, None)
        self.assertEqual("linear", selected)
        self.assertEqual("visits", {candidate.mode: candidate.reason for candidate in candidates}["displacement"])

        stats[(1, "displacement")].visits = 5
        selected, _, changed, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "displacement": 0.5}, None)
        self.assertEqual("displacement", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", {candidate.mode: candidate.reason for candidate in candidates}["displacement"])

    def test_aim_mode_selector_applies_confidence_penalty_to_switch_score(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                switch_margin=0.03,
                switch_confidence_visits=100,
                switch_confidence_penalty=0.10,
                primary_role_bonus=0.0,
                fallback_role_penalty=0.0,
                sample_maturity_bonus=0.0,
            ),
            min_visits=1,
            min_switch_score=0.1,
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=0, rolling_score=0.30),
            (1, "dynamic_cluster"): GunStats(visits=10, hits=0, rolling_score=0.40),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "dynamic_cluster": 0.5}, None)

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("linear", selected)
        self.assertFalse(changed)
        self.assertEqual("margin", by_mode["dynamic_cluster"].reason)
        self.assertAlmostEqual(0.28, by_mode["dynamic_cluster"].raw_score or 0.0)
        self.assertAlmostEqual(0.19, by_mode["dynamic_cluster"].score)
        self.assertAlmostEqual(0.09, by_mode["dynamic_cluster"].confidence_penalty)

        stats[(1, "dynamic_cluster")].visits = 100
        selected, _, changed, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "dynamic_cluster": 0.5}, None)

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["dynamic_cluster"].reason)
        self.assertAlmostEqual(0.0, by_mode["dynamic_cluster"].confidence_penalty)

    def test_aim_mode_selector_penalizes_low_trust_traditional_gf_source(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "traditional_gf"}),
                switch_margin=0.03,
                fallback_role_penalty=0.0,
            ),
            min_visits=1,
            min_switch_score=0.1,
            traditional_gf=TraditionalGfGunConfig(
                min_switch_visits=1,
                min_switch_score=0.1,
                global_source_penalty=0.06,
            ),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=0, rolling_score=0.30),
            (1, "traditional_gf"): GunStats(visits=100, hits=0, rolling_score=0.40),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)
        decision_contexts = {
            "traditional_gf": GunDecisionContext("traditional_gf", {"source": "global", "blend": 0.0})
        }

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 0.5},
            None,
            decision_contexts,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("linear", selected)
        self.assertFalse(changed)
        self.assertEqual("margin", by_mode["traditional_gf"].reason)
        self.assertAlmostEqual(0.28, by_mode["traditional_gf"].raw_score or 0.0)
        self.assertAlmostEqual(0.22, by_mode["traditional_gf"].score)
        self.assertAlmostEqual(0.06, by_mode["traditional_gf"].source_penalty)
        self.assertEqual("global", by_mode["traditional_gf"].decision_source)

    def test_aim_mode_selector_scales_blend_traditional_gf_source_penalty(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "traditional_gf"}),
                switch_margin=0.2,
            ),
            min_visits=1,
            min_switch_score=0.1,
            traditional_gf=TraditionalGfGunConfig(
                min_switch_visits=1,
                min_switch_score=0.1,
                blend_source_penalty=0.10,
            ),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=0, rolling_score=0.30),
            (1, "traditional_gf"): GunStats(visits=100, hits=0, rolling_score=0.40),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        _, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 0.5},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "blend", "blend": 0.75})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertAlmostEqual(0.025, by_mode["traditional_gf"].source_penalty)
        self.assertAlmostEqual(0.255, by_mode["traditional_gf"].score)
        self.assertEqual("blend", by_mode["traditional_gf"].decision_source)

    def test_aim_mode_selector_uses_source_aware_traditional_gf_gates(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "traditional_gf"}),
                switch_margin=0.03,
            ),
            min_visits=1,
            min_switch_score=0.1,
            traditional_gf=TraditionalGfGunConfig(
                min_switch_visits=45,
                min_switch_score=0.10,
                global_source_min_switch_visits=60,
                global_source_min_switch_score=0.16,
                trusted_source_min_switch_visits=32,
                trusted_source_min_switch_score=0.08,
                global_source_penalty=0.0,
            ),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=0, rolling_score=0.05),
            (1, "traditional_gf"): GunStats(visits=40, hits=0, rolling_score=0.20),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        _, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 0.5},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "global", "blend": 0.0})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("visits", by_mode["traditional_gf"].reason)
        self.assertEqual(60, by_mode["traditional_gf"].required_visits)
        self.assertAlmostEqual(0.16, by_mode["traditional_gf"].min_score)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 0.5},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "segment", "blend": 1.0})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["traditional_gf"].reason)
        self.assertEqual(32, by_mode["traditional_gf"].required_visits)
        self.assertAlmostEqual(0.08, by_mode["traditional_gf"].min_score)

    def test_traditional_gf_blend_gates_interpolate_by_source_weight(self) -> None:
        config = TraditionalGfGunConfig(
            min_switch_visits=45,
            min_switch_score=0.10,
            global_source_min_switch_visits=60,
            global_source_min_switch_score=0.16,
            trusted_source_min_switch_visits=32,
            trusted_source_min_switch_score=0.08,
        )
        policy = config.mode_policy()
        context = GunDecisionContext("traditional_gf", {"source": "blend", "blend": 0.5})

        self.assertEqual(46, policy.visits_for(context))
        self.assertAlmostEqual(0.12, policy.score_for(context))

    def test_aim_mode_selector_applies_primary_knn_sample_bonus(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                switch_margin=0.03,
                primary_role_bonus=0.04,
                sample_maturity_bonus=0.04,
                sample_maturity_visits=60,
            ),
            min_visits=1,
            min_switch_score=0.05,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.05),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 0.5},
            None,
            {"dynamic_cluster": GunDecisionContext("dynamic_cluster", {"samples": 60})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["dynamic_cluster"].reason)
        self.assertAlmostEqual(0.08, by_mode["dynamic_cluster"].decision_bonus)

    def test_aim_mode_selector_keeps_linear_situational_for_simple_motion(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                switch_margin=0.03,
                context_match_bonus=0.04,
                fallback_role_penalty=0.03,
            ),
            min_visits=1,
            min_switch_score=0.05,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.05),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)

        _, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 0.5},
            None,
            {"linear": GunDecisionContext("linear", {"context_tags": frozenset({"low_lateral"})})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertAlmostEqual(0.01, by_mode["linear"].decision_bonus)

    def test_aim_mode_selector_uses_primary_over_fallback_margin_and_penalty_scale(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                switch_margin=0.06,
                primary_over_fallback_margin=0.02,
                switch_confidence_visits=100,
                switch_confidence_penalty=0.10,
                primary_confidence_penalty_scale=0.25,
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "dynamic_cluster"): GunStats(visits=10, hits=1, rolling_score=0.06),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 0.5},
            None,
            {"dynamic_cluster": GunDecisionContext("dynamic_cluster", {"samples": 60})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["dynamic_cluster"].reason)
        self.assertAlmostEqual(0.02, by_mode["dynamic_cluster"].margin)
        self.assertAlmostEqual(0.0225, by_mode["dynamic_cluster"].confidence_penalty)

    def test_aim_mode_selector_requires_extra_margin_for_fallback_over_primary(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
                switch_margin=0.08,
                fallback_over_primary_margin=0.18,
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "linear"): GunStats(visits=136, hits=20, rolling_score=0.40),
            (1, "dynamic_cluster"): GunStats(visits=106, hits=16, rolling_score=0.05),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 0.5},
            None,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertFalse(changed)
        self.assertEqual("margin", by_mode["linear"].reason)
        self.assertAlmostEqual(0.18, by_mode["linear"].margin)
        score_advantage = by_mode["linear"].score - by_mode["linear"].current_score
        self.assertGreater(score_advantage, 0.08)
        self.assertLess(score_advantage, 0.18)

        stats[(1, "linear")].rolling_score = 0.50
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)
        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "dynamic_cluster": 0.5},
            None,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("linear", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["linear"].reason)
        self.assertGreater(by_mode["linear"].score - by_mode["linear"].current_score, 0.18)

    def test_aim_mode_selector_requires_extra_margin_for_situational_over_primary(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.03,
                situational_over_primary_margin=0.08,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "traditional_gf"): GunStats(visits=100, hits=16, rolling_score=0.16),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"dynamic_cluster": 0.0, "traditional_gf": 0.5},
            None,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertFalse(changed)
        self.assertEqual("margin", by_mode["traditional_gf"].reason)
        self.assertAlmostEqual(0.08, by_mode["traditional_gf"].margin)

    def test_aim_mode_selector_relaxes_situational_margin_during_primary_slump(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.03,
                situational_over_primary_margin=0.08,
                primary_slump_visits=80,
                primary_slump_score=0.13,
                primary_slump_situational_margin=0.025,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "traditional_gf"): GunStats(visits=100, hits=14, rolling_score=0.14),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"dynamic_cluster": 0.0, "traditional_gf": 0.5},
            None,
            {
                "traditional_gf": GunDecisionContext(
                    "traditional_gf",
                    {"source": "blend", "blend": 1.0, "context_tags": frozenset({"stable_pattern"})},
                )
            },
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["traditional_gf"].reason)
        self.assertAlmostEqual(0.025, by_mode["traditional_gf"].margin)

    def test_aim_mode_selector_uses_segment_score_for_primary_slump(self) -> None:
        segment_key = (1, 1, 1)
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.03,
                situational_over_primary_margin=0.08,
                primary_slump_visits=80,
                primary_slump_score=0.13,
                primary_slump_situational_margin=0.025,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            scoring=GunScoringConfig(
                segment_min_visits=1,
                segment_full_weight_visits=1,
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=50, rolling_score=0.50),
            (1, "traditional_gf"): GunStats(visits=100, hits=14, rolling_score=0.14),
        }
        segment_stats = {
            (1, "dynamic_cluster", segment_key): GunStats(visits=100, hits=10, rolling_score=0.10),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, segment_stats)
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"dynamic_cluster": 0.0, "traditional_gf": 0.5},
            segment_key,
            {
                "traditional_gf": GunDecisionContext(
                    "traditional_gf",
                    {"source": "blend", "blend": 1.0, "context_tags": frozenset({"stable_pattern"})},
                )
            },
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["traditional_gf"].reason)
        self.assertAlmostEqual(0.025, by_mode["traditional_gf"].margin)

    def test_aim_mode_selector_does_not_retain_situational_on_global_source(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.03,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=1,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=1, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=1, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "traditional_gf"): GunStats(visits=100, hits=50, rolling_score=0.50),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "traditional_gf"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"traditional_gf": 0.5, "dynamic_cluster": 0.0},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "global"})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertTrue(changed)
        self.assertEqual("source_degraded", by_mode["traditional_gf"].reason)
        self.assertEqual("selected", by_mode["dynamic_cluster"].reason)

    def test_aim_mode_selector_requires_gates_before_leaving_degraded_situational(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"linear", "dynamic_cluster", "traditional_gf"}),
                switch_margin=0.03,
                primary_role_bonus=0.0,
                fallback_role_penalty=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=30,
            min_switch_score=0.20,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=30, min_switch_score=0.20),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=30, min_switch_score=0.20),
        )
        stats = {
            (1, "linear"): GunStats(visits=0, hits=0, rolling_score=0.0),
            (1, "dynamic_cluster"): GunStats(visits=0, hits=0, rolling_score=0.0),
            (1, "traditional_gf"): GunStats(visits=100, hits=50, rolling_score=0.50),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "traditional_gf"}, stats)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"traditional_gf": 0.5, "dynamic_cluster": 0.0, "linear": 0.0},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "global"})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertFalse(changed)
        self.assertEqual("source_degraded", by_mode["traditional_gf"].reason)
        self.assertEqual("visits", by_mode["dynamic_cluster"].reason)
        self.assertEqual("visits", by_mode["linear"].reason)

    def test_aim_mode_selector_can_use_eval_score_bonus_without_mutating_production_stats(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.02,
                eval_influence_min_visits=18,
                eval_influence_weight=0.25,
                eval_influence_cap=0.035,
                eval_visit_credit_ratio=0.5,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=30,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=30, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=30, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "traditional_gf"): GunStats(visits=5, hits=1, rolling_score=0.10),
        }
        eval_stats = {
            (1, "traditional_gf"): GunStats(visits=60, hits=24, rolling_score=0.32),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        eval_scorer = VirtualGunScorer(scoring_config(config), eval_stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats, eval_scorer)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"dynamic_cluster": 0.0, "traditional_gf": 0.5},
            None,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["traditional_gf"].reason)
        self.assertEqual(5, by_mode["traditional_gf"].visits)
        self.assertEqual(60, by_mode["traditional_gf"].eval_visits)
        self.assertEqual(30, by_mode["traditional_gf"].effective_visits)
        self.assertAlmostEqual(0.035, by_mode["traditional_gf"].eval_score_bonus)
        self.assertEqual(5, stats[(1, "traditional_gf")].visits)

    def test_aim_mode_selector_does_not_credit_eval_scores_before_eval_min_visits(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                selectable_modes=frozenset({"dynamic_cluster", "traditional_gf"}),
                switch_margin=0.02,
                eval_influence_min_visits=18,
                eval_influence_weight=0.25,
                eval_influence_cap=0.035,
                eval_visit_credit_ratio=0.5,
                primary_role_bonus=0.0,
                sample_maturity_bonus=0.0,
                context_match_bonus=0.0,
            ),
            min_visits=30,
            min_switch_score=0.03,
            dynamic_cluster=DynamicClusterGunConfig(min_switch_visits=30, min_switch_score=0.03),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=30, min_switch_score=0.03),
        )
        stats = {
            (1, "dynamic_cluster"): GunStats(visits=100, hits=10, rolling_score=0.10),
            (1, "traditional_gf"): GunStats(visits=5, hits=1, rolling_score=0.10),
        }
        eval_stats = {
            (1, "traditional_gf"): GunStats(visits=17, hits=10, rolling_score=0.40),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        eval_scorer = VirtualGunScorer(scoring_config(config), eval_stats, {})
        selector = make_selector(config, scorer, {1: "dynamic_cluster"}, stats, eval_scorer)

        selected, _, changed, candidates = selector.select_with_diagnostics(
            1,
            {"dynamic_cluster": 0.0, "traditional_gf": 0.5},
            None,
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("dynamic_cluster", selected)
        self.assertFalse(changed)
        self.assertEqual("visits", by_mode["traditional_gf"].reason)
        self.assertEqual(17, by_mode["traditional_gf"].eval_visits)
        self.assertEqual(5, by_mode["traditional_gf"].effective_visits)
        self.assertAlmostEqual(0.0, by_mode["traditional_gf"].eval_score_bonus)

    def test_aim_mode_selector_honors_forced_available_mode(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                forced_mode="traditional_gf",
                selectable_modes=frozenset({"linear", "traditional_gf"}),
            ),
            traditional_gf=TraditionalGfGunConfig(min_switch_visits=999, min_switch_score=0.99),
        )
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "traditional_gf"): GunStats(visits=1, hits=0, rolling_score=0.0),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        active_modes = {1: "linear"}
        selector = make_selector(config, scorer, active_modes, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0, "traditional_gf": 1.0}, None)

        self.assertEqual("traditional_gf", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_aim_mode_selector_prefers_available_selectable_fallback(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                default_mode="dynamic_cluster",
                selectable_modes=frozenset({"anti_surfer", "dynamic_cluster"}),
            ),
        )
        scorer = VirtualGunScorer(scoring_config(config), {}, {})
        selector = make_selector(config, scorer, {1: "linear"}, {})

        selected, previous, changed = selector.select(
            1,
            {"head_on": 0.0, "dynamic_cluster": 1.0},
            None,
        )

        self.assertEqual("dynamic_cluster", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_aim_mode_selector_uses_any_bearing_only_when_no_selectable_available(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                default_mode="dynamic_cluster",
                selectable_modes=frozenset({"anti_surfer", "dynamic_cluster"}),
            ),
        )
        scorer = VirtualGunScorer(scoring_config(config), {}, {})
        selector = make_selector(config, scorer, {}, {})

        selected, previous, changed = selector.select(1, {"head_on": 0.0, "linear": 1.0}, None)

        self.assertIn(selected, {"head_on", "linear"})
        self.assertIsNone(previous)
        self.assertTrue(changed)

    def test_aim_mode_selector_forced_diagnostics_keep_previous_score(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                forced_mode="traditional_gf",
                selectable_modes=frozenset({"linear", "traditional_gf"}),
                switch_confidence_visits=0,
                fallback_role_penalty=0.0,
            ),
        )
        stats = {
            (1, "linear"): GunStats(visits=10, hits=0, rolling_score=0.2),
            (1, "traditional_gf"): GunStats(visits=10, hits=0, rolling_score=0.5),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 1.0},
            None,
        )

        self.assertEqual("traditional_gf", selected)
        candidate = candidates[0]
        self.assertEqual("forced", candidate.reason)
        self.assertAlmostEqual(0.35, candidate.score)
        self.assertAlmostEqual(0.14, candidate.current_score)
        self.assertAlmostEqual(0.35, candidate.raw_score or 0.0)
        self.assertAlmostEqual(0.14, candidate.raw_current_score or 0.0)

    def test_aim_mode_selector_ignores_forced_unavailable_mode(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                forced_mode="dynamic_cluster",
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
            ),
        )
        stats = {(1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2)}
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        active_modes = {1: "linear"}
        selector = make_selector(config, scorer, active_modes, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0}, None)

        self.assertEqual("linear", selected)
        self.assertEqual("linear", previous)
        self.assertFalse(changed)

    def test_aim_mode_selector_unavailable_candidate_reports_historical_score(self) -> None:
        config = runtime_config(selector=GunSelectorConfig(selectable_modes=frozenset({"linear", "dynamic_cluster"})))
        stats = {
            (1, "linear"): GunStats(visits=10, hits=0, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=12, hits=3, rolling_score=0.5),
        }
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        _, _, _, candidates = selector.select_with_diagnostics(1, {"linear": 0.0}, None)

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertFalse(by_mode["dynamic_cluster"].available)
        self.assertEqual("unavailable", by_mode["dynamic_cluster"].reason)
        self.assertEqual(12, by_mode["dynamic_cluster"].visits)
        self.assertAlmostEqual(0.433, by_mode["dynamic_cluster"].score)
        self.assertAlmostEqual(0.008, by_mode["dynamic_cluster"].decision_bonus)
        self.assertAlmostEqual(0.425, by_mode["dynamic_cluster"].raw_score or 0.0)

    def test_aim_mode_selector_allows_forced_non_selectable_mode(self) -> None:
        config = runtime_config(
            selector=GunSelectorConfig(
                forced_mode="displacement",
                selectable_modes=frozenset({"linear", "dynamic_cluster"}),
            ),
        )
        stats = {(1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2)}
        scorer = VirtualGunScorer(scoring_config(config), stats, {})
        selector = make_selector(config, scorer, {1: "linear"}, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0, "displacement": 1.0}, None)

        self.assertEqual("displacement", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_eval_waves_keep_scores_separate_from_switching_stats(self) -> None:
        gun = VirtualGunSystem(runtime_config(system=GunSystemConfig(eval_waves_enabled=True, eval_wave_min_interval=8)))
        bot = SimpleNamespace(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0, turn_number=0)
        target = TargetSnapshot(1, 100.0, 100.0, 300.0, 90.0, 0.0, 0)
        aim = AimSolution(
            predicted_x=target.x,
            predicted_y=target.y,
            gun_bearing=0.0,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            virtual_bearings={"linear": 0.0, "dynamic_cluster": 25.0},
            switch_candidates=(GunSwitchCandidate("linear", True, 0.0, 0.0, 0, 0, 0.0, 0.0, "current"),),
        )

        self.assertTrue(gun.maybe_add_eval_wave(bot, target, 1.0, aim))
        self.assertEqual(1, gun.eval_wave_count)
        self.assertEqual(0, gun.wave_count)

        bot.turn_number = 30
        visits = gun.update_eval_waves(bot, target)

        self.assertEqual(1, len(visits))
        self.assertEqual(0, gun.sample_count)
        self.assertEqual({}, gun.score_summary(target.bot_id, aim.segment_key))
        self.assertIn("linear", gun.eval_score_summary(target.bot_id, aim.segment_key))

    def test_eval_waves_are_disabled_by_default(self) -> None:
        gun = VirtualGunSystem(runtime_config())
        bot = SimpleNamespace(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0, turn_number=0)
        target = TargetSnapshot(1, 100.0, 100.0, 300.0, 90.0, 0.0, 0)
        aim = AimSolution(
            predicted_x=target.x,
            predicted_y=target.y,
            gun_bearing=0.0,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            virtual_bearings={"linear": 0.0},
        )

        self.assertFalse(gun.maybe_add_eval_wave(bot, target, 1.0, aim))
        self.assertEqual(0, gun.eval_wave_count)

    def test_clear_round_state_keeps_active_gun_mode_and_scores(self) -> None:
        gun = VirtualGunSystem(runtime_config())
        gun._active_modes[1] = "dynamic_cluster"
        gun._stats[(1, "dynamic_cluster")] = GunStats(visits=12, rolling_score=0.4)

        gun.clear_round_state()

        self.assertEqual({1: "dynamic_cluster"}, gun._active_modes)
        self.assertIn("dynamic_cluster", gun.score_summary(1, None))

    def test_clear_battle_state_drops_active_gun_mode_and_scores(self) -> None:
        gun = VirtualGunSystem(runtime_config())
        gun._active_modes[1] = "dynamic_cluster"
        gun._stats[(1, "dynamic_cluster")] = GunStats(visits=12, rolling_score=0.4)

        gun.clear_battle_state()

        self.assertEqual({}, gun._active_modes)
        self.assertEqual({}, gun.score_summary(1, None))

    def test_switch_decision_diagnostics_sampling(self) -> None:
        aim = AimSolution(
            predicted_x=100.0,
            predicted_y=100.0,
            gun_bearing=0.0,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            virtual_bearings={"linear": 0.0, "traditional_gf": 1.0},
            switch_candidates=(
                GunSwitchCandidate("linear", True, 0.2, 0.2, 20, 0, 0.0, 0.0, "current"),
                GunSwitchCandidate("traditional_gf", True, 0.26, 0.2, 40, 80, 0.1, 0.05, "visits"),
            ),
        )

        self.assertTrue(should_log_switch_decision(aim, 100, 70, 24))
        self.assertFalse(should_log_switch_decision(aim, 100, 90, 24))

        changed = AimSolution(
            predicted_x=100.0,
            predicted_y=100.0,
            gun_bearing=0.0,
            mode="traditional_gf",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            virtual_bearings={"linear": 0.0, "traditional_gf": 1.0},
            previous_mode="linear",
            mode_changed=True,
            switch_candidates=aim.switch_candidates,
        )
        self.assertTrue(should_log_switch_decision(changed, 100, 99, 24))

    def test_dynamic_cluster_requires_recent_effective_samples(self) -> None:
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=2.0,
                decay_half_life=10.0,
            )
        )
        for turn in range(3):
            gun.memory.add(GunSample(1, turn, (0.0,) * 7, 0.6))
        gun.sequence = 100

        self.assertIsNone(gun.guess_factor(1, (0.0,) * 7))
        gun.sequence = 3
        self.assertIsNotNone(gun.guess_factor(1, (0.0,) * 7))

    def test_fire_context_records_shared_tactical_features(self) -> None:
        bot = SimpleNamespace(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 100.0, 300.0, 300.0, 90.0, 8.0, 12)
        context = build_fire_context(
            bot,
            target,
            distance=250.0,
            firepower=2.0,
            features=(0.5, 2.0 / 3.0, 1.0, 0.0, 0.0, 0.8, 0.25),
            movement_tags=frozenset({"surfer", "nonlinear_mover"}),
        )

        self.assertEqual(frozenset({"surfer", "nonlinear_mover"}), context.movement_tags)
        self.assertAlmostEqual(250.0 / 14.0, context.bullet_flight_time)
        self.assertEqual(1, context.lateral_direction)
        self.assertGreater(context.lateral_direction_confidence, 0.7)
        self.assertEqual(1, context.distance_bucket)
        self.assertEqual(2, context.firepower_bucket)
        self.assertGreaterEqual(context.wall_escape_balance, -1.0)
        self.assertLessEqual(context.wall_escape_balance, 1.0)

    def test_dynamic_cluster_context_weighting_prefers_similar_fire_context(self) -> None:
        current_context = FireContext(
            movement_tags=frozenset({"surfer"}),
            bullet_flight_time=20.0,
            lateral_direction_confidence=1.0,
        )
        matching_context = FireContext(
            movement_tags=frozenset({"surfer"}),
            bullet_flight_time=20.0,
            lateral_direction_confidence=1.0,
        )
        mismatched_context = FireContext(
            movement_tags=frozenset(),
            bullet_flight_time=60.0,
            lateral_direction_confidence=0.0,
            wall_escape_balance=1.0,
        )
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.7, matching_context),
            GunSample(1, 2, (0.0,) * 7, -0.7, mismatched_context),
            GunSample(1, 3, (0.0,) * 7, -0.7, mismatched_context),
        ]
        weighted = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                context_weighting_enabled=True,
                tag_match_bonus=0.5,
                flight_time_mismatch_penalty=0.8,
                wall_escape_mismatch_penalty=0.8,
                lateral_confidence_penalty=0.8,
            )
        )
        unweighted = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                context_weighting_enabled=False,
            )
        )

        weighted_prediction = weighted._prediction_from_samples(1, (0.0,) * 7, samples, current_context, 0.0)
        unweighted_prediction = unweighted._prediction_from_samples(1, (0.0,) * 7, samples, current_context, 0.0)

        self.assertIsNotNone(weighted_prediction)
        self.assertIsNotNone(unweighted_prediction)
        assert weighted_prediction is not None
        assert unweighted_prediction is not None
        self.assertGreater(weighted_prediction.guess_factor, unweighted_prediction.guess_factor)
        self.assertGreater(weighted_prediction.diagnostics["tag_match_ratio"], 0.0)

    def test_dynamic_cluster_centroid_refines_best_bin_guess_factor(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.24),
            GunSample(1, 2, (0.0,) * 7, 0.28),
            GunSample(1, 3, (0.0,) * 7, 0.32),
        ]
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                guess_factor_bins=11,
                bandwidth=0.12,
                context_weighting_enabled=False,
            )
        )

        prediction = gun._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)

        self.assertIsNotNone(prediction)
        assert prediction is not None
        self.assertAlmostEqual(0.2, prediction.diagnostics["best_bin_guess_factor"])
        self.assertGreater(prediction.guess_factor, prediction.diagnostics["best_bin_guess_factor"])
        self.assertLess(prediction.guess_factor, 0.32)
        self.assertIn("peak_margin", prediction.diagnostics)
        self.assertIn("neighbor_agreement", prediction.diagnostics)
        self.assertIn("aim_confidence", prediction.diagnostics)

    def test_dynamic_cluster_effective_bandwidth_uses_radian_hit_width(self) -> None:
        gun = DynamicClusterGun(DynamicClusterGunConfig())
        fire_context = FireContext(positive_escape_angle=0.6, negative_escape_angle=0.6)

        close_bandwidth = gun._effective_bandwidth(100.0, fire_context)
        far_bandwidth = gun._effective_bandwidth(600.0, fire_context)

        self.assertAlmostEqual(gun.config.bandwidth_max, close_bandwidth)
        self.assertAlmostEqual(gun.config.bandwidth_min, far_bandwidth)
        self.assertGreater(close_bandwidth, far_bandwidth)

    def test_dynamic_cluster_visit_diagnostics_use_fire_time_metadata(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.24),
            GunSample(1, 2, (0.0,) * 7, 0.28),
            GunSample(1, 3, (0.0,) * 7, 0.32),
        ]
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                guess_factor_bins=11,
                context_weighting_enabled=False,
            )
        )
        for sample in samples:
            gun.memory.add(sample)
        bot = SimpleNamespace(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 10, 100.0, 300.0, 100.0, 0.0, 0.0)
        bearing = gun.aim(
            AimContext(
                bot=bot,
                target=target,
                distance=200.0,
                firepower=2.0,
                motion=TargetMotion(),
                field_margin=18.0,
                features=(0.0,) * 7,
                segment_key=(0, 0, 0, 0, 0, 0),
                fire_context=FireContext(positive_escape_angle=0.6, negative_escape_angle=0.6),
            )
        )
        self.assertIsNotNone(bearing)
        assert bearing is not None
        fire_time_guess_factor = bearing.metadata["dynamic_cluster"]["selected_guess_factor"]

        for turn in range(4, 12):
            gun.memory.add(GunSample(1, turn, (0.0,) * 7, -0.8))
        wave = make_wave(aim_mode="dynamic_cluster")
        wave.gun_metadata.update(bearing.metadata)
        visit = GunVisit(
            wave=wave,
            actual_bearing=0.0,
            target_distance=200.0,
            guess_factor=-0.8,
            segment_key=wave.segment_key,
        )

        diagnostics = gun.visit_diagnostics(visit)

        self.assertEqual(fire_time_guess_factor, diagnostics["selected_guess_factor"])

    def test_dynamic_cluster_visit_diagnostics_fallback_handles_wave_without_metadata(self) -> None:
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                context_weighting_enabled=False,
            )
        )
        for turn, guess_factor in enumerate((0.2, 0.25, 0.3), start=1):
            gun.memory.add(GunSample(1, turn, (0.0,) * 7, guess_factor))
        wave = make_wave(aim_mode="dynamic_cluster")
        visit = GunVisit(
            wave=wave,
            actual_bearing=0.0,
            target_distance=200.0,
            guess_factor=0.4,
            segment_key=wave.segment_key,
        )

        diagnostics = gun.visit_diagnostics(visit)

        self.assertIn("selected_guess_factor", diagnostics)
        self.assertNotAlmostEqual(0.4, diagnostics["selected_guess_factor"])

    def test_dynamic_cluster_second_peak_ignores_same_peak_adjacent_bins(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.18),
            GunSample(1, 2, (0.0,) * 7, 0.22),
            GunSample(1, 3, (0.0,) * 7, 0.24),
            GunSample(1, 4, (0.0,) * 7, -0.62),
            GunSample(1, 5, (0.0,) * 7, -0.58),
        ]
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=5,
                min_effective_samples=0.0,
                neighbors=5,
                guess_factor_bins=21,
                bandwidth=0.12,
                context_weighting_enabled=False,
            )
        )

        prediction = gun._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)

        self.assertIsNotNone(prediction)
        assert prediction is not None
        self.assertAlmostEqual(0.2, prediction.diagnostics["best_peak_gf"], delta=0.11)
        self.assertAlmostEqual(-0.6, prediction.diagnostics["second_peak_gf"], delta=0.11)
        self.assertGreater(prediction.diagnostics["peak_separation"], 0.6)

    def test_dynamic_cluster_ambiguity_threshold_is_configurable(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.18),
            GunSample(1, 2, (0.0,) * 7, 0.22),
            GunSample(1, 3, (0.0,) * 7, -0.62),
        ]
        strict = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                guess_factor_bins=21,
                bandwidth=0.12,
                ambiguous_peak_score_ratio=0.2,
                context_weighting_enabled=False,
            )
        )
        lenient = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                guess_factor_bins=21,
                bandwidth=0.12,
                ambiguous_peak_score_ratio=0.99,
                context_weighting_enabled=False,
            )
        )

        strict_prediction = strict._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)
        lenient_prediction = lenient._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)

        self.assertIsNotNone(strict_prediction)
        self.assertIsNotNone(lenient_prediction)
        assert strict_prediction is not None
        assert lenient_prediction is not None
        self.assertTrue(strict_prediction.diagnostics["ambiguous_peak"])
        self.assertFalse(lenient_prediction.diagnostics["ambiguous_peak"])

    def test_dynamic_cluster_ambiguous_peak_centering_is_configurable(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.5),
            GunSample(1, 2, (0.0,) * 7, 0.55),
            GunSample(1, 3, (0.0,) * 7, -0.5),
            GunSample(1, 4, (0.0,) * 7, -0.55),
        ]
        uncentered = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=4,
                min_effective_samples=0.0,
                neighbors=4,
                guess_factor_bins=21,
                bandwidth=0.12,
                ambiguous_peak_score_ratio=0.5,
                ambiguous_peak_centering_factor=1.0,
                context_weighting_enabled=False,
            )
        )
        centered = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=4,
                min_effective_samples=0.0,
                neighbors=4,
                guess_factor_bins=21,
                bandwidth=0.12,
                ambiguous_peak_score_ratio=0.5,
                ambiguous_peak_centering_factor=0.5,
                context_weighting_enabled=False,
            )
        )

        uncentered_prediction = uncentered._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)
        centered_prediction = centered._prediction_from_samples(1, (0.0,) * 7, samples, FireContext(), 0.0)

        self.assertIsNotNone(uncentered_prediction)
        self.assertIsNotNone(centered_prediction)
        assert uncentered_prediction is not None
        assert centered_prediction is not None
        self.assertTrue(uncentered_prediction.diagnostics["ambiguous_peak"])
        self.assertTrue(centered_prediction.diagnostics["ambiguous_peak"])
        self.assertAlmostEqual(
            abs(uncentered_prediction.guess_factor) * 0.5,
            abs(centered_prediction.guess_factor),
            delta=0.02,
        )

    def test_dynamic_cluster_context_weight_clamp_is_configurable(self) -> None:
        current = FireContext(
            movement_tags=frozenset({"surfer"}),
            bullet_flight_time=40.0,
            lateral_direction_confidence=1.0,
        )
        sample = FireContext(
            movement_tags=frozenset({"surfer"}),
            bullet_flight_time=40.0,
            lateral_direction_confidence=1.0,
        )
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                tag_match_bonus=1.0,
                context_weight_min=0.4,
                context_weight_max=1.1,
            )
        )

        self.assertAlmostEqual(1.1, gun._context_weight_factor(current, sample))

    def test_dynamic_cluster_centroid_window_scale_is_configurable(self) -> None:
        samples = [
            GunSample(1, 1, (0.0,) * 7, 0.0),
            GunSample(1, 2, (0.0,) * 7, 0.6),
        ]
        weighted_neighbors = [(sample, 1.0) for sample in samples]
        narrow = DynamicClusterGun(
            DynamicClusterGunConfig(
                guess_factor_bins=21,
                centroid_window_bandwidth_scale=1.0,
                centroid_window_bin_scale=1.0,
            )
        )
        wide = DynamicClusterGun(
            DynamicClusterGunConfig(
                guess_factor_bins=21,
                centroid_window_bandwidth_scale=8.0,
                centroid_window_bin_scale=1.0,
            )
        )

        self.assertAlmostEqual(0.0, narrow._local_peak_centroid(0.0, weighted_neighbors, 0.1))
        self.assertGreater(wide._local_peak_centroid(0.0, weighted_neighbors, 0.1), 0.0)

    def test_dynamic_cluster_aim_confidence_maturity_uses_sample_count_not_neighbor_count(self) -> None:
        samples = [GunSample(1, turn, (0.0,) * 7, 0.3) for turn in range(1, 21)]
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                neighbors=3,
                guess_factor_bins=21,
                context_weighting_enabled=False,
                confidence_mature_samples=10,
            )
        )
        fire_context = FireContext(lateral_direction_confidence=1.0)

        prediction = gun._prediction_from_samples(1, (0.0,) * 7, samples, fire_context, 300.0)

        self.assertIsNotNone(prediction)
        assert prediction is not None
        self.assertGreater(prediction.diagnostics["aim_confidence"], 0.5)

    def test_target_history_store_preserves_target_direction(self) -> None:
        history = TargetHistoryStore(max_history=10)
        history.observe_target(
            TargetSnapshot(1, 100.0, 300.0, 100.0, 135.0, 6.0, 12)
        )

        self.assertEqual(135.0, history.history_for(1)[0].direction)

    def test_target_history_store_records_observation_time_velocity_context(self) -> None:
        history = TargetHistoryStore(max_history=10)
        bot = fake_bot(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)

        history.observe_target(
            TargetSnapshot(1, 100.0, 300.0, 100.0, 90.0, 8.0, 12),
            bot,
        )

        position = history.history_for(1)[0]
        self.assertAlmostEqual(8.0, position.observed_lateral_speed)
        self.assertAlmostEqual(0.0, position.observed_advancing_speed)
        self.assertAlmostEqual(0.125, position.observed_wall_margin)
        self.assertAlmostEqual(200.0, position.observed_distance)

    def test_displacement_candidate_scoring_prefers_stored_velocity_context(self) -> None:
        bot = fake_bot(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 100.0, 200.0, 100.0, 90.0, 8.0, 20)
        context = AimContext(
            bot=bot,
            target=target,
            distance=100.0,
            firepower=2.0,
            motion=TargetMotion(),
            field_margin=18.0,
            features=(0.125, 2.0 / 3.0, 1.0, 0.0, 0.0, 1.0, 0.125),
            segment_key=(0,) * 6,
            fire_context=FireContext(lateral_speed_signed=8.0, wall_margin=0.125),
        )
        current = TargetPosition(20, 200.0, 100.0, 8.0, 90.0)
        stored_match = TargetPosition(
            10,
            300.0,
            100.0,
            8.0,
            90.0,
            observed_lateral_speed=8.0,
            observed_advancing_speed=0.0,
            observed_wall_margin=0.125,
        )
        fallback_only = TargetPosition(10, 300.0, 100.0, 8.0, 90.0)
        gun = DisplacementGun(DisplacementGunConfig(min_samples=1), TargetHistoryStore(max_history=10))

        stored_score = gun._candidate_score(context, current, stored_match)
        fallback_score = gun._candidate_score(context, current, fallback_only)

        self.assertLess(stored_score, fallback_score)

    def test_displacement_density_best_selects_cluster_instead_of_between_mode_median(self) -> None:
        gun = DisplacementGun(DisplacementGunConfig(min_samples=1), TargetHistoryStore(max_history=10))
        replays = [
            _ReplayBearing(-30.0, -30.0, 0.1, 1.0),
            _ReplayBearing(-29.0, -29.0, 0.1, 1.0),
            _ReplayBearing(-28.0, -28.0, 0.1, 1.0),
            _ReplayBearing(10.0, 10.0, 0.1, 1.3),
            _ReplayBearing(11.0, 11.0, 0.1, 1.3),
            _ReplayBearing(12.0, 12.0, 0.1, 1.3),
        ]

        selection = gun._density_best_bearing(0.0, replays)

        self.assertGreater(selection.bearing, 5.0)
        self.assertGreater(selection.peak_share, 0.20)

    def test_displacement_rotated_step_preserves_relative_forward_left_motion(self) -> None:
        start = TargetPosition(1, 300.0, 100.0, 8.0, 0.0)
        previous = TargetPosition(1, 300.0, 100.0, 8.0, 0.0)
        next_position = TargetPosition(2, 310.0, 110.0, 8.0, 0.0)

        dx, dy = DisplacementGun._rotated_step(start, previous, next_position, 90.0)

        self.assertAlmostEqual(-10.0, dx)
        self.assertAlmostEqual(10.0, dy)

    def test_displacement_intersect_segment_returns_first_bullet_contact_point(self) -> None:
        context = AimContext(
            bot=fake_bot(x=0.0, y=0.0),
            target=TargetSnapshot(1, 100.0, 100.0, 0.0, 0.0, 0.0, 1),
            distance=100.0,
            firepower=2.0,
            motion=TargetMotion(),
            field_margin=18.0,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
        )

        x, y = DisplacementGun._intersect_segment(
            context,
            100.0,
            0.0,
            0.0,
            200.0,
            0.0,
            30.0,
            10.0,
        )

        self.assertAlmostEqual(150.0, x, places=1)
        self.assertAlmostEqual(0.0, y)

    def test_displacement_gun_replays_history_relative_to_current_heading(self) -> None:
        history = TargetHistoryStore(max_history=32)
        for turn in range(11):
            history.observe_target(
                TargetSnapshot(
                    1,
                    100.0,
                    300.0 + 10.0 * turn,
                    100.0 + 10.0 * turn,
                    0.0,
                    8.0,
                    turn,
                )
            )
        gun = DisplacementGun(DisplacementGunConfig(min_samples=1), history)
        bot = fake_bot(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 100.0, 200.0, 100.0, 90.0, 8.0, 100)
        context = AimContext(
            bot=bot,
            target=target,
            distance=100.0,
            firepower=2.0,
            motion=TargetMotion(),
            field_margin=18.0,
            features=(0.125, 2.0 / 3.0, 1.0, 0.0, 0.0, 1.0, 0.125),
            segment_key=(0,) * 6,
            fire_context=FireContext(lateral_speed_signed=8.0, wall_margin=0.125),
        )

        bearing = gun.aim_bearing(context, 100.0, 2.0, 18.0)

        self.assertIsNotNone(bearing)
        assert bearing is not None
        self.assertGreater(bearing, 35.0)
        self.assertLess(bearing, 60.0)

    def test_displacement_aim_exposes_replay_quality_diagnostics(self) -> None:
        history = TargetHistoryStore(max_history=32)
        bot = fake_bot(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        for turn in range(11):
            history.observe_target(
                TargetSnapshot(
                    1,
                    100.0,
                    300.0 + 10.0 * turn,
                    100.0 + 10.0 * turn,
                    0.0,
                    8.0,
                    turn,
                ),
                bot,
            )
        gun = DisplacementGun(DisplacementGunConfig(min_samples=1), history)
        context = AimContext(
            bot=bot,
            target=TargetSnapshot(1, 100.0, 200.0, 100.0, 90.0, 8.0, 100),
            distance=100.0,
            firepower=2.0,
            motion=TargetMotion(),
            field_margin=18.0,
            features=(0.125, 2.0 / 3.0, 1.0, 0.0, 0.0, 1.0, 0.125),
            segment_key=(0,) * 6,
            fire_context=FireContext(
                lateral_speed_signed=8.0,
                wall_margin=0.125,
                bullet_flight_time=8.0,
                distance_bucket=1,
            ),
        )

        bearing = gun.aim(context)

        self.assertIsNotNone(bearing)
        assert bearing is not None
        metadata = bearing.metadata["displacement"]
        self.assertGreater(metadata["displacement_replay_count"], 0)
        self.assertIn("displacement_peak_share", metadata)
        self.assertIn("displacement_bearing_spread", metadata)
        self.assertEqual(1, metadata["displacement_distance_bucket"])

    def test_movement_context_tags_classify_stable_and_curving_history(self) -> None:
        bot = SimpleNamespace(x=100.0, y=100.0)
        target = TargetSnapshot(1, 100.0, 0.0, 200.0, 100.0, 8.0, 12)
        stable_history = [TargetPosition(turn, 100.0 + 8.0 * turn, 100.0, 8.0) for turn in range(12)]
        stable_tags = movement_context_tags(
            bot,
            target,
            (0.5, 0.7, 0.1, 0.0, 0.0, 0.8, 0.5),
            stable_history,
        )

        self.assertIn("low_lateral", stable_tags)
        self.assertIn("stable_velocity", stable_tags)
        self.assertIn("stable_pattern", stable_tags)
        self.assertNotIn("nonlinear_mover", stable_tags)

        curving_history = [
            TargetPosition(turn, 300.0 + 80.0 * math.cos(turn * 0.45), 300.0 + 80.0 * math.sin(turn * 0.45), 8.0)
            for turn in range(12)
        ]
        curving_tags = movement_context_tags(
            bot,
            target,
            (0.5, 0.7, 0.5, 0.0, 0.2, 0.1, 0.5),
            curving_history,
        )

        self.assertIn("nonlinear_mover", curving_tags)
        self.assertIn("adaptive_mover", curving_tags)
        self.assertIn("surfer", curving_tags)

        stationary_history = [TargetPosition(turn, 250.0, 250.0, 0.0) for turn in range(12)]
        stationary_tags = movement_context_tags(
            bot,
            target,
            (0.5, 0.7, 0.0, 0.0, 0.0, 0.8, 0.5),
            stationary_history,
        )

        self.assertIn("low_lateral", stationary_tags)
        self.assertIn("stable_velocity", stationary_tags)
        self.assertNotIn("nonlinear_mover", stationary_tags)
        self.assertNotIn("adaptive_mover", stationary_tags)
        self.assertNotIn("surfer", stationary_tags)

    def test_dynamic_cluster_context_tags_come_from_movement_history(self) -> None:
        gun = DynamicClusterGun(DynamicClusterGunConfig(min_samples=1, min_effective_samples=1.0))
        gun.memory.add(GunSample(1, 1, (0.0,) * 7, 0.25))
        gun.sequence = 1
        bot = SimpleNamespace(x=100.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(1, 100.0, 0.0, 300.0, 300.0, 8.0, 12)
        context = AimContext(
            bot=bot,
            target=target,
            distance=250.0,
            firepower=2.0,
            motion=TargetMotion(),
            field_margin=18.0,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            movement_tags=frozenset({"nonlinear_mover", "stable_pattern"}),
        )

        bearing = gun.aim(context)

        self.assertIsNotNone(bearing)
        assert bearing is not None
        self.assertEqual(frozenset({"nonlinear_mover"}), bearing.decision_context.data["context_tags"])

    def test_traditional_guess_factor_requires_effective_samples(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                min_samples=3,
                decay=0.5,
            )
        )

        gun.record(1, 1.0)
        gun.record(1, 1.0)

        self.assertIsNone(gun.guess_factor(1))

    def test_traditional_guess_factor_decays_old_visits(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                smoothing_bins=0.75,
                decay=0.5,
            )
        )

        for _ in range(5):
            gun.record(1, 1.0)
        self.assertGreater(gun.guess_factor(1), 0.0)

        for _ in range(8):
            gun.record(1, -1.0)

        self.assertLess(gun.guess_factor(1), 0.0)

    def test_traditional_guess_factor_falls_back_to_global_until_segment_ready(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                segment_min_samples=3,
                segment_full_weight_samples=3,
                smoothing_bins=0.75,
            )
        )
        segment_key = (1, 1, 1)

        for _ in range(5):
            gun.record(1, 1.0)
        gun.record(1, -1.0, segment_key)

        self.assertGreater(gun.guess_factor(1, segment_key), 0.0)

    def test_traditional_guess_factor_uses_segment_profile_when_ready(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                segment_min_samples=2,
                segment_full_weight_samples=2,
                smoothing_bins=0.75,
            )
        )
        left_segment = (1, 1, 1)
        right_segment = (2, 1, 1)

        for _ in range(4):
            gun.record(1, 1.0, left_segment)
            gun.record(1, -1.0, right_segment)

        self.assertGreater(gun.guess_factor(1, left_segment), 0.0)
        self.assertLess(gun.guess_factor(1, right_segment), 0.0)

    def test_traditional_guess_factor_limits_extreme_aim_tail(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                min_samples=1,
                segment_min_samples=0,
                max_aim_guess_factor=0.87,
            )
        )
        gun.record(1, 1.0)
        gun.record(2, -1.0)

        positive = gun.diagnostics(1)
        negative = gun.diagnostics(2)
        self.assertIsNotNone(positive)
        self.assertIsNotNone(negative)
        assert positive is not None
        assert negative is not None
        self.assertAlmostEqual(1.0, positive.global_guess_factor)
        self.assertAlmostEqual(0.87, positive.selected_guess_factor)
        self.assertAlmostEqual(-1.0, negative.global_guess_factor)
        self.assertAlmostEqual(-0.87, negative.selected_guess_factor)

    def test_traditional_guess_factor_reports_segment_diagnostics(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                segment_min_samples=2,
                segment_full_weight_samples=6,
                smoothing_bins=0.75,
            )
        )
        segment_key = (1, 1, 1)

        for _ in range(4):
            gun.record(1, 1.0)
        gun.record(1, -1.0, segment_key)
        fallback = gun.diagnostics(1, segment_key)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual("global", fallback.source)
        self.assertIsNone(fallback.segment_guess_factor)
        self.assertGreater(fallback.global_guess_factor, 0.0)

        for _ in range(4):
            gun.record(1, -1.0, segment_key)
        segmented = gun.diagnostics(1, segment_key)
        self.assertIsNotNone(segmented)
        assert segmented is not None
        self.assertEqual("blend", segmented.source)
        self.assertIsNotNone(segmented.segment_guess_factor)
        assert segmented.segment_guess_factor is not None
        self.assertLess(segmented.segment_guess_factor, 0.0)
        self.assertGreater(segmented.blend, 0.0)





    def test_traditional_gf_visit_trains_the_same_gun_local_key_used_for_aiming(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                min_samples=1,
                segment_min_samples=1,
                segment_full_weight_samples=1,
            )
        )
        fire_context = FireContext(
            bullet_flight_time=28.0,
            lateral_speed_signed=6.0,
            wall_margin=0.08,
        )
        expected_key = gun.profile_segment_key(fire_context)
        self.assertEqual((1, 2, 0), expected_key)
        wave = make_wave(aim_mode="traditional_gf")
        wave.fire_context = fire_context

        for _ in range(3):
            gun.observe_visit(
                GunVisit(
                    wave=wave,
                    actual_bearing=0.0,
                    target_distance=300.0,
                    guess_factor=0.6,
                    segment_key=(9, 9, 9),
                )
            )

        self.assertIn((wave.target_id, expected_key), gun.segment_profiles)
        diagnostics = gun.diagnostics(wave.target_id, expected_key)
        self.assertIsNotNone(diagnostics)
        assert diagnostics is not None
        self.assertEqual(expected_key, diagnostics.profile_key)
        self.assertEqual("segment", diagnostics.source)

    def test_traditional_gf_profile_key_bucket_boundaries(self) -> None:
        gun = TraditionalGfGun(TraditionalGfGunConfig())
        cases = (
            (19.999, 1.999, 0.1199, (0, 0, 0)),
            (20.0, 2.0, 0.12, (1, 1, 1)),
            (34.999, -5.599, 0.2499, (1, 1, 1)),
            (35.0, -5.6, 0.25, (2, 2, 2)),
        )

        for flight_time, lateral_speed, wall_margin, expected in cases:
            with self.subTest(
                flight_time=flight_time,
                lateral_speed=lateral_speed,
                wall_margin=wall_margin,
            ):
                context = FireContext(
                    bullet_flight_time=flight_time,
                    lateral_speed_signed=lateral_speed,
                    wall_margin=wall_margin,
                )
                self.assertEqual(expected, gun.profile_segment_key(context))



    def test_anti_surfer_guess_factor_targets_under_visited_valley(self) -> None:
        gun = AntiSurferGun(
            AntiSurferGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                smoothing_bins=0.75,
            )
        )

        for _ in range(8):
            gun.record(1, 0.0)

        guess_factor = gun.guess_factor(1)
        self.assertIsNotNone(guess_factor)
        assert guess_factor is not None
        self.assertGreater(abs(guess_factor), 0.2)

    def test_anti_surfer_guess_factor_reaches_default_threshold(self) -> None:
        gun = AntiSurferGun(AntiSurferGunConfig())

        for _ in range(20):
            gun.record(1, 0.0)

        self.assertIsNotNone(gun.guess_factor(1))

    def test_anti_surfer_guess_factor_uses_rapid_decay(self) -> None:
        gun = AntiSurferGun(
            AntiSurferGunConfig(
                guess_factor_bins=7,
                min_samples=1,
                smoothing_bins=0.75,
                decay=0.5,
            )
        )

        for _ in range(5):
            gun.record(1, -1.0)
        self.assertGreater(gun.guess_factor(1), -0.9)

        for _ in range(12):
            gun.record(1, 1.0)
        self.assertLess(gun.guess_factor(1), 0.9)


if __name__ == "__main__":
    unittest.main()

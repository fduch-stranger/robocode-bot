import math
import unittest
from types import SimpleNamespace

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
    LINEAR_VARIANT_MODES,
    LINEAR_WALL_AWARE_MODE,
    TargetHistoryStore,
    TargetMotion,
    TargetPosition,
    VirtualGunScorer,
    VirtualGunSystem,
    build_fire_context,
    movement_context_tags,
    should_log_switch_decision,
)
from bot_core.gun.factory import standard_runtime_config
from bot_core.gun.policy import selector_config_from_policy
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.anti_surfer.gun import AntiSurferGun
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.gun import DynamicClusterGun
from bot_core.gun.guns.dynamic_cluster.memory import RollingKnnBuffer
from bot_core.gun.guns.traditional_gf.diagnostics import TraditionalGfDiagnostics
from bot_core.gun.guns.traditional_gf.gun import TraditionalGfGun
from bot_core.gun.guns.traditional_gf.profile import GuessFactorProfile
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.target_snapshot import TargetSnapshot


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

        for mode in LINEAR_VARIANT_MODES:
            self.assertIn(mode, by_mode)
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
        self.assertEqual(12, traditional_gf.segment_min_samples)
        self.assertEqual(48, traditional_gf.segment_full_weight_samples)
        self.assertEqual(12, traditional_gf.coarse_segment_min_samples)
        self.assertEqual(48, traditional_gf.coarse_segment_full_weight_samples)
        self.assertEqual("density", traditional_gf.peak_selection)
        self.assertAlmostEqual(0.8, traditional_gf.global_source_centering_factor)
        self.assertAlmostEqual(0.7, traditional_gf.coarse_source_centering_factor)
        self.assertAlmostEqual(0.8, traditional_gf.coarse_blend_source_centering_factor)
        self.assertAlmostEqual(0.06, traditional_gf.global_source_penalty)
        self.assertAlmostEqual(0.035, traditional_gf.blend_source_penalty)
        self.assertAlmostEqual(0.02, traditional_gf.coarse_blend_source_penalty)

    def test_direct_runtime_config_bypasses_legacy_gun_config(self) -> None:
        runtime = standard_runtime_config(
            system=GunSystemConfig(max_waves=3),
            dynamic_cluster=DynamicClusterGunConfig(min_samples=4),
        )

        components = runtime.component_factory(TargetHistoryStore(max_history=80))
        by_mode = {component.mode: component for component in components}

        self.assertEqual(3, runtime.system.max_waves)
        self.assertEqual(4, by_mode["dynamic_cluster"].config.min_samples)

    def test_runtime_config_registers_force_testable_linear_variants(self) -> None:
        runtime = runtime_config(
            selector=GunSelectorConfig(
                forced_mode=LINEAR_WALL_AWARE_MODE,
                selectable_modes=frozenset({LINEAR_MODE, "dynamic_cluster"}),
            )
        )
        gun = VirtualGunSystem(runtime)
        bot = SimpleNamespace(
            x=100.0,
            y=100.0,
            gun_direction=0.0,
            arena_width=800.0,
            arena_height=600.0,
        )
        target = TargetSnapshot(1, 100.0, 300.0, 100.0, 0.0, 8.0, 1)

        aim = gun.aim(
            bot,
            target,
            distance=200.0,
            firepower=1.0,
            motion=TargetMotion(acceleration=-1.0, velocity_change_age=0),
            field_margin=18.0,
        )

        self.assertEqual(LINEAR_WALL_AWARE_MODE, aim.mode)
        self.assertTrue(LINEAR_VARIANT_MODES.issubset(aim.virtual_bearings))
        self.assertIn(LINEAR_WALL_AWARE_MODE, aim.gun_diagnostics)
        self.assertIn("wall_hit", aim.gun_diagnostics[LINEAR_WALL_AWARE_MODE])
        self.assertNotIn(LINEAR_WALL_AWARE_MODE, runtime.selector.selectable_modes)

    def test_linear_variant_visit_diagnostics_read_wave_metadata(self) -> None:
        runtime = runtime_config()
        gun = VirtualGunSystem(runtime)
        bot = SimpleNamespace(
            x=100.0,
            y=100.0,
            gun_direction=0.0,
            turn_number=10,
            arena_width=800.0,
            arena_height=600.0,
        )
        target = TargetSnapshot(1, 100.0, 300.0, 100.0, 0.0, 8.0, 1)
        aim = gun.aim(
            bot,
            target,
            distance=200.0,
            firepower=1.0,
            motion=TargetMotion(acceleration=-1.0, velocity_change_age=0),
            field_margin=18.0,
        )
        wave = gun.make_wave(bot, target, 1.0, aim)
        visit = GunVisit(
            wave=wave,
            actual_bearing=0.0,
            target_distance=200.0,
            guess_factor=0.0,
            segment_key=wave.segment_key,
        )
        components = {
            component.mode: component
            for component in runtime.component_factory(TargetHistoryStore(max_history=80))
        }

        wall_diagnostics = components[LINEAR_WALL_AWARE_MODE].visit_diagnostics(visit)

        self.assertEqual(aim.gun_diagnostics[LINEAR_WALL_AWARE_MODE], wall_diagnostics)
        self.assertIn("wall_hit", wall_diagnostics)

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

    def test_traditional_gf_centering_factor_shrinks_selected_guess_factor(self) -> None:
        gun = TraditionalGfGun(TraditionalGfGunConfig(centering_factor=0.6))

        self.assertAlmostEqual(0.3, gun.center_guess_factor(0.5))
        self.assertAlmostEqual(-0.3, gun.center_guess_factor(-0.5))

    def test_traditional_gf_source_centering_factor_shrinks_only_matching_source(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                centering_factor=1.0,
                global_source_centering_factor=0.75,
                coarse_source_centering_factor=0.9,
            )
        )

        self.assertAlmostEqual(0.375, gun.center_guess_factor(0.5, "global"))
        self.assertAlmostEqual(0.45, gun.center_guess_factor(0.5, "coarse"))
        self.assertAlmostEqual(0.5, gun.center_guess_factor(0.5, "blend"))

    def test_traditional_gf_uses_coarse_segment_when_exact_segment_is_sparse(self) -> None:
        config = TraditionalGfGunConfig(
            min_samples=1,
            segment_min_samples=4,
            coarse_segment_min_samples=2,
            coarse_segment_full_weight_samples=4,
            coarse_source_centering_factor=1.0,
        )
        gun = TraditionalGfGun(config)
        target_id = 1
        segment_key = (0, 1, 2, 0, 1, 2)
        global_profile = GuessFactorProfile(visits=4, effective_weight=4.0, bins=[0.0] * config.guess_factor_bins)
        global_profile.bins[config.guess_factor_bins // 2] = 4.0
        coarse_profile = GuessFactorProfile(visits=4, effective_weight=4.0, bins=[0.0] * config.guess_factor_bins)
        coarse_profile.bins[-1] = 4.0
        gun.profiles[target_id] = global_profile
        gun.coarse_segment_profiles[(target_id, gun.coarse_segment_key(segment_key))] = coarse_profile

        diagnostics = gun.diagnostics(target_id, segment_key)

        self.assertIsNotNone(diagnostics)
        self.assertEqual("coarse", diagnostics.source)
        self.assertAlmostEqual(1.0, diagnostics.selected_guess_factor or 0.0)
        self.assertEqual(4.0, diagnostics.segment_weight)

    def test_traditional_gf_ignores_coarse_profile_when_segmentation_disabled(self) -> None:
        config = TraditionalGfGunConfig(
            min_samples=1,
            segment_min_samples=0,
            coarse_segment_min_samples=2,
        )
        gun = TraditionalGfGun(config)
        target_id = 1
        segment_key = (0, 1, 2, 0, 1, 2)
        global_profile = GuessFactorProfile(visits=4, effective_weight=4.0, bins=[0.0] * config.guess_factor_bins)
        global_profile.bins[config.guess_factor_bins // 2] = 4.0
        coarse_profile = GuessFactorProfile(visits=4, effective_weight=4.0, bins=[0.0] * config.guess_factor_bins)
        coarse_profile.bins[-1] = 4.0
        gun.profiles[target_id] = global_profile
        gun.coarse_segment_profiles[(target_id, gun.coarse_segment_key(segment_key))] = coarse_profile

        diagnostics = gun.diagnostics(target_id, segment_key)

        self.assertIsNotNone(diagnostics)
        self.assertEqual("global", diagnostics.source)
        self.assertAlmostEqual(0.0, diagnostics.selected_guess_factor or 0.0)

    def test_traditional_gf_does_not_record_coarse_profile_when_segmentation_disabled(self) -> None:
        gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                segment_min_samples=0,
                coarse_segment_min_samples=2,
            )
        )

        gun.record(1, 0.5, (0, 1, 2, 0, 1, 2))

        self.assertEqual({}, gun.segment_profiles)
        self.assertEqual({}, gun.coarse_segment_profiles)

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
                coarse_blend_source_penalty=0.20,
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

        _, _, _, candidates = selector.select_with_diagnostics(
            1,
            {"linear": 0.0, "traditional_gf": 0.5},
            None,
            {"traditional_gf": GunDecisionContext("traditional_gf", {"source": "coarse_blend", "blend": 0.75})},
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertAlmostEqual(0.05, by_mode["traditional_gf"].source_penalty)
        self.assertAlmostEqual(0.23, by_mode["traditional_gf"].score)
        self.assertEqual("coarse_blend", by_mode["traditional_gf"].decision_source)

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
                    {"source": "coarse_blend", "blend": 1.0, "context_tags": frozenset({"stable_pattern"})},
                )
            },
        )

        by_mode = {candidate.mode: candidate for candidate in candidates}
        self.assertEqual("traditional_gf", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", by_mode["traditional_gf"].reason)
        self.assertAlmostEqual(0.025, by_mode["traditional_gf"].margin)

    def test_aim_mode_selector_uses_segment_score_for_primary_slump(self) -> None:
        segment_key = (1, 1, 1, 1, 1, 1)
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
                    {"source": "coarse_blend", "blend": 1.0, "context_tags": frozenset({"stable_pattern"})},
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
                blend_samples=3,
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
                blend_samples=3,
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
                blend_samples=3,
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
                blend_samples=3,
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
                blend_samples=3,
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
                blend_samples=3,
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
                blend_samples=5,
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

    def test_dynamic_cluster_aim_confidence_maturity_uses_sample_count_not_neighbor_count(self) -> None:
        samples = [GunSample(1, turn, (0.0,) * 7, 0.3) for turn in range(1, 21)]
        gun = DynamicClusterGun(
            DynamicClusterGunConfig(
                min_samples=3,
                min_effective_samples=0.0,
                blend_samples=3,
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
        segment_key = (1, 1, 1, 1, 1, 1)

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
        left_segment = (1, 1, 1, 1, 1, 1)
        right_segment = (2, 1, 1, 1, 1, 1)

        for _ in range(4):
            gun.record(1, 1.0, left_segment)
            gun.record(1, -1.0, right_segment)

        self.assertGreater(gun.guess_factor(1, left_segment), 0.0)
        self.assertLess(gun.guess_factor(1, right_segment), 0.0)

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
        segment_key = (1, 1, 1, 1, 1, 1)

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

    def test_traditional_gf_coarse_segment_key_uses_distance_lateral_wall(self) -> None:
        segment_key = (0, 1, 2, 3, 4, 5)

        self.assertEqual(
            (0, 2, 5),
            TraditionalGfGun.coarse_segment_key(segment_key),
        )

    def test_traditional_gf_density_peak_prefers_supported_peak(self) -> None:
        profile = GuessFactorProfile(
            visits=20,
            effective_weight=20.0,
            bins=[0.0, 0.0, 5.0, 6.0, 5.0, 0.0, 10.0],
        )

        max_bin_gun = TraditionalGfGun(
            TraditionalGfGunConfig(guess_factor_bins=7, peak_selection="max")
        )
        density_gun = TraditionalGfGun(
            TraditionalGfGunConfig(
                guess_factor_bins=7,
                peak_selection="density",
                peak_support_radius=1,
            )
        )

        self.assertAlmostEqual(1.0, max_bin_gun.profile_guess_factor(profile))
        self.assertAlmostEqual(0.0, density_gun.profile_guess_factor(profile))

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

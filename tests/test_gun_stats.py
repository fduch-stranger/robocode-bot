import unittest
from types import SimpleNamespace

from bot_core.gun import (
    AimSolution,
    AimModeSelector,
    GunConfig,
    GunSample,
    GunStats,
    GunSwitchCandidate,
    GunWave,
    GunWaveTracker,
    RollingKnnBuffer,
    VirtualGunScorer,
    VirtualGunSystem,
    should_log_switch_decision,
)
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


class GunStatsTest(unittest.TestCase):
    def test_default_knn_memory_keeps_previous_duel_depth(self) -> None:
        config = GunConfig()

        self.assertGreaterEqual(config.max_samples_per_target, 900)
        self.assertGreaterEqual(config.max_samples, config.max_samples_per_target)

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
        tracker = GunWaveTracker(GunConfig(max_waves=2), waves)
        pending = make_wave(fire_turn=2)

        tracker.set_pending_wave(pending)
        recorded = tracker.record_pending_fire()

        self.assertIs(pending, recorded)
        self.assertIsNone(tracker.pending_wave)
        self.assertEqual([1, 2], [wave.fire_turn for wave in waves])

    def test_virtual_gun_scorer_updates_global_and_segment_scores(self) -> None:
        stats: dict[tuple[int, str], GunStats] = {}
        segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats] = {}
        scorer = VirtualGunScorer(GunConfig(score_alpha=0.5), stats, segment_stats)
        wave = make_wave()

        scores = scorer.score_virtual_guns(wave, actual_bearing=0.0, target_distance=300.0)

        self.assertEqual(1.0, scores["linear"])
        self.assertEqual(1, stats[(1, "linear")].visits)
        self.assertEqual(1, stats[(1, "linear")].hits)
        self.assertEqual(1, segment_stats[(1, "linear", wave.segment_key)].visits)

    def test_aim_mode_selector_respects_visit_and_score_thresholds(self) -> None:
        config = GunConfig(min_visits=2, min_switch_score=0.25, switch_margin=0.05)
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=1, hits=1, rolling_score=1.0),
        }
        scorer = VirtualGunScorer(config, stats, {})
        active_modes = {1: "linear"}
        selector = AimModeSelector(config, scorer, active_modes, stats)

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
        config = GunConfig(
            min_visits=2,
            min_switch_score=0.25,
            switch_margin=0.05,
            selectable_modes=frozenset({"linear", "dynamic_cluster", "traditional_gf"}),
        )
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=1, hits=1, rolling_score=1.0),
        }
        scorer = VirtualGunScorer(config, stats, {})
        selector = AimModeSelector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "dynamic_cluster": 1.0}, None)

        self.assertEqual("linear", selected)
        reasons = {candidate.mode: candidate.reason for candidate in candidates}
        self.assertEqual("current", reasons["linear"])
        self.assertEqual("visits", reasons["dynamic_cluster"])
        self.assertEqual("unavailable", reasons["traditional_gf"])

    def test_aim_mode_selector_reports_superseded_candidate_reason(self) -> None:
        config = GunConfig(
            min_visits=2,
            min_switch_score=0.1,
            switch_margin=0.05,
            selectable_modes=frozenset({"linear", "dynamic_cluster", "traditional_gf"}),
            traditional_gf_min_switch_visits=2,
            traditional_gf_min_switch_score=0.1,
        )
        stats = {
            (1, "linear"): GunStats(visits=10, hits=1, rolling_score=0.2),
            (1, "dynamic_cluster"): GunStats(visits=10, hits=3, rolling_score=0.6),
            (1, "traditional_gf"): GunStats(visits=10, hits=2, rolling_score=0.4),
        }
        scorer = VirtualGunScorer(config, stats, {})
        selector = AimModeSelector(config, scorer, {1: "linear"}, stats)

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
        config = GunConfig(
            selectable_modes=frozenset({"linear", "displacement"}),
            displacement_min_switch_visits=5,
            displacement_min_switch_score=0.10,
            switch_margin=0.03,
        )
        stats = {
            (1, "linear"): GunStats(visits=10, hits=1, rolling_score=0.1),
            (1, "displacement"): GunStats(visits=4, hits=4, rolling_score=0.7),
        }
        scorer = VirtualGunScorer(config, stats, {})
        selector = AimModeSelector(config, scorer, {1: "linear"}, stats)

        selected, _, _, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "displacement": 0.5}, None)
        self.assertEqual("linear", selected)
        self.assertEqual("visits", {candidate.mode: candidate.reason for candidate in candidates}["displacement"])

        stats[(1, "displacement")].visits = 5
        selected, _, changed, candidates = selector.select_with_diagnostics(1, {"linear": 0.0, "displacement": 0.5}, None)
        self.assertEqual("displacement", selected)
        self.assertTrue(changed)
        self.assertEqual("selected", {candidate.mode: candidate.reason for candidate in candidates}["displacement"])

    def test_aim_mode_selector_applies_confidence_penalty_to_switch_score(self) -> None:
        config = GunConfig(
            selectable_modes=frozenset({"linear", "dynamic_cluster"}),
            min_visits=1,
            min_switch_score=0.1,
            switch_margin=0.03,
            switch_confidence_visits=100,
            switch_confidence_penalty=0.10,
        )
        stats = {
            (1, "linear"): GunStats(visits=100, hits=0, rolling_score=0.30),
            (1, "dynamic_cluster"): GunStats(visits=10, hits=0, rolling_score=0.40),
        }
        scorer = VirtualGunScorer(config, stats, {})
        selector = AimModeSelector(config, scorer, {1: "linear"}, stats)

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

    def test_aim_mode_selector_honors_forced_available_mode(self) -> None:
        config = GunConfig(
            forced_mode="traditional_gf",
            selectable_modes=frozenset({"linear", "traditional_gf"}),
            traditional_gf_min_switch_visits=999,
            traditional_gf_min_switch_score=0.99,
        )
        stats = {
            (1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2),
            (1, "traditional_gf"): GunStats(visits=1, hits=0, rolling_score=0.0),
        }
        scorer = VirtualGunScorer(config, stats, {})
        active_modes = {1: "linear"}
        selector = AimModeSelector(config, scorer, active_modes, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0, "traditional_gf": 1.0}, None)

        self.assertEqual("traditional_gf", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_aim_mode_selector_ignores_forced_unavailable_mode(self) -> None:
        config = GunConfig(
            forced_mode="dynamic_cluster",
            selectable_modes=frozenset({"linear", "dynamic_cluster"}),
        )
        stats = {(1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2)}
        scorer = VirtualGunScorer(config, stats, {})
        active_modes = {1: "linear"}
        selector = AimModeSelector(config, scorer, active_modes, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0}, None)

        self.assertEqual("linear", selected)
        self.assertEqual("linear", previous)
        self.assertFalse(changed)

    def test_aim_mode_selector_allows_forced_non_selectable_mode(self) -> None:
        config = GunConfig(
            forced_mode="displacement",
            selectable_modes=frozenset({"linear", "dynamic_cluster"}),
        )
        stats = {(1, "linear"): GunStats(visits=3, hits=1, rolling_score=0.2)}
        scorer = VirtualGunScorer(config, stats, {})
        selector = AimModeSelector(config, scorer, {1: "linear"}, stats)

        selected, previous, changed = selector.select(1, {"linear": 0.0, "displacement": 1.0}, None)

        self.assertEqual("displacement", selected)
        self.assertEqual("linear", previous)
        self.assertTrue(changed)

    def test_eval_waves_keep_scores_separate_from_switching_stats(self) -> None:
        gun = VirtualGunSystem(GunConfig(eval_waves_enabled=True, eval_wave_min_interval=8))
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
        gun = VirtualGunSystem()
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
        gun = VirtualGunSystem(
            GunConfig(
                knn_min_samples=3,
                knn_min_effective_samples=2.0,
                knn_blend_samples=3,
                knn_decay_half_life=10.0,
            )
        )
        for turn in range(3):
            gun._knn_memory.add(GunSample(1, turn, (0.0,) * 7, 0.6))
        gun._knn_sequence = 100

        self.assertIsNone(gun._knn_guess_factor(1, (0.0,) * 7))
        gun._knn_sequence = 3
        self.assertIsNotNone(gun._knn_guess_factor(1, (0.0,) * 7))

    def test_traditional_guess_factor_requires_effective_samples(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                traditional_gf_min_samples=3,
                traditional_gf_decay=0.5,
            )
        )

        gun._record_traditional_guess_factor(1, 1.0)
        gun._record_traditional_guess_factor(1, 1.0)

        self.assertIsNone(gun._traditional_guess_factor(1))

    def test_traditional_guess_factor_decays_old_visits(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                traditional_gf_min_samples=1,
                traditional_gf_smoothing_bins=0.75,
                traditional_gf_decay=0.5,
            )
        )

        for _ in range(5):
            gun._record_traditional_guess_factor(1, 1.0)
        self.assertGreater(gun._traditional_guess_factor(1), 0.0)

        for _ in range(8):
            gun._record_traditional_guess_factor(1, -1.0)

        self.assertLess(gun._traditional_guess_factor(1), 0.0)

    def test_traditional_guess_factor_falls_back_to_global_until_segment_ready(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                traditional_gf_min_samples=1,
                traditional_gf_segment_min_samples=3,
                traditional_gf_segment_full_weight_samples=3,
                traditional_gf_smoothing_bins=0.75,
            )
        )
        segment_key = (1, 1, 1, 1, 1, 1)

        for _ in range(5):
            gun._record_traditional_guess_factor(1, 1.0)
        gun._record_traditional_guess_factor(1, -1.0, segment_key)

        self.assertGreater(gun._traditional_guess_factor(1, segment_key), 0.0)

    def test_traditional_guess_factor_uses_segment_profile_when_ready(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                traditional_gf_min_samples=1,
                traditional_gf_segment_min_samples=2,
                traditional_gf_segment_full_weight_samples=2,
                traditional_gf_smoothing_bins=0.75,
            )
        )
        left_segment = (1, 1, 1, 1, 1, 1)
        right_segment = (2, 1, 1, 1, 1, 1)

        for _ in range(4):
            gun._record_traditional_guess_factor(1, 1.0, left_segment)
            gun._record_traditional_guess_factor(1, -1.0, right_segment)

        self.assertGreater(gun._traditional_guess_factor(1, left_segment), 0.0)
        self.assertLess(gun._traditional_guess_factor(1, right_segment), 0.0)

    def test_traditional_guess_factor_reports_segment_diagnostics(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                traditional_gf_min_samples=1,
                traditional_gf_segment_min_samples=2,
                traditional_gf_segment_full_weight_samples=6,
                traditional_gf_smoothing_bins=0.75,
            )
        )
        segment_key = (1, 1, 1, 1, 1, 1)

        for _ in range(4):
            gun._record_traditional_guess_factor(1, 1.0)
        gun._record_traditional_guess_factor(1, -1.0, segment_key)
        fallback = gun._traditional_guess_factor_diagnostics(1, segment_key)
        self.assertIsNotNone(fallback)
        assert fallback is not None
        self.assertEqual("global", fallback.source)
        self.assertIsNone(fallback.segment_guess_factor)
        self.assertGreater(fallback.global_guess_factor, 0.0)

        for _ in range(4):
            gun._record_traditional_guess_factor(1, -1.0, segment_key)
        segmented = gun._traditional_guess_factor_diagnostics(1, segment_key)
        self.assertIsNotNone(segmented)
        assert segmented is not None
        self.assertEqual("blend", segmented.source)
        self.assertIsNotNone(segmented.segment_guess_factor)
        assert segmented.segment_guess_factor is not None
        self.assertLess(segmented.segment_guess_factor, 0.0)
        self.assertGreater(segmented.blend, 0.0)

    def test_anti_surfer_guess_factor_targets_under_visited_valley(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                anti_surfer_min_samples=1,
                anti_surfer_smoothing_bins=0.75,
            )
        )

        for _ in range(8):
            gun._record_anti_surfer_guess_factor(1, 0.0)

        guess_factor = gun._anti_surfer_guess_factor(1)
        self.assertIsNotNone(guess_factor)
        assert guess_factor is not None
        self.assertGreater(abs(guess_factor), 0.2)

    def test_anti_surfer_guess_factor_reaches_default_threshold(self) -> None:
        gun = VirtualGunSystem()

        for _ in range(20):
            gun._record_anti_surfer_guess_factor(1, 0.0)

        self.assertIsNotNone(gun._anti_surfer_guess_factor(1))

    def test_anti_surfer_guess_factor_uses_rapid_decay(self) -> None:
        gun = VirtualGunSystem(
            GunConfig(
                guess_factor_bins=7,
                anti_surfer_min_samples=1,
                anti_surfer_smoothing_bins=0.75,
                anti_surfer_decay=0.5,
            )
        )

        for _ in range(5):
            gun._record_anti_surfer_guess_factor(1, -1.0)
        self.assertGreater(gun._anti_surfer_guess_factor(1), -0.9)

        for _ in range(12):
            gun._record_anti_surfer_guess_factor(1, 1.0)
        self.assertLess(gun._anti_surfer_guess_factor(1), 0.9)


if __name__ == "__main__":
    unittest.main()

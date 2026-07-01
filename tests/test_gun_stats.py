import unittest

from bot_core.gun import (
    AimModeSelector,
    GunConfig,
    GunSample,
    GunStats,
    GunWave,
    GunWaveTracker,
    RollingKnnBuffer,
    VirtualGunScorer,
    VirtualGunSystem,
)


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

        self.assertGreater(abs(gun._anti_surfer_guess_factor(1)), 0.2)

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

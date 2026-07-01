import unittest

from bot_utils.gun import GunConfig, GunSample, RollingKnnBuffer, VirtualGunSystem


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

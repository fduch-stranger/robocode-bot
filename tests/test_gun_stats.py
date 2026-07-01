import unittest

from bot_utils.gun import GunConfig, VirtualGunSystem


class GunStatsTest(unittest.TestCase):
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

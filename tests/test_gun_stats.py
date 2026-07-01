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


if __name__ == "__main__":
    unittest.main()

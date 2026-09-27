import unittest

from bot_core.gun.aim_tracking import offset_tracking_bearing


class AimTrackingTest(unittest.TestCase):
    def test_offset_tracking_keeps_guess_factor_offset(self) -> None:
        self.assertAlmostEqual(37.0, offset_tracking_bearing(35.0, 30.0, 32.0))

    def test_offset_tracking_handles_bearing_wraparound(self) -> None:
        # Last aim 3 degrees counter-clockwise of a direct bearing at the -180/180 seam.
        self.assertAlmostEqual(173.0, offset_tracking_bearing(-178.0, 179.0, 170.0))


if __name__ == "__main__":
    unittest.main()

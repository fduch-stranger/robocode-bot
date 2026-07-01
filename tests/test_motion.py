import unittest
from types import SimpleNamespace

from bot_core.motion import OwnMotionTracker


class OwnMotionTrackerTest(unittest.TestCase):
    def test_initial_update_sets_zero_age_baseline(self) -> None:
        tracker = OwnMotionTracker()
        bot = SimpleNamespace(turn_number=10, speed=0.0, direction=90.0)

        snapshot = tracker.update(bot)

        self.assertEqual(0.0, snapshot.acceleration)
        self.assertEqual(0, snapshot.direction_change_age)
        self.assertEqual(0, snapshot.decel_age)

    def test_tracks_acceleration_direction_change_and_decel_age(self) -> None:
        tracker = OwnMotionTracker()
        tracker.update(SimpleNamespace(turn_number=10, speed=8.0, direction=90.0))

        snapshot = tracker.update(SimpleNamespace(turn_number=11, speed=6.0, direction=96.0))

        self.assertEqual(-2.0, snapshot.acceleration)
        self.assertEqual(0, snapshot.direction_change_age)
        self.assertEqual(0, snapshot.decel_age)

        later = tracker.update(SimpleNamespace(turn_number=15, speed=6.0, direction=96.0))

        self.assertEqual(4, later.direction_change_age)
        self.assertEqual(4, later.decel_age)

    def test_movement_wave_kwargs_match_current_snapshot(self) -> None:
        tracker = OwnMotionTracker()
        tracker.update(SimpleNamespace(turn_number=4, speed=2.0, direction=20.0))
        tracker.update(SimpleNamespace(turn_number=5, speed=3.0, direction=20.0))

        self.assertEqual(
            {
                "acceleration": 1.0,
                "direction_change_age": 0,
                "decel_age": 1,
            },
            tracker.movement_wave_kwargs(5),
        )

    def test_reset_clears_previous_motion(self) -> None:
        tracker = OwnMotionTracker()
        tracker.update(SimpleNamespace(turn_number=4, speed=2.0, direction=20.0))
        tracker.update(SimpleNamespace(turn_number=5, speed=4.0, direction=30.0))

        tracker.reset(20)
        snapshot = tracker.update(SimpleNamespace(turn_number=21, speed=4.0, direction=30.0))

        self.assertEqual(0.0, snapshot.acceleration)
        self.assertEqual(0, snapshot.direction_change_age)
        self.assertEqual(0, snapshot.decel_age)


if __name__ == "__main__":
    unittest.main()

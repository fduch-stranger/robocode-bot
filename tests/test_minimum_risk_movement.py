import unittest
from types import SimpleNamespace

from bot_utils.movement import MinimumRiskConfig, MinimumRiskMovement
from bot_utils.tank_math import TargetSnapshot


class MinimumRiskMovementTest(unittest.TestCase):
    def test_reuses_active_destination_during_commit_window(self) -> None:
        movement = MinimumRiskMovement(
            MinimumRiskConfig(
                candidate_distances=(145.0,),
                candidate_angle_step=45,
                destination_commit_ticks=8,
                destination_switch_risk_ratio=0.0,
            )
        )
        bot = SimpleNamespace(x=500.0, y=500.0, arena_width=1000.0, arena_height=1000.0, turn_number=20)
        targets = [
            TargetSnapshot(1, 100.0, 250.0, 500.0, 0.0, 0.0, 20),
            TargetSnapshot(2, 100.0, 750.0, 500.0, 180.0, 0.0, 20),
        ]

        first = movement.choose(bot, targets, targets[0])
        self.assertIsNotNone(first)
        assert first is not None

        bot.x += 6.0
        bot.turn_number += 1
        second = movement.choose(bot, targets, targets[0])

        self.assertIsNotNone(second)
        assert second is not None
        self.assertTrue(second.reused)
        self.assertEqual(1, second.age)
        self.assertEqual((first.x, first.y), (second.x, second.y))


if __name__ == "__main__":
    unittest.main()

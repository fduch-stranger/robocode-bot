import unittest
from types import SimpleNamespace
from typing import cast

from robocode_tank_royale.bot_api import Bot

from bot_core.gun.prediction import (
    predict_accel_damped_linear_position,
    predict_linear_position,
    predict_wall_aware_linear_position,
)
from bot_core.target_snapshot import TargetSnapshot


def _bot(**attrs: object) -> Bot:
    return cast(Bot, cast(object, SimpleNamespace(**attrs)))


class GunPredictionTest(unittest.TestCase):
    def test_predict_linear_position_uses_iterative_intercept_time(self) -> None:
        bot = _bot(x=0.0, y=0.0, arena_width=1000.0, arena_height=1000.0)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=100.0,
            y=100.0,
            direction=0.0,
            speed=8.0,
            seen_turn=1,
        )

        predicted_x, predicted_y = predict_linear_position(bot, target, 1.0, 18.0)

        self.assertEqual(100.0, predicted_y)
        self.assertGreater(predicted_x, 160.0)

    def test_predict_wall_aware_linear_position_stops_at_wall_collision(self) -> None:
        bot = _bot(x=400.0, y=100.0, arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=780.0,
            y=100.0,
            direction=45.0,
            speed=8.0,
            seen_turn=1,
        )

        linear_x, linear_y = predict_linear_position(bot, target, 1.0, 18.0)
        wall_x, wall_y = predict_wall_aware_linear_position(bot, target, 1.0, 18.0)

        self.assertAlmostEqual(782.0, linear_x)
        self.assertAlmostEqual(782.0, wall_x)
        self.assertLess(wall_y, linear_y)

    def test_predict_accel_damped_linear_position_slows_decelerating_target(self) -> None:
        bot = _bot(x=0.0, y=0.0, arena_width=1000.0, arena_height=1000.0)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=100.0,
            y=100.0,
            direction=0.0,
            speed=8.0,
            seen_turn=1,
        )

        linear_x, linear_y = predict_linear_position(bot, target, 1.0, 18.0)
        damped_x, damped_y = predict_accel_damped_linear_position(
            bot,
            target,
            1.0,
            18.0,
            acceleration=-2.0,
        )

        self.assertEqual(linear_y, damped_y)
        self.assertLess(damped_x, linear_x)

    def test_predict_accel_damped_linear_position_matches_linear_without_acceleration(self) -> None:
        bot = _bot(x=0.0, y=0.0, arena_width=1000.0, arena_height=1000.0)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=100.0,
            y=100.0,
            direction=0.0,
            speed=8.0,
            seen_turn=1,
        )

        self.assertEqual(
            predict_linear_position(bot, target, 1.0, 18.0),
            predict_accel_damped_linear_position(bot, target, 1.0, 18.0),
        )


if __name__ == "__main__":
    unittest.main()

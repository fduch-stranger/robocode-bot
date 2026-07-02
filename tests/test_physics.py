import unittest
from types import SimpleNamespace
from typing import cast

from robocode_tank_royale.bot_api import Bot

from bot_core.physics import (
    RobotMovementState,
    bullet_damage_for_power,
    bullet_hit_bonus_for_power,
    bullet_speed_for_power,
    calc_new_bot_speed,
    gun_heat_for_power,
    max_robot_turn_rate_for_speed,
    next_robot_speed,
    predict_robot_movement,
    wall_collision_damage_for_speed,
)
from bot_core.geometry.position import predicted_position
from bot_core.target_snapshot import TargetSnapshot


def _bot(**attrs: object) -> Bot:
    return cast(Bot, cast(object, SimpleNamespace(**attrs)))


class PhysicsTest(unittest.TestCase):
    def test_robocode_physics_formulas(self) -> None:
        self.assertAlmostEqual(14.0, bullet_speed_for_power(2.0))
        self.assertAlmostEqual(1.4, gun_heat_for_power(2.0))
        self.assertAlmostEqual(10.0, bullet_damage_for_power(2.0))
        self.assertAlmostEqual(6.0, bullet_hit_bonus_for_power(2.0))
        self.assertAlmostEqual(4.0, max_robot_turn_rate_for_speed(8.0))
        self.assertAlmostEqual(3.0, wall_collision_damage_for_speed(8.0))

    def test_predicted_position_uses_iterative_intercept_time(self) -> None:
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

        predicted_x, predicted_y = predicted_position(bot, target, 1.0, 18.0)

        self.assertEqual(100.0, predicted_y)
        self.assertGreater(predicted_x, 160.0)

    def test_robot_movement_predictor_accelerates_and_turns_by_speed_limit(self) -> None:
        state = RobotMovementState(x=100.0, y=100.0, direction=0.0, speed=0.0)

        next_state = predict_robot_movement(state, move_bearing=90.0, max_speed=8.0)

        self.assertAlmostEqual(9.25, next_state.direction)
        self.assertAlmostEqual(1.0, next_state.speed)
        self.assertAlmostEqual(101.0, next_state.x)
        self.assertAlmostEqual(100.0, next_state.y)

    def test_robot_movement_predictor_limits_turn_at_high_speed(self) -> None:
        state = RobotMovementState(x=100.0, y=100.0, direction=0.0, speed=8.0)

        next_state = predict_robot_movement(state, move_bearing=90.0, max_speed=8.0)

        self.assertAlmostEqual(4.0, next_state.direction)
        self.assertAlmostEqual(8.0, next_state.speed)
        self.assertAlmostEqual(108.0, next_state.x)
        self.assertAlmostEqual(100.0, next_state.y)

    def test_calc_new_bot_speed_matches_tank_royale_zero_crossing(self) -> None:
        self.assertAlmostEqual(3.0, calc_new_bot_speed(8.0, -8.0))
        self.assertAlmostEqual(0.5, calc_new_bot_speed(3.0, -8.0))
        self.assertAlmostEqual(-0.75, calc_new_bot_speed(0.5, -8.0))

    def test_robot_movement_predictor_uses_tank_royale_reversal_math(self) -> None:
        state = RobotMovementState(x=100.0, y=100.0, direction=0.0, speed=8.0)

        next_state = predict_robot_movement(state, move_bearing=180.0, max_speed=8.0)

        self.assertAlmostEqual(0.0, next_state.direction)
        self.assertAlmostEqual(3.0, next_state.speed)
        self.assertAlmostEqual(103.0, next_state.x)

    def test_robot_movement_predictor_clamps_to_battlefield(self) -> None:
        state = RobotMovementState(x=780.0, y=300.0, direction=0.0, speed=8.0)

        next_state = predict_robot_movement(
            state,
            move_bearing=0.0,
            max_speed=8.0,
            field_margin=18.0,
            arena_width=800.0,
            arena_height=600.0,
        )

        self.assertEqual(782.0, next_state.x)
        self.assertEqual(300.0, next_state.y)
        self.assertEqual(0.0, next_state.speed)

    def test_next_robot_speed_uses_distance_remaining_to_stop_precisely(self) -> None:
        self.assertAlmostEqual(3.0, next_robot_speed(4.0, 8.0, distance_remaining=3.0))
        self.assertAlmostEqual(0.0, next_robot_speed(0.0, 8.0, distance_remaining=0.0))

    def test_robot_movement_predictor_keeps_reversing_physics_with_distance_remaining(self) -> None:
        state = RobotMovementState(x=100.0, y=100.0, direction=0.0, speed=8.0)

        next_state = predict_robot_movement(
            state,
            move_bearing=180.0,
            max_speed=8.0,
            distance_remaining=20.0,
        )

        self.assertAlmostEqual(0.0, next_state.direction)
        self.assertAlmostEqual(6.0, next_state.speed)
        self.assertAlmostEqual(106.0, next_state.x)


if __name__ == "__main__":
    unittest.main()

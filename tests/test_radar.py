import math
import unittest
from typing import cast

from robocode_tank_royale.bot_api import Bot

from bot_core.radar import (
    RadarLockConfig,
    lock_overscan_for_distance,
    lock_radar_to_target,
    predict_radar_lock_point,
)
from bot_core.target_snapshot import TargetSnapshot


class _Bot:
    def __init__(
        self,
        *,
        x: float = 0.0,
        y: float = 0.0,
        radar_direction: float = 0.0,
        turn_number: int = 10,
        arena_width: float = 1000.0,
        arena_height: float = 1000.0,
    ) -> None:
        self.x = x
        self.y = y
        self.radar_direction = radar_direction
        self.turn_number = turn_number
        self.arena_width = arena_width
        self.arena_height = arena_height
        self.radar_turn: float | None = None
        self.radar_turn_rate: float | None = None

    def set_turn_radar_left(self, degrees: float) -> None:
        self.radar_turn = degrees


def _bot(**attrs: object) -> Bot:
    return cast(Bot, _Bot(**attrs))


def _target_at_bearing(angle: float, distance: float, *, seen_turn: int = 10) -> TargetSnapshot:
    radians = math.radians(angle)
    return TargetSnapshot(
        bot_id=1,
        energy=100.0,
        x=math.cos(radians) * distance,
        y=math.sin(radians) * distance,
        direction=0.0,
        speed=0.0,
        seen_turn=seen_turn,
    )


class RadarTest(unittest.TestCase):
    def test_predict_radar_lock_point_uses_short_linear_lead(self) -> None:
        bot = _bot(arena_width=800.0, arena_height=600.0)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=100.0,
            y=100.0,
            direction=0.0,
            speed=8.0,
            seen_turn=10,
        )

        predicted_x, predicted_y = predict_radar_lock_point(bot, target, lead_ticks=2, field_margin=18.0)

        self.assertAlmostEqual(116.0, predicted_x)
        self.assertAlmostEqual(100.0, predicted_y)

    def test_lock_overscan_is_smaller_for_far_targets_than_old_fixed_overscan(self) -> None:
        config = RadarLockConfig(search_rate=18)

        overscan = lock_overscan_for_distance(600.0, config)

        self.assertGreater(overscan, config.lock_min_overscan)
        self.assertLess(overscan, config.lock_overscan)

    def test_lock_overscan_is_clamped_for_close_targets(self) -> None:
        config = RadarLockConfig(search_rate=18)

        overscan = lock_overscan_for_distance(50.0, config)

        self.assertEqual(config.lock_max_overscan, overscan)

    def test_legacy_lock_overscan_caps_dynamic_overscan(self) -> None:
        config = RadarLockConfig(search_rate=18, lock_overscan=4)

        overscan = lock_overscan_for_distance(50.0, config)

        self.assertEqual(4, overscan)

    def test_fresh_lock_uses_dynamic_overscan(self) -> None:
        bot_impl = cast(_Bot, _bot())
        config = RadarLockConfig(search_rate=18)
        target = _target_at_bearing(0.0, 600.0)

        command = lock_radar_to_target(cast(Bot, bot_impl), target, config)

        self.assertEqual("lock", command.mode)
        self.assertIsNotNone(bot_impl.radar_turn)
        self.assertAlmostEqual(command.turn, cast(float, bot_impl.radar_turn))
        self.assertGreater(command.turn, config.lock_min_overscan)
        self.assertLess(command.turn, config.lock_overscan)

    def test_fresh_lock_reports_actual_target_bearing(self) -> None:
        bot_impl = cast(_Bot, _bot())
        config = RadarLockConfig(search_rate=18)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=600.0,
            y=0.0,
            direction=90.0,
            speed=8.0,
            seen_turn=10,
        )

        command = lock_radar_to_target(cast(Bot, bot_impl), target, config)

        self.assertAlmostEqual(0.0, command.bearing)
        self.assertGreater(command.turn, config.lock_min_overscan)

    def test_stale_target_reacquire_keeps_configured_overscan(self) -> None:
        bot_impl = cast(_Bot, _bot())
        config = RadarLockConfig(search_rate=18, reacquire_overscan=18)
        target = _target_at_bearing(10.0, 600.0, seen_turn=8)

        command = lock_radar_to_target(cast(Bot, bot_impl), target, config)

        self.assertEqual("reacquire", command.mode)
        self.assertEqual(config.reacquire_rate, command.turn)
        self.assertEqual(config.reacquire_rate, bot_impl.radar_turn)

    def test_stale_target_with_small_error_widens_search(self) -> None:
        bot_impl = cast(_Bot, _bot())
        config = RadarLockConfig(search_rate=18)
        target = _target_at_bearing(0.0, 600.0, seen_turn=8)

        command = lock_radar_to_target(cast(Bot, bot_impl), target, config)

        self.assertEqual("widen", command.mode)
        self.assertEqual(config.search_rate, command.turn)
        self.assertEqual(config.search_rate, bot_impl.radar_turn_rate)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace

from bot_core.gun import AimSolution, VirtualGunSystem, bullet_speed_for_power, lateral_direction
from bot_core.geometry.waves import wall_limited_escape_angle, wall_limited_escape_angle_from_state
from bot_core.movement import MovementFlattener
from bot_core.target_snapshot import TargetSnapshot


class GeometryWavesTest(unittest.TestCase):
    def test_gun_wave_escape_angles_follow_positive_guessfactor_direction(self) -> None:
        bot = SimpleNamespace(x=430.0, y=300.0, arena_width=800.0, arena_height=600.0, turn_number=40)
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=70.0,
            y=70.0,
            direction=180.0,
            speed=8.0,
            seen_turn=40,
        )
        aim = AimSolution(
            predicted_x=target.x,
            predicted_y=target.y,
            gun_bearing=0.0,
            mode="linear",
            guess_factor=None,
            features=(0.0,) * 7,
            segment_key=(0,) * 6,
            virtual_bearings={},
        )

        gun = VirtualGunSystem()
        wave = gun.make_wave(bot, target, 1.4, aim)
        expected_lateral = lateral_direction(target, wave.fire_bearing)
        bullet_speed = bullet_speed_for_power(1.4)

        self.assertEqual(-1, expected_lateral)
        self.assertEqual(expected_lateral, wave.lateral_direction)
        self.assertAlmostEqual(
            wall_limited_escape_angle(bot, target, bullet_speed, expected_lateral),
            wave.max_escape_angle_positive,
        )
        self.assertAlmostEqual(
            wall_limited_escape_angle(bot, target, bullet_speed, -expected_lateral),
            wave.max_escape_angle_negative,
        )

    def test_movement_wave_escape_angles_follow_positive_guessfactor_direction(self) -> None:
        bot = SimpleNamespace(
            x=430.0,
            y=300.0,
            direction=0.0,
            speed=8.0,
            arena_width=800.0,
            arena_height=600.0,
            turn_number=40,
        )
        target = TargetSnapshot(
            bot_id=1,
            energy=100.0,
            x=70.0,
            y=70.0,
            direction=0.0,
            speed=0.0,
            seen_turn=40,
        )

        movement = MovementFlattener()
        wave = movement.record_enemy_fire(bot, target, 1.4)
        self.assertIsNotNone(wave)
        assert wave is not None
        bullet_speed = bullet_speed_for_power(1.4)

        self.assertEqual(-1, wave.lateral_direction)
        self.assertAlmostEqual(
            wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                wave.lateral_direction,
            ),
            wave.max_escape_angle_positive,
        )
        self.assertAlmostEqual(
            wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                -wave.lateral_direction,
            ),
            wave.max_escape_angle_negative,
        )


if __name__ == "__main__":
    unittest.main()

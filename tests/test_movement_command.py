import unittest

from bot_core.movement import MovementCommand


class FakeBot:
    def __init__(self, x: float = 100.0, y: float = 100.0, direction: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.direction = direction
        self.target_speed = 0.0
        self.turn_left = 0.0

    def set_turn_left(self, turn: float) -> None:
        self.turn_left = turn


class MovementCommandTest(unittest.TestCase):
    def test_strafe_command_builds_turn_from_bearing_offset_and_direction(self) -> None:
        command = MovementCommand.strafe("orbit", body_bearing=15.0, strafe_offset=92.0, direction=-1, speed=7.0)
        bot = FakeBot()

        command.apply(bot)

        self.assertEqual("orbit", command.mode)
        self.assertAlmostEqual(-77.0, command.turn)
        self.assertAlmostEqual(7.0, command.speed)
        self.assertAlmostEqual(92.0, command.strafe_offset)
        self.assertAlmostEqual(7.0, bot.target_speed)
        self.assertAlmostEqual(-77.0, bot.turn_left)

    def test_destination_command_uses_shared_reverse_drive_math_without_applying_immediately(self) -> None:
        bot = FakeBot()

        command = MovementCommand.drive_to_destination(bot, 0.0, 100.0, 8.0, "goto")

        self.assertEqual("goto", command.mode)
        self.assertAlmostEqual(0.0, command.turn)
        self.assertAlmostEqual(-8.0, command.speed)
        self.assertAlmostEqual(0.0, bot.target_speed)

        command.apply(bot)

        self.assertAlmostEqual(-8.0, bot.target_speed)
        self.assertAlmostEqual(0.0, bot.turn_left)


if __name__ == "__main__":
    unittest.main()

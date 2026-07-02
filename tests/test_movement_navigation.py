import unittest

from bot_core.movement.navigation import drive_to_destination


class FakeBot:
    def __init__(self, x: float, y: float, direction: float) -> None:
        self.x = x
        self.y = y
        self.direction = direction
        self.target_speed = 0.0
        self.turn_left = 0.0

    def set_turn_left(self, turn: float) -> None:
        self.turn_left = turn


class MovementNavigationTest(unittest.TestCase):
    def test_drive_to_destination_drives_forward_when_bearing_is_ahead(self) -> None:
        bot = FakeBot(x=100.0, y=100.0, direction=0.0)

        turn, speed = drive_to_destination(bot, 200.0, 100.0, 8.0)

        self.assertAlmostEqual(0.0, turn)
        self.assertAlmostEqual(8.0, speed)
        self.assertAlmostEqual(8.0, bot.target_speed)
        self.assertAlmostEqual(0.0, bot.turn_left)

    def test_drive_to_destination_reverses_when_destination_is_behind(self) -> None:
        bot = FakeBot(x=100.0, y=100.0, direction=0.0)

        turn, speed = drive_to_destination(bot, 0.0, 100.0, 8.0)

        self.assertAlmostEqual(0.0, turn)
        self.assertAlmostEqual(-8.0, speed)
        self.assertAlmostEqual(-8.0, bot.target_speed)
        self.assertAlmostEqual(0.0, bot.turn_left)

    def test_drive_to_destination_reverses_oblique_turns_over_90_degrees(self) -> None:
        cases = (
            (0.0, 200.0, -45.0),
            (0.0, 0.0, 45.0),
        )
        for x, y, expected_turn in cases:
            with self.subTest(x=x, y=y):
                bot = FakeBot(x=100.0, y=100.0, direction=0.0)

                turn, speed = drive_to_destination(bot, x, y, 8.0)

                self.assertAlmostEqual(expected_turn, turn)
                self.assertAlmostEqual(-8.0, speed)
                self.assertAlmostEqual(-8.0, bot.target_speed)
                self.assertAlmostEqual(expected_turn, bot.turn_left)

    def test_drive_to_destination_keeps_forward_speed_at_90_degree_boundary(self) -> None:
        cases = (
            (100.0, 200.0, 90.0),
            (100.0, 0.0, -90.0),
        )
        for x, y, expected_turn in cases:
            with self.subTest(x=x, y=y):
                bot = FakeBot(x=100.0, y=100.0, direction=0.0)

                turn, speed = drive_to_destination(bot, x, y, 8.0)

                self.assertAlmostEqual(expected_turn, turn)
                self.assertAlmostEqual(8.0, speed)
                self.assertAlmostEqual(8.0, bot.target_speed)
                self.assertAlmostEqual(expected_turn, bot.turn_left)


if __name__ == "__main__":
    unittest.main()

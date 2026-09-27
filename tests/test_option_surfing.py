import math
import unittest
from types import SimpleNamespace

from bot_core.movement import MovementCommand, MovementFlattener, MovementFlatteningConfig, drive_command_to_bearing
from bot_core.movement.option_surfing import (
    CLOCKWISE,
    COUNTER_CLOCKWISE,
    STOP,
    OptionSurfer,
    attack_angle,
    head_on_prior_danger,
    integrate_bin_danger,
    orbit_bearing,
    ring_coverage_half_width,
)
from bot_core.movement.waves import MovementWave
from bot_core.physics import RobotMovementState, bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


def make_bot(x: float = 500.0, y: float = 300.0, direction: float = 90.0, speed: float = 8.0, turn_number: int = 100) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, direction=direction, speed=speed, turn_number=turn_number, arena_width=800.0, arena_height=600.0)


def make_target(x: float = 100.0, y: float = 300.0, seen_turn: int = 100) -> TargetSnapshot:
    return TargetSnapshot(bot_id=2, energy=100.0, x=x, y=y, direction=0.0, speed=0.0, seen_turn=seen_turn)


def make_wave(bot, target, fire_power: float = 1.9, fired_turn: int | None = None, kind: str = "confirmed") -> MovementWave:
    bullet_speed = bullet_speed_for_power(fire_power)
    mea = math.degrees(math.asin(8.0 / bullet_speed))
    return MovementWave(
        target_id=target.bot_id,
        source_x=target.x,
        source_y=target.y,
        direct_bearing=math.degrees(math.atan2(bot.y - target.y, bot.x - target.x)),
        lateral_direction=1,
        bullet_speed=bullet_speed,
        max_escape_angle_positive=mea,
        max_escape_angle_negative=mea,
        fired_turn=bot.turn_number - 1 if fired_turn is None else fired_turn,
        distance_bucket=1,
        kind=kind,
    )


class RingCoverageTest(unittest.TestCase):
    def test_ring_through_the_centre_covers_the_full_tangent_width(self) -> None:
        distance = 400.0
        half_width = ring_coverage_half_width(distance, 18.0, 390.0, 405.0)
        self.assertIsNotNone(half_width)
        self.assertAlmostEqual(math.degrees(math.asin(18.0 / distance)), half_width, places=9)

    def test_ring_clipping_the_near_edge_is_narrower(self) -> None:
        distance = 400.0
        full = math.degrees(math.asin(18.0 / distance))
        half_width = ring_coverage_half_width(distance, 18.0, 370.0, 385.0)
        self.assertIsNotNone(half_width)
        self.assertLess(half_width, full)
        self.assertGreater(half_width, 0.0)

    def test_ring_outside_the_bot_covers_nothing(self) -> None:
        self.assertIsNone(ring_coverage_half_width(400.0, 18.0, 300.0, 315.0))
        self.assertIsNone(ring_coverage_half_width(400.0, 18.0, 430.0, 445.0))


class DangerIntegrationTest(unittest.TestCase):
    def test_full_span_sums_every_bin_once(self) -> None:
        bins = [1.0] * 31
        self.assertAlmostEqual(31.0, integrate_bin_danger(-1.0 - 1 / 30, 1.0 + 1 / 30, bins))

    def test_narrow_span_weights_covered_bins_by_overlap(self) -> None:
        bins = [0.0] * 31
        bins[15] = 2.0
        # Bin 15 spans [-1/30, 1/30]; cover exactly half of it.
        self.assertAlmostEqual(1.0, integrate_bin_danger(0.0, 1 / 30, bins))
        self.assertAlmostEqual(0.0, integrate_bin_danger(0.5, 0.6, bins))

    def test_head_on_prior_is_largest_at_zero(self) -> None:
        centre = head_on_prior_danger(-0.05, 0.05, 1.0, 0.12)
        edge = head_on_prior_danger(0.7, 0.8, 1.0, 0.12)
        self.assertGreater(centre, edge)
        self.assertAlmostEqual(1.0, head_on_prior_danger(-1.0, 1.0, 1.0, 0.12), places=6)


class OrbitGeometryTest(unittest.TestCase):
    def test_attack_angle_leans_in_when_far_and_out_when_close(self) -> None:
        self.assertGreater(attack_angle(900.0, 480.0, 0.6, 81.0), 0.0)
        self.assertLess(attack_angle(200.0, 480.0, 0.6, 81.0), 0.0)
        self.assertEqual(0.0, attack_angle(480.0, 480.0, 0.6, 81.0))
        self.assertEqual(81.0, attack_angle(100000.0, 480.0, 0.6, 81.0))

    def test_orbit_bearing_is_perpendicular_without_lean(self) -> None:
        bearing = orbit_bearing(500.0, 300.0, 100.0, 300.0, CLOCKWISE, 0.0)
        self.assertAlmostEqual(270.0, bearing % 360.0)
        bearing = orbit_bearing(500.0, 300.0, 100.0, 300.0, COUNTER_CLOCKWISE, 0.0)
        self.assertAlmostEqual(90.0, bearing % 360.0)

    def test_drive_command_to_bearing_uses_the_closer_end(self) -> None:
        bot = SimpleNamespace(direction=90.0)
        self.assertEqual((0.0, 8.0), drive_command_to_bearing(bot, 90.0, 8.0))
        turn, speed = drive_command_to_bearing(bot, 240.0, 8.0)
        self.assertAlmostEqual(-30.0, turn)
        self.assertEqual(-8.0, speed)
        command = MovementCommand.hold("option_surf_stop")
        self.assertEqual(0.0, command.speed)
        self.assertEqual(0.0, command.turn)


class OptionSurferTest(unittest.TestCase):
    def test_flat_profile_prefers_the_narrowest_exposure(self) -> None:
        bot = make_bot(speed=0.0)
        target = make_target()
        wave = make_wave(bot, target)
        config = MovementFlatteningConfig(option_surf_head_on_prior=0.0, option_surf_distancing_base=1.0)
        surfer = OptionSurfer(config)
        decision = surfer.choose(bot, target, [wave], {id(wave): [1.0] * 31}, 8.0, 18.0, 480.0, CLOCKWISE)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(STOP, decision.option)
        self.assertEqual(0.0, decision.speed)
        self.assertLess(decision.danger_stop, decision.danger_cw)
        self.assertLess(decision.danger_stop, decision.danger_ccw)
        self.assertGreater(decision.hit_turn, 0)
        self.assertLess(decision.gf_low, decision.gf_high)

    def test_head_on_danger_makes_the_bot_move(self) -> None:
        bot = make_bot(speed=0.0)
        target = make_target()
        wave = make_wave(bot, target)
        bins = [0.0] * 31
        bins[15] = 40.0
        bins[14] = 20.0
        bins[16] = 20.0
        surfer = OptionSurfer(MovementFlatteningConfig(option_surf_distancing_base=1.0))
        decision = surfer.choose(bot, target, [wave], {id(wave): bins}, 8.0, 18.0, 480.0, CLOCKWISE)
        assert decision is not None
        self.assertNotEqual(STOP, decision.option)
        self.assertEqual(8.0, decision.speed)
        self.assertGreater(decision.danger_stop, decision.danger)

    def test_danger_on_one_side_picks_the_other_orbit(self) -> None:
        bot = make_bot(speed=0.0)
        target = make_target()
        wave = make_wave(bot, target)
        surfer = OptionSurfer(MovementFlatteningConfig(option_surf_head_on_prior=0.0, option_surf_distancing_base=1.0))
        clockwise = surfer.evaluate_option(bot, target, [wave], 0, RobotMovementState(bot.x, bot.y, bot.direction, 0.0, bot.turn_number), CLOCKWISE, CLOCKWISE, {id(wave): [0.0] * 31}, 8.0, 18.0, 480.0, (800.0, 600.0), (), math.inf)
        # Load the bins the clockwise orbit reaches; the surfer must choose the other side.
        bins = [0.0] * 31
        low_bin = round((clockwise.gf_low + 1.0) / 2.0 * 30)
        high_bin = round((clockwise.gf_high + 1.0) / 2.0 * 30)
        for index in range(min(low_bin, high_bin), max(low_bin, high_bin) + 1):
            bins[index] = 50.0
        decision = surfer.choose(bot, target, [wave], {id(wave): bins}, 8.0, 18.0, 480.0, CLOCKWISE)
        assert decision is not None
        self.assertNotEqual(CLOCKWISE, decision.option)
        self.assertGreater(decision.danger_cw, decision.danger)

    def test_second_wave_changes_the_choice(self) -> None:
        bot = make_bot(speed=0.0)
        target = make_target()
        first = make_wave(bot, target)
        # Fired two turns after the first wave: it breaks before a stopped bot can get away.
        second = make_wave(bot, target, fired_turn=bot.turn_number + 1)
        config = MovementFlatteningConfig(option_surf_head_on_prior=0.0, option_surf_distancing_base=1.0, option_surf_time_to_impact_weighting=False)
        surfer = OptionSurfer(config)
        flat = [1.0] * 31
        single = surfer.choose(bot, target, [first], {id(first): flat}, 8.0, 18.0, 480.0, CLOCKWISE)
        assert single is not None
        self.assertEqual(STOP, single.option)
        # Stopping for the first wave leaves the bot sitting in a second-wave danger peak at GF 0.
        peaked = [0.0] * 31
        peaked[15] = 400.0
        peaked[14] = 200.0
        peaked[16] = 200.0
        double = surfer.choose(bot, target, [first, second], {id(first): flat, id(second): peaked}, 8.0, 18.0, 480.0, CLOCKWISE)
        assert double is not None
        self.assertEqual(2, double.waves)
        self.assertGreater(double.danger_stop, single.danger_stop)
        self.assertNotEqual(STOP, double.option)


class FlattenerOptionSurfTest(unittest.TestCase):
    def test_choose_option_surf_uses_confirmed_waves_and_shadows(self) -> None:
        bot = make_bot(speed=8.0)
        target = make_target()
        movement = MovementFlattener(MovementFlatteningConfig(bullet_shadow_enabled=True))
        self.assertIsNone(movement.choose_option_surf(bot, target, 8.0, 18.0, 480.0, 1))
        wave = movement.record_enemy_fire(bot, target, 1.9, fired_turn=bot.turn_number - 1)
        self.assertIsNotNone(wave)
        decision = movement.choose_option_surf(bot, target, 8.0, 18.0, 480.0, 1)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual("confirmed", decision.wave_kind)
        self.assertEqual(1, decision.waves)
        self.assertIn(decision.option, (CLOCKWISE, COUNTER_CLOCKWISE, STOP))
        movement.record_enemy_fire(bot, target, 1.9, wave_kind="expected", expected_confidence=0.9, fired_turn=bot.turn_number + 8)
        decision = movement.choose_option_surf(bot, target, 8.0, 18.0, 480.0, 1)
        assert decision is not None
        self.assertEqual(2, decision.waves)


if __name__ == "__main__":
    unittest.main()

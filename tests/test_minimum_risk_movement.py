import unittest
import math
from types import SimpleNamespace

from bot_utils.movement import (
    MinimumRiskConfig,
    MinimumRiskMovement,
    MovementFlattener,
    MovementFlatteningConfig,
    MovementWave,
    MovementWaveFeatures,
)
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

    def test_fire_threat_prefers_lateral_destination(self) -> None:
        movement = MinimumRiskMovement(
            MinimumRiskConfig(
                travel_weight=0.0,
                wall_weight=0.0,
                enemy_weight=0.0,
                close_enemy_weight=0.0,
                target_distance_weight=0.0,
                radial_weight=0.0,
                recent_destination_weight=0.0,
                threat_lateral_weight=10.0,
                threat_distance_weight=0.0,
            )
        )
        bot = SimpleNamespace(x=500.0, y=500.0, arena_width=1000.0, arena_height=1000.0, turn_number=20)
        threat = TargetSnapshot(1, 100.0, 500.0, 100.0, 0.0, 0.0, 20)
        other = TargetSnapshot(2, 100.0, 850.0, 850.0, 180.0, 0.0, 20)

        radial_risk, _, _ = movement._risk(bot, 500.0, 700.0, [threat, other], other, threat, 0)
        lateral_risk, _, _ = movement._risk(bot, 700.0, 500.0, [threat, other], other, threat, 0)

        self.assertLess(lateral_risk, radial_risk)

    def test_movement_profile_survives_round_clear(self) -> None:
        movement = MovementFlattener()
        movement._profile[(1, 0, 15)] = 3.0
        movement._stats_buffers.record(self._incoming_wave(1), 15, 1.0)
        movement._waves.append(object())
        movement._last_switch_turn[1] = 42

        movement.clear_round_state()

        self.assertEqual(3.0, movement._profile[(1, 0, 15)])
        self.assertGreater(movement._stats_buffers.danger(self._incoming_wave(1), 15).danger, 0.0)
        self.assertEqual([], movement._waves)
        self.assertEqual({}, movement._last_switch_turn)

    def test_surf_wall_smoothing_uses_wall_stick_before_next_step_hits_wall(self) -> None:
        movement = MovementFlattener(MovementFlatteningConfig(wall_stick=140.0))
        wave = MovementWave(
            target_id=1,
            source_x=735.0,
            source_y=100.0,
            direct_bearing=0.0,
            lateral_direction=1,
            bullet_speed=14.0,
            max_escape_angle_positive=30.0,
            max_escape_angle_negative=30.0,
            fired_turn=0,
            distance_bucket=1,
        )

        bearing = movement._surf_move_bearing(
            x=740.0,
            y=300.0,
            wave=wave,
            strafe_offset=92.0,
            direction=1,
            field_margin=18.0,
            arena_width=800.0,
            arena_height=600.0,
        )

        stick_x = 740.0 + math.cos(math.radians(bearing)) * movement.config.wall_stick
        self.assertLess(bearing, -20.0)
        self.assertLessEqual(stick_x, 782.0)

    def test_surf_wall_smoothing_keeps_clear_orbit_bearing(self) -> None:
        movement = MovementFlattener(MovementFlatteningConfig(wall_stick=140.0))
        wave = MovementWave(
            target_id=1,
            source_x=395.0,
            source_y=100.0,
            direct_bearing=0.0,
            lateral_direction=1,
            bullet_speed=14.0,
            max_escape_angle_positive=30.0,
            max_escape_angle_negative=30.0,
            fired_turn=0,
            distance_bucket=1,
        )

        bearing = movement._surf_move_bearing(
            x=400.0,
            y=300.0,
            wave=wave,
            strafe_offset=92.0,
            direction=1,
            field_margin=18.0,
            arena_width=800.0,
            arena_height=600.0,
        )

        self.assertAlmostEqual(0.57, bearing, delta=0.1)

    def test_bullet_shadow_reduces_danger_for_intersected_wave_bin(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                bullet_shadow_enabled=True,
                bullet_shadow_danger_multiplier=0.2,
                bullet_shadow_radius_margin=16.0,
            )
        )
        bot = SimpleNamespace(x=500.0, y=100.0, arena_width=1000.0, arena_height=1000.0, turn_number=1)
        wave = MovementWave(
            target_id=1,
            source_x=100.0,
            source_y=100.0,
            direct_bearing=0.0,
            lateral_direction=1,
            bullet_speed=10.0,
            max_escape_angle_positive=30.0,
            max_escape_angle_negative=30.0,
            fired_turn=0,
            distance_bucket=1,
        )
        center_bin = movement.config.bin_count // 2
        movement._profile[(1, 1, center_bin)] = 5.0

        unshadowed = movement._danger(wave, center_bin, bot)
        movement.record_shadow_bullet(bot, "b1", 2.0, 180.0)
        shadowed = movement._danger(wave, center_bin, bot)

        self.assertLess(shadowed, unshadowed)
        self.assertAlmostEqual(unshadowed * 0.2, shadowed)

    def test_bullet_shadow_does_not_reduce_expected_wave_danger(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                bullet_shadow_enabled=True,
                bullet_shadow_danger_multiplier=0.2,
                bullet_shadow_radius_margin=16.0,
            )
        )
        bot = SimpleNamespace(x=500.0, y=100.0, arena_width=1000.0, arena_height=1000.0, turn_number=1)
        wave = MovementWave(
            target_id=1,
            source_x=100.0,
            source_y=100.0,
            direct_bearing=0.0,
            lateral_direction=1,
            bullet_speed=10.0,
            max_escape_angle_positive=30.0,
            max_escape_angle_negative=30.0,
            fired_turn=0,
            distance_bucket=1,
            kind="expected",
        )
        center_bin = movement.config.bin_count // 2
        movement._profile[(1, 1, center_bin)] = 5.0

        unshadowed = movement._danger(wave, center_bin, bot)
        movement.record_shadow_bullet(bot, "b1", 2.0, 180.0)
        shadowed = movement._danger(wave, center_bin, bot)

        self.assertEqual(unshadowed, shadowed)

    def test_go_to_surf_returns_none_without_wave(self) -> None:
        movement = MovementFlattener()
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=0.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 500.0, 100.0, 0.0, 0.0, 20)

        decision = movement.choose_go_to_surf_destination(bot, target, max_speed=8.0, field_margin=80.0)

        self.assertIsNone(decision)

    def test_go_to_surf_destination_stays_inside_field(self) -> None:
        movement = MovementFlattener()
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=0.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 500.0, 100.0, 0.0, 0.0, 20)
        movement._waves.append(self._incoming_wave(target_id=1))

        decision = movement.choose_go_to_surf_destination(bot, target, max_speed=8.0, field_margin=80.0)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertGreater(decision.candidates, 0)
        self.assertGreaterEqual(decision.x, 80.0)
        self.assertLessEqual(decision.x, 920.0)
        self.assertGreaterEqual(decision.y, 80.0)
        self.assertLessEqual(decision.y, 920.0)
        self.assertGreater(decision.hit_turn, 0)
        self.assertGreaterEqual(decision.hit_bin, 0)
        self.assertLess(decision.hit_bin, movement.config.bin_count)

    def test_go_to_surf_ignores_expected_waves_by_default(self) -> None:
        movement = MovementFlattener()
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=0.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 500.0, 100.0, 0.0, 0.0, 20)
        wave = self._incoming_wave(target_id=1)
        wave.kind = "expected"
        movement._waves.append(wave)

        decision = movement.choose_go_to_surf_destination(bot, target, max_speed=8.0, field_margin=80.0)

        self.assertIsNone(decision)

    def test_go_to_surf_uses_confident_expected_waves_when_enabled(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(goto_use_expected_waves=True, goto_expected_wave_min_confidence=0.6)
        )
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=0.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 100.0, 500.0, 100.0, 0.0, 20)
        low_confidence = self._incoming_wave(target_id=1)
        low_confidence.kind = "expected"
        low_confidence.expected_confidence = 0.4
        movement._waves.append(low_confidence)

        self.assertIsNone(movement.choose_go_to_surf_destination(bot, target, max_speed=8.0, field_margin=80.0))

        movement._waves.clear()
        high_confidence = self._incoming_wave(target_id=1)
        high_confidence.kind = "expected"
        high_confidence.expected_confidence = 0.8
        movement._waves.append(high_confidence)

        decision = movement.choose_go_to_surf_destination(bot, target, max_speed=8.0, field_margin=80.0)

        self.assertIsNotNone(decision)

    def test_go_to_surf_scoring_uses_simulated_hit_bin_danger(self) -> None:
        movement = MovementFlattener()
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=0.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 500.0, 100.0, 0.0, 0.0, 20)
        wave = self._incoming_wave(target_id=1)
        candidates = movement._go_to_candidate_points(bot, target, field_margin=80.0)
        scored = [
            movement._score_go_to_candidate(bot, target, wave, x, y, max_speed=8.0, field_margin=80.0)
            for x, y in candidates
        ]
        scored = [decision for decision in scored if decision is not None]
        first = scored[0]
        second = next(decision for decision in scored if decision.hit_bin != first.hit_bin)

        movement._profile[(1, wave.distance_bucket, first.hit_bin)] = 12.0
        first_with_profile = movement._score_go_to_candidate(
            bot, target, wave, first.x, first.y, max_speed=8.0, field_margin=80.0
        )
        second_with_profile = movement._score_go_to_candidate(
            bot, target, wave, second.x, second.y, max_speed=8.0, field_margin=80.0
        )

        assert first_with_profile is not None
        assert second_with_profile is not None
        self.assertGreater(first_with_profile.profile_danger, second_with_profile.profile_danger)

    def test_movement_wave_records_segmentation_features(self) -> None:
        movement = MovementFlattener()
        bot = SimpleNamespace(
            x=500.0,
            y=500.0,
            direction=90.0,
            speed=8.0,
            arena_width=1000.0,
            arena_height=1000.0,
            turn_number=20,
        )
        target = TargetSnapshot(1, 100.0, 100.0, 500.0, 0.0, 0.0, 20)

        wave = movement.record_enemy_fire(
            bot,
            target,
            2.0,
            acceleration=-1.0,
            direction_change_age=9,
            decel_age=3,
        )

        self.assertIsNotNone(wave)
        assert wave is not None
        self.assertAlmostEqual(8.0, wave.features.lateral_velocity, places=2)
        self.assertAlmostEqual(0.0, wave.features.advancing_velocity, places=2)
        self.assertAlmostEqual(-1.0, wave.features.acceleration)
        self.assertEqual(9, wave.features.direction_change_age)
        self.assertEqual(3, wave.features.decel_age)
        self.assertEqual(500.0, wave.features.wall_distance)

    def test_stats_buffer_records_and_decays_segment_visits(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                stats_buffer_decay=0.5,
                stats_buffer_min_samples=1.0,
                stats_buffer_max_effective_samples=1.0,
            )
        )
        wave = self._incoming_wave(1)

        movement._stats_buffers.record(wave, 12, 1.0)
        first = movement._stats_buffers.danger(wave, 12)
        movement._stats_buffers.record(wave, 12, 1.0)
        second = movement._stats_buffers.danger(wave, 12)

        self.assertGreater(first.danger, 0.0)
        self.assertGreater(second.danger, first.danger)
        self.assertLess(second.samples, 2.1)

    def test_confident_ensemble_raises_context_specific_danger(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                stats_buffer_weight=0.5,
                stats_buffer_min_samples=1.0,
                stats_buffer_max_effective_samples=1.0,
                stats_buffer_decay=1.0,
                unvisited_bin_danger=0.0,
            )
        )
        wave = self._incoming_wave(1)
        for _ in range(4):
            movement._stats_buffers.record(wave, 12, 1.0)

        profile_only = movement._smoothed_count(1, wave.distance_bucket, 12)
        blended = movement._danger_breakdown(wave, 12)

        self.assertGreater(blended.total_danger, profile_only)
        self.assertGreater(blended.ensemble_samples, 0.0)
        self.assertGreater(blended.ensemble_weight, 0.0)

    def test_ensemble_does_not_lower_profile_danger(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                stats_buffer_weight=0.5,
                stats_buffer_min_samples=1.0,
                stats_buffer_max_effective_samples=1.0,
                stats_buffer_decay=1.0,
                unvisited_bin_danger=0.0,
            )
        )
        wave = self._incoming_wave(1)
        movement._profile[(1, wave.distance_bucket, 12)] = 10.0
        for _ in range(4):
            movement._stats_buffers.record(wave, 18, 1.0)

        profile_only = movement._smoothed_count(1, wave.distance_bucket, 12)
        blended = movement._danger_breakdown(wave, 12)

        self.assertGreaterEqual(blended.total_danger, profile_only)

    def test_low_sample_ensemble_has_low_blend_weight(self) -> None:
        movement = MovementFlattener(
            MovementFlatteningConfig(
                stats_buffer_weight=0.5,
                stats_buffer_min_samples=1.0,
                stats_buffer_max_effective_samples=50.0,
                stats_buffer_decay=1.0,
            )
        )
        wave = self._incoming_wave(1)
        movement._stats_buffers.record(wave, 12, 1.0)

        danger = movement._danger_breakdown(wave, 12)

        self.assertLess(danger.ensemble_weight, 0.05)

    @staticmethod
    def _incoming_wave(target_id: int) -> MovementWave:
        return MovementWave(
            target_id=target_id,
            source_x=500.0,
            source_y=100.0,
            direct_bearing=90.0,
            lateral_direction=1,
            bullet_speed=11.0,
            max_escape_angle_positive=30.0,
            max_escape_angle_negative=30.0,
            fired_turn=10,
            distance_bucket=1,
            features=MovementWaveFeatures(
                lateral_velocity=4.0,
                advancing_velocity=-2.0,
                bullet_flight_time=28.0,
                acceleration=1.0,
                direction_change_age=12,
                decel_age=18,
                wall_distance=160.0,
            ),
        )


if __name__ == "__main__":
    unittest.main()

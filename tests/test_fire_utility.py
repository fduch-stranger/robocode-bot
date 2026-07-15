import unittest

from bot_core.combat import (
    FireUtilityCalibrator,
    FireUtilityConfig,
    build_fire_utility_context,
    cooldown_turns_for_power,
    power_band_for,
    quality_band_for,
    range_band_for,
)


class FireUtilityBandTests(unittest.TestCase):
    def test_context_bands_keep_calibration_dimensions_small(self) -> None:
        self.assertEqual("near", range_band_for(299.9))
        self.assertEqual("mid", range_band_for(300.0))
        self.assertEqual("far", range_band_for(550.0))
        self.assertEqual("low", power_band_for(0.74))
        self.assertEqual("medium", power_band_for(0.75))
        self.assertEqual("high", power_band_for(1.5))
        self.assertEqual("cold", quality_band_for("linear", None, 7))
        self.assertEqual("warming", quality_band_for("linear", None, 8))
        self.assertEqual("mature", quality_band_for("linear", None, 36))
        self.assertEqual("low", quality_band_for("dynamic_cluster", 0.099, 8))
        self.assertEqual("high", quality_band_for("dynamic_cluster", 0.10, 8))

    def test_context_normalizes_inputs_and_cooldown(self) -> None:
        context = build_fire_utility_context(
            "dynamic_cluster",
            -5.0,
            4.0,
            solution_quality=2.0,
            model_support=-2,
        )
        self.assertEqual(0.0, context.distance)
        self.assertEqual("near", context.range_band)
        self.assertEqual("high", context.power_band)
        self.assertEqual("cold", context.quality_band)
        self.assertEqual(1.0, context.solution_quality)
        self.assertEqual(0, context.model_support)
        self.assertEqual(12, cooldown_turns_for_power(1.0, 0.1))
        self.assertEqual(0, cooldown_turns_for_power(1.0, 0.0))


class FireUtilityCalibratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = FireUtilityConfig()
        self.calibrator = FireUtilityCalibrator(self.config)
        self.context = build_fire_utility_context(
            "linear",
            400.0,
            1.0,
            model_support=40,
            config=self.config,
        )

    def _accept_and_resolve(self, bullet_id: int, outcome: str) -> None:
        shot = self.calibrator.record_accepted_shot(
            bullet_id,
            bullet_id,
            7,
            self.context,
            1.0,
            cooling_rate=0.1,
            behavior_reason="ready",
        )
        self.assertIsNotNone(shot)
        self.assertIsNotNone(
            self.calibrator.resolve_shot(bullet_id + 1, bullet_id, outcome, damage=4.0)
        )

    def test_estimate_uses_canonical_physics_and_prior(self) -> None:
        estimate = self.calibrator.estimate(self.context, 2.0, cooling_rate=0.1)
        self.assertAlmostEqual(1.0 / 6.0, estimate.q)
        self.assertEqual(0, estimate.calibration_support)
        self.assertEqual("global_prior", estimate.fallback_level)
        self.assertAlmostEqual(10.0, estimate.bullet_damage)
        self.assertAlmostEqual(6.0, estimate.hit_bonus)
        self.assertAlmostEqual(1.4, estimate.gun_heat)
        self.assertEqual(14, estimate.cooldown_turns)
        self.assertAlmostEqual(estimate.q * 10.0, estimate.score_utility)
        self.assertAlmostEqual(estimate.q * 16.0 - 2.0, estimate.energy_swing_utility)

    def test_predictions_only_use_previously_resolved_shots(self) -> None:
        before = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        shot = self.calibrator.record_accepted_shot(
            10,
            1,
            7,
            self.context,
            1.0,
            cooling_rate=0.1,
            behavior_reason="ready",
            estimate=before,
        )
        self.assertIsNotNone(shot)
        while_pending = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual(before.q, while_pending.q)
        self.assertEqual(0, while_pending.calibration_support)
        outcome = self.calibrator.resolve_shot(20, 1, "hit_bot", damage=4.0)
        self.assertIsNotNone(outcome)
        after = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertGreater(after.q, before.q)
        self.assertEqual(1, after.calibration_support)
        self.assertEqual("global", after.fallback_level)

    def test_accepted_actual_power_replaces_proposed_power_economics(self) -> None:
        proposed_context = build_fire_utility_context(
            "linear",
            400.0,
            0.7,
            model_support=40,
            config=self.config,
        )
        proposed = self.calibrator.estimate(
            proposed_context,
            0.7,
            cooling_rate=0.1,
        )
        frozen_power_bands = self.calibrator.snapshot_power_bands(proposed_context)
        intervening_context = build_fire_utility_context(
            "linear",
            400.0,
            1.6,
            model_support=40,
            config=self.config,
        )
        self.calibrator.record_accepted_shot(
            9,
            90,
            7,
            intervening_context,
            1.6,
            cooling_rate=0.1,
            behavior_reason="ready",
        )
        self.calibrator.resolve_shot(10, 90, "hit_bot", damage=7.6)
        live_after_callback = self.calibrator.estimate(
            intervening_context,
            1.6,
            cooling_rate=0.1,
        )
        shot = self.calibrator.record_accepted_shot(
            10,
            1,
            7,
            proposed_context,
            1.6,
            cooling_rate=0.1,
            behavior_reason="ready",
            estimate=proposed,
            calibration_snapshots=frozen_power_bands,
        )

        assert shot is not None
        self.assertEqual("high", shot.estimate.context.power_band)
        self.assertAlmostEqual(1.6, shot.estimate.power)
        self.assertAlmostEqual(7.6, shot.estimate.bullet_damage)
        self.assertNotEqual(proposed.score_utility, shot.estimate.score_utility)
        self.assertAlmostEqual(1.0 / 6.0, shot.estimate.q)
        self.assertGreater(live_after_callback.q, shot.estimate.q)

    def test_global_calibration_accumulates_resolved_support(self) -> None:
        self._accept_and_resolve(1, "hit_wall")
        first = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual("global", first.fallback_level)
        self.assertEqual(1, first.calibration_support)
        self.assertEqual(0, first.calibration_hits)
        self._accept_and_resolve(3, "hit_bot")
        second = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual("global", second.fallback_level)
        self.assertEqual(2, second.calibration_support)
        self.assertEqual(1, second.calibration_hits)
        self.assertGreater(second.q, first.q)

    def test_dynamic_high_quality_applies_conservative_odds_multiplier(self) -> None:
        calibrator = FireUtilityCalibrator()
        low_quality = build_fire_utility_context(
            "dynamic_cluster",
            420.0,
            0.7,
            solution_quality=0.099,
            model_support=100,
        )
        high_quality = build_fire_utility_context(
            "dynamic_cluster",
            250.0,
            1.8,
            solution_quality=0.10,
            model_support=100,
        )
        other_mode = build_fire_utility_context(
            "linear",
            250.0,
            1.8,
            solution_quality=0.9,
            model_support=100,
        )

        base = calibrator.estimate(low_quality, 0.7, cooling_rate=0.1)
        adjusted = calibrator.estimate(high_quality, 1.8, cooling_rate=0.1)
        unadjusted_other = calibrator.estimate(other_mode, 1.8, cooling_rate=0.1)
        expected_odds = (base.q / (1.0 - base.q)) * 1.75

        self.assertEqual("global_prior", base.fallback_level)
        self.assertEqual("dynamic_quality_prior", adjusted.fallback_level)
        self.assertAlmostEqual(expected_odds / (1.0 + expected_odds), adjusted.q)
        self.assertAlmostEqual(base.q, unadjusted_other.q)

        shot = calibrator.record_accepted_shot(
            1,
            1,
            7,
            low_quality,
            0.7,
            cooling_rate=0.1,
            behavior_reason="ready",
        )
        self.assertIsNotNone(shot)
        calibrator.resolve_shot(2, 1, "hit_wall")

        supported_base = calibrator.estimate(low_quality, 0.7, cooling_rate=0.1)
        supported_adjusted = calibrator.estimate(high_quality, 1.8, cooling_rate=0.1)
        supported_odds = (supported_base.q / (1.0 - supported_base.q)) * 1.75
        self.assertEqual("global", supported_base.fallback_level)
        self.assertEqual("dynamic_quality", supported_adjusted.fallback_level)
        self.assertEqual(1, supported_adjusted.calibration_support)
        self.assertAlmostEqual(
            supported_odds / (1.0 + supported_odds),
            supported_adjusted.q,
        )

    def test_late_hit_corrects_a_terminal_miss_once(self) -> None:
        shot = self.calibrator.record_accepted_shot(
            10,
            99,
            7,
            self.context,
            1.0,
            cooling_rate=0.1,
            behavior_reason="last_stand",
        )
        self.assertIsNotNone(shot)
        miss = self.calibrator.resolve_shot(20, 99, "round_end")
        self.assertIsNotNone(miss)
        corrected = self.calibrator.resolve_shot(20, 99, "hit_bot", damage=4.0)
        self.assertIsNotNone(corrected)
        assert corrected is not None
        self.assertEqual("round_end", corrected.previous_outcome)
        self.assertTrue(corrected.hit)
        estimate = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual(1, estimate.calibration_support)
        self.assertEqual(1, estimate.calibration_hits)
        self.assertIsNone(self.calibrator.resolve_shot(21, 99, "hit_bot", damage=4.0))

    def test_late_hit_does_not_rewrite_a_durable_miss(self) -> None:
        self.calibrator.record_accepted_shot(
            10,
            99,
            7,
            self.context,
            1.0,
            cooling_rate=0.1,
            behavior_reason="ready",
        )

        durable = self.calibrator.resolve_shot(20, 99, "hit_wall")
        corrected = self.calibrator.resolve_shot(20, 99, "hit_bot", damage=4.0)

        self.assertIsNotNone(durable)
        self.assertIsNone(corrected)
        estimate = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual(1, estimate.calibration_support)
        self.assertEqual(0, estimate.calibration_hits)

    def test_round_close_resolves_pending_and_keeps_lifetime_calibration(self) -> None:
        self.calibrator.record_accepted_shot(
            10,
            1,
            7,
            self.context,
            1.0,
            cooling_rate=0.1,
            behavior_reason="ready",
        )
        outcomes = self.calibrator.close_round(30)
        self.assertEqual(1, len(outcomes))
        self.assertEqual("round_end", outcomes[0].outcome)
        self.assertEqual(0, self.calibrator.pending_accepted_shots)
        self.assertEqual(30, self.calibrator.round_closed_turn)
        self.calibrator.clear_round_state()
        estimate = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual(1, estimate.calibration_support)
        self.calibrator.clear_battle_state()
        reset = self.calibrator.estimate(self.context, 1.0, cooling_rate=0.1)
        self.assertEqual(0, reset.calibration_support)


if __name__ == "__main__":
    unittest.main()

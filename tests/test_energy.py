import unittest

from bot_core.energy import (
    EnemyEnergyCorrectionLedger,
    EnemyFireDetector,
    EnemyFirePowerPredictor,
    EnemyFirePowerPredictorConfig,
    EnergyDropConfig,
    FireGate,
    FireGateConfig,
    GunHeatTracker,
)
from bot_core.physics import gun_heat_for_power


class EnergyTest(unittest.TestCase):
    def test_enemy_energy_correction_ledger_consumes_relevant_turns(self) -> None:
        ledger = EnemyEnergyCorrectionLedger()
        ledger.record(7, turn_number=10, correction=1.2, reason="older_hit")
        ledger.record(7, turn_number=12, correction=2.0, reason="current_hit")
        ledger.record(7, turn_number=14, correction=0.8, reason="future_hit")

        correction = ledger.consume(7, current_turn=12, after_turn=10)

        self.assertAlmostEqual(2.0, correction)
        self.assertAlmostEqual(0.8, ledger.consume(7, current_turn=14, after_turn=-1))
        self.assertEqual(0.0, ledger.consume(7, current_turn=14, after_turn=-1))

    def test_enemy_energy_correction_ledger_can_include_after_turn(self) -> None:
        ledger = EnemyEnergyCorrectionLedger()
        ledger.record(7, turn_number=10, correction=1.2, reason="same_turn_hit")
        ledger.record(7, turn_number=11, correction=2.0, reason="later_hit")

        correction = ledger.consume(7, current_turn=10, after_turn=10, include_after_turn=True)

        self.assertAlmostEqual(1.2, correction)
        self.assertAlmostEqual(2.0, ledger.consume(7, current_turn=11, after_turn=10))

    def test_enemy_energy_correction_ledger_trims_oldest_entries(self) -> None:
        ledger = EnemyEnergyCorrectionLedger(max_entries_per_target=2)
        ledger.record(3, turn_number=1, correction=1.0, reason="first")
        ledger.record(3, turn_number=2, correction=2.0, reason="second")
        ledger.record(3, turn_number=3, correction=3.0, reason="third")

        self.assertAlmostEqual(5.0, ledger.consume(3, current_turn=3, after_turn=0))

    def test_enemy_fire_detector_updates_heat_for_ignored_drop(self) -> None:
        detector = EnemyFireDetector(EnergyDropConfig(max_scan_gap=1))

        detection = detector.evaluate_scan(
            target_id=4,
            previous_energy=80.0,
            current_energy=78.0,
            previous_seen_turn=10,
            current_turn=13,
            scan_gap=3,
            distance=320.0,
            our_energy=90.0,
            cooling_rate=0.1,
        )

        self.assertFalse(detection.is_fire)
        self.assertEqual("stale_scan", detection.signal.reason)
        self.assertIsNotNone(detection.heat_state)
        self.assertEqual(13, detection.heat_state.last_turn if detection.heat_state is not None else None)

    def test_enemy_fire_detector_records_fire_power_and_prediction_error(self) -> None:
        predictor = EnemyFirePowerPredictor()
        prediction = predictor.predict(4, enemy_energy=80.0, our_energy=90.0, distance=320.0)
        previous_predictions = {4: prediction}
        detector = EnemyFireDetector(
            EnergyDropConfig(),
            fire_power=predictor,
            previous_predictions=previous_predictions,
        )

        detection = detector.evaluate_scan(
            target_id=4,
            previous_energy=80.0,
            current_energy=78.0,
            previous_seen_turn=10,
            current_turn=11,
            scan_gap=1,
            distance=320.0,
            our_energy=90.0,
            cooling_rate=0.1,
        )

        self.assertTrue(detection.is_fire)
        self.assertAlmostEqual(2.0, detection.signal.fire_power or 0.0)
        self.assertEqual(prediction, detection.previous_prediction)
        self.assertNotIn(4, previous_predictions)
        self.assertEqual(1, predictor.sample_count(4))
        self.assertIsNotNone(predictor.mean_absolute_error(4))

    def test_enemy_fire_detector_keeps_energy_drop_fire_when_gun_heat_is_hot(self) -> None:
        detector = EnemyFireDetector(EnergyDropConfig())
        detector.evaluate_scan(
            target_id=4,
            previous_energy=80.0,
            current_energy=78.0,
            previous_seen_turn=10,
            current_turn=11,
            scan_gap=1,
            distance=320.0,
            our_energy=90.0,
            cooling_rate=0.1,
        )

        detection = detector.evaluate_scan(
            target_id=4,
            previous_energy=78.0,
            current_energy=76.0,
            previous_seen_turn=11,
            current_turn=12,
            scan_gap=1,
            distance=320.0,
            our_energy=90.0,
            cooling_rate=0.1,
        )

        self.assertTrue(detection.is_fire)
        self.assertEqual("fire", detection.signal.reason)

    def test_fire_gate_returns_ready_decision(self) -> None:
        gate = FireGate(FireGateConfig(fire_memory_turns=1, alignment_degrees=7, energy_margin=5))

        decision = gate.decide(age=1, distance=300.0, gun_bearing=6.5, firepower=2.0, energy=20.0)

        self.assertTrue(decision.can_fire)
        self.assertEqual("ready", decision.reason)
        self.assertEqual(7, decision.alignment_limit)

    def test_fire_gate_reports_policy_reasons_in_order(self) -> None:
        gate = FireGate(
            FireGateConfig(
                fire_memory_turns=4,
                alignment_degrees=8,
                energy_margin=6,
                critical_energy_hold=10,
                low_energy_hold=18,
                low_energy_max_distance=220,
                far_alignment_distance=360,
                far_alignment_degrees=5,
            )
        )

        self.assertEqual("stale", gate.decide(5, 100.0, 0.0, 1.0, 40.0).reason)
        self.assertEqual("critical_energy", gate.decide(1, 100.0, 0.0, 1.0, 10.0).reason)
        self.assertEqual("low_energy_range", gate.decide(1, 300.0, 0.0, 1.0, 18.0).reason)

        alignment = gate.decide(1, 400.0, 5.5, 1.0, 40.0)

        self.assertEqual("gun_alignment", alignment.reason)
        self.assertEqual(5, alignment.alignment_limit)
        self.assertEqual("energy_margin", gate.decide(1, 100.0, 0.0, 6.0, 11.0).reason)

    def test_enemy_fire_power_predictor_starts_with_low_confidence_heuristic(self) -> None:
        predictor = EnemyFirePowerPredictor()

        prediction = predictor.predict(1, enemy_energy=80.0, our_energy=90.0, distance=300.0)

        self.assertEqual("heuristic", prediction.reason)
        self.assertEqual(0, prediction.samples)
        self.assertEqual(0.0, prediction.confidence)
        self.assertGreater(prediction.fire_power, 1.0)

    def test_enemy_fire_power_predictor_learns_nearby_samples(self) -> None:
        predictor = EnemyFirePowerPredictor(EnemyFirePowerPredictorConfig(min_confident_samples=3, neighbors=3))
        for power in (2.2, 2.4, 2.3, 2.5):
            predictor.record(1, enemy_energy=90.0, our_energy=90.0, distance=210.0, fire_power=power)
        for power in (0.7, 0.8, 0.9):
            predictor.record(1, enemy_energy=90.0, our_energy=90.0, distance=760.0, fire_power=power)

        close_prediction = predictor.predict(1, enemy_energy=88.0, our_energy=85.0, distance=220.0)
        far_prediction = predictor.predict(1, enemy_energy=88.0, our_energy=85.0, distance=740.0)

        self.assertGreater(close_prediction.confidence, 0.5)
        self.assertGreater(close_prediction.fire_power, 2.0)
        self.assertLess(far_prediction.fire_power, 1.2)

    def test_enemy_fire_power_predictor_tracks_prediction_error(self) -> None:
        predictor = EnemyFirePowerPredictor()
        prediction = predictor.predict(1, enemy_energy=90.0, our_energy=90.0, distance=300.0)

        predictor.record(
            1,
            enemy_energy=90.0,
            our_energy=90.0,
            distance=300.0,
            fire_power=2.0,
            previous_prediction=prediction,
        )

        self.assertIsNotNone(predictor.mean_absolute_error(1))

    def test_gun_heat_tracker_uses_predicted_power_for_expected_fire(self) -> None:
        tracker = GunHeatTracker()
        tracker.record_fire(1, turn_number=1, fire_power=1.0, cooling_rate=0.1)

        fire_power = tracker.expected_fire_power(1, turn_number=21, cooling_rate=0.1, predicted_fire_power=2.4)

        self.assertAlmostEqual(2.4, fire_power or 0.0)
        self.assertAlmostEqual(gun_heat_for_power(2.4), tracker.update(1, 21, 0.1).heat)


if __name__ == "__main__":
    unittest.main()

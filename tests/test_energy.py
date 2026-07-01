import unittest

from bot_utils.energy import EnemyFirePowerPredictor, EnemyFirePowerPredictorConfig, GunHeatTracker
from bot_utils.physics import gun_heat_for_power


class EnergyTest(unittest.TestCase):
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

from dataclasses import dataclass
import math

from bot_core.geometry.numeric import clamp
from bot_core.physics import bullet_speed_for_power


@dataclass(frozen=True)
class EnemyFirePowerSample:
    enemy_energy: float
    our_energy: float
    distance: float
    fire_power: float


@dataclass(frozen=True)
class EnemyFirePowerPrediction:
    fire_power: float
    confidence: float
    samples: int
    reason: str
    mean_absolute_error: float | None = None


@dataclass(frozen=True)
class EnemyFirePowerPredictorConfig:
    min_fire_power: float = 0.1
    max_fire_power: float = 3.0
    max_samples_per_target: int = 240
    min_confident_samples: int = 6
    neighbors: int = 7
    distance_scale: float = 650.0
    energy_scale: float = 100.0
    low_confidence_cap: float = 0.45


class EnemyFirePowerPredictor:
    def __init__(self, config: EnemyFirePowerPredictorConfig | None = None) -> None:
        self.config = config or EnemyFirePowerPredictorConfig()
        self._samples: dict[int, list[EnemyFirePowerSample]] = {}
        self._absolute_errors: dict[int, list[float]] = {}

    def record(
        self,
        target_id: int,
        enemy_energy: float,
        our_energy: float,
        distance: float,
        fire_power: float,
        previous_prediction: EnemyFirePowerPrediction | None = None,
    ) -> None:
        sample = EnemyFirePowerSample(
            enemy_energy=enemy_energy,
            our_energy=our_energy,
            distance=distance,
            fire_power=clamp(fire_power, self.config.min_fire_power, self.config.max_fire_power),
        )
        samples = self._samples.setdefault(target_id, [])
        samples.append(sample)
        if len(samples) > self.config.max_samples_per_target:
            del samples[: len(samples) - self.config.max_samples_per_target]

        if previous_prediction is not None:
            errors = self._absolute_errors.setdefault(target_id, [])
            errors.append(abs(previous_prediction.fire_power - sample.fire_power))
            if len(errors) > self.config.max_samples_per_target:
                del errors[: len(errors) - self.config.max_samples_per_target]

    def predict(
        self,
        target_id: int,
        enemy_energy: float,
        our_energy: float,
        distance: float,
    ) -> EnemyFirePowerPrediction:
        samples = self._samples.get(target_id, [])
        fallback = self._heuristic_power(enemy_energy, our_energy, distance)
        if not samples:
            return EnemyFirePowerPrediction(
                fire_power=fallback,
                confidence=0.0,
                samples=0,
                reason="heuristic",
                mean_absolute_error=self.mean_absolute_error(target_id),
            )

        query = self._features(enemy_energy, our_energy, distance)
        scored = sorted(
            (
                (self._feature_distance(query, self._features(sample.enemy_energy, sample.our_energy, sample.distance)), sample)
                for sample in samples
            ),
            key=lambda item: item[0],
        )
        neighbors = scored[: max(1, min(self.config.neighbors, len(scored)))]
        weighted_sum = 0.0
        total_weight = 0.0
        total_distance = 0.0
        for feature_distance, sample in neighbors:
            weight = 1.0 / (0.08 + feature_distance)
            weighted_sum += sample.fire_power * weight
            total_weight += weight
            total_distance += feature_distance

        predicted = weighted_sum / total_weight if total_weight else fallback
        sample_confidence = min(1.0, len(samples) / max(1.0, self.config.min_confident_samples))
        neighbor_confidence = max(0.0, 1.0 - total_distance / max(1.0, len(neighbors)))
        confidence = sample_confidence * (0.35 + neighbor_confidence * 0.65)
        if len(samples) < self.config.min_confident_samples:
            blend = len(samples) / max(1.0, self.config.min_confident_samples)
            predicted = fallback * (1.0 - blend) + predicted * blend
            confidence = min(confidence, self.config.low_confidence_cap)

        return EnemyFirePowerPrediction(
            fire_power=clamp(predicted, self.config.min_fire_power, self.config.max_fire_power),
            confidence=clamp(confidence, 0.0, 1.0),
            samples=len(samples),
            reason="knn" if len(samples) >= self.config.min_confident_samples else "knn_warmup",
            mean_absolute_error=self.mean_absolute_error(target_id),
        )

    def mean_absolute_error(self, target_id: int) -> float | None:
        errors = self._absolute_errors.get(target_id, [])
        if not errors:
            return None
        return sum(errors) / len(errors)

    def sample_count(self, target_id: int) -> int:
        return len(self._samples.get(target_id, []))

    def clear(self) -> None:
        self._samples.clear()
        self._absolute_errors.clear()

    def _heuristic_power(self, enemy_energy: float, our_energy: float, distance: float) -> float:
        if enemy_energy <= 0.3:
            return self.config.min_fire_power
        if distance < 220:
            power = 2.4
        elif distance < 430:
            power = 1.8
        elif distance < 650:
            power = 1.35
        else:
            power = 1.0
        if enemy_energy < 12:
            power = min(power, 1.2)
        if our_energy < 18:
            power += 0.25
        return clamp(power, self.config.min_fire_power, min(self.config.max_fire_power, enemy_energy))

    def _features(self, enemy_energy: float, our_energy: float, distance: float) -> tuple[float, float, float]:
        return (
            clamp(enemy_energy / self.config.energy_scale, 0.0, 1.0),
            clamp(our_energy / self.config.energy_scale, 0.0, 1.0),
            clamp(distance / self.config.distance_scale, 0.0, 1.4),
        )

    @staticmethod
    def _feature_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) * (a - b) for a, b in zip(left, right)))

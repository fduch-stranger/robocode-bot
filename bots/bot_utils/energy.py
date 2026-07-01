from dataclasses import dataclass
import math

from bot_utils.physics import bullet_speed_for_power, gun_heat_for_power
from bot_utils.tank_math import clamp


@dataclass(frozen=True)
class EnergyDropConfig:
    min_fire_power: float = 0.1
    max_fire_power: float = 3.0
    max_scan_gap: int = 4
    close_collision_distance: float = 75.0
    close_collision_max_drop: float = 0.8
    evade_lead_ticks: int = 6
    min_evade_ticks: int = 14
    max_evade_ticks: int = 42


@dataclass(frozen=True)
class EnergyDropSignal:
    is_fire: bool
    reason: str
    raw_energy_drop: float
    energy_drop: float
    energy_correction: float
    fire_power: float | None
    bullet_travel_ticks: int | None
    evade_ticks: int


@dataclass(frozen=True)
class GunHeatConfig:
    default_fire_power: float = 1.5
    min_fire_power: float = 0.1
    max_fire_power: float = 3.0
    ready_tolerance: float = 0.05
    min_ticks_between_expected_waves: int = 4


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


@dataclass
class GunHeatState:
    heat: float = 0.0
    last_turn: int = -1
    last_expected_wave_turn: int = -1000
    observed_fire: bool = False


class GunHeatTracker:
    def __init__(self, config: GunHeatConfig | None = None) -> None:
        self.config = config or GunHeatConfig()
        self._states: dict[int, GunHeatState] = {}

    def update(self, target_id: int, turn_number: int, cooling_rate: float) -> GunHeatState:
        state = self._states.setdefault(target_id, GunHeatState(last_turn=turn_number))
        elapsed = max(0, turn_number - state.last_turn)
        if elapsed > 0:
            state.heat = max(0.0, state.heat - cooling_rate * elapsed)
            state.last_turn = turn_number
        return state

    def record_fire(self, target_id: int, turn_number: int, fire_power: float, cooling_rate: float) -> GunHeatState:
        state = self.update(target_id, turn_number, cooling_rate)
        state.heat = gun_heat_for_power(clamp(fire_power, self.config.min_fire_power, self.config.max_fire_power))
        state.last_expected_wave_turn = turn_number
        state.observed_fire = True
        return state

    def expected_fire_power(
        self,
        target_id: int,
        turn_number: int,
        cooling_rate: float,
        predicted_fire_power: float | None = None,
    ) -> float | None:
        state = self.update(target_id, turn_number, cooling_rate)
        if not state.observed_fire:
            return None
        if state.heat > self.config.ready_tolerance:
            return None
        if turn_number - state.last_expected_wave_turn < self.config.min_ticks_between_expected_waves:
            return None
        state.last_expected_wave_turn = turn_number
        fire_power = predicted_fire_power if predicted_fire_power is not None else self.config.default_fire_power
        state.heat = gun_heat_for_power(clamp(fire_power, self.config.min_fire_power, self.config.max_fire_power))
        return fire_power

    def clear_round_state(self) -> None:
        self._states.clear()

    def remove_target(self, target_id: int) -> None:
        self._states.pop(target_id, None)


def classify_energy_drop(
    previous_energy: float,
    current_energy: float,
    scan_gap: int,
    distance: float,
    config: EnergyDropConfig,
    energy_correction: float = 0.0,
) -> EnergyDropSignal:
    raw_energy_drop = previous_energy - current_energy
    energy_drop = previous_energy - (current_energy + energy_correction)
    if energy_drop <= 0:
        return EnergyDropSignal(False, "no_drop", raw_energy_drop, energy_drop, energy_correction, None, None, 0)

    if scan_gap > config.max_scan_gap:
        return EnergyDropSignal(False, "stale_scan", raw_energy_drop, energy_drop, energy_correction, None, None, 0)

    if not (config.min_fire_power <= energy_drop <= config.max_fire_power):
        return EnergyDropSignal(
            False,
            "outside_fire_power",
            raw_energy_drop,
            energy_drop,
            energy_correction,
            None,
            None,
            0,
        )

    if distance <= config.close_collision_distance and energy_drop <= config.close_collision_max_drop:
        return EnergyDropSignal(
            False,
            "close_collision_noise",
            raw_energy_drop,
            energy_drop,
            energy_correction,
            None,
            None,
            0,
        )

    bullet_speed = bullet_speed_for_power(energy_drop)
    bullet_travel_ticks = max(1, round(distance / bullet_speed))
    evade_ticks = round(
        clamp(
            bullet_travel_ticks + config.evade_lead_ticks,
            config.min_evade_ticks,
            config.max_evade_ticks,
        )
    )
    return EnergyDropSignal(
        True,
        "fire",
        raw_energy_drop,
        energy_drop,
        energy_correction,
        energy_drop,
        bullet_travel_ticks,
        evade_ticks,
    )

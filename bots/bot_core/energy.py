from dataclasses import dataclass
import math

from bot_core.physics import bullet_speed_for_power, gun_heat_for_power
from bot_core.tank_math import clamp


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
class EnemyFireDetection:
    signal: EnergyDropSignal
    distance: float
    previous_prediction: "EnemyFirePowerPrediction | None"
    heat_state: "GunHeatState | None"

    @property
    def is_fire(self) -> bool:
        return self.signal.is_fire


@dataclass(frozen=True)
class FireGateConfig:
    fire_memory_turns: int
    alignment_degrees: float
    energy_margin: float
    critical_energy_hold: float | None = None
    low_energy_hold: float | None = None
    low_energy_max_distance: float | None = None
    far_alignment_distance: float | None = None
    far_alignment_degrees: float | None = None


@dataclass(frozen=True)
class FireDecision:
    can_fire: bool
    reason: str
    alignment_limit: float


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


class EnemyEnergyCorrectionLedger:
    def __init__(self, max_entries_per_target: int = 8) -> None:
        self.max_entries_per_target = max_entries_per_target
        self._corrections: dict[int, list[tuple[int, float, str]]] = {}

    def record(self, target_id: int, turn_number: int, correction: float, reason: str) -> None:
        corrections = self._corrections.setdefault(target_id, [])
        corrections.append((turn_number, correction, reason))
        if len(corrections) > self.max_entries_per_target:
            del corrections[: len(corrections) - self.max_entries_per_target]

    def consume(self, target_id: int, current_turn: int, after_turn: int) -> float:
        corrections = self._corrections.get(target_id)
        if not corrections:
            return 0.0

        correction = 0.0
        remaining: list[tuple[int, float, str]] = []
        for turn, value, reason in corrections:
            if turn > current_turn:
                remaining.append((turn, value, reason))
            elif turn > after_turn:
                correction += value

        if remaining:
            self._corrections[target_id] = remaining
        else:
            self._corrections.pop(target_id, None)
        return correction

    def clear(self) -> None:
        self._corrections.clear()


class EnemyFireDetector:
    def __init__(
        self,
        config: EnergyDropConfig,
        correction_ledger: EnemyEnergyCorrectionLedger | None = None,
        gun_heat: "GunHeatTracker | None" = None,
        fire_power: "EnemyFirePowerPredictor | None" = None,
        previous_predictions: "dict[int, EnemyFirePowerPrediction] | None" = None,
    ) -> None:
        self.config = config
        self.correction_ledger = correction_ledger or EnemyEnergyCorrectionLedger()
        self.gun_heat = gun_heat or GunHeatTracker()
        self.fire_power = fire_power or EnemyFirePowerPredictor()
        self.previous_predictions = previous_predictions if previous_predictions is not None else {}

    def evaluate_scan(
        self,
        target_id: int,
        previous_energy: float,
        current_energy: float,
        previous_seen_turn: int,
        current_turn: int,
        scan_gap: int,
        distance: float,
        our_energy: float,
        cooling_rate: float,
    ) -> EnemyFireDetection:
        energy_correction = self.correction_ledger.consume(target_id, current_turn, previous_seen_turn)
        signal = classify_energy_drop(
            previous_energy,
            current_energy,
            scan_gap,
            distance,
            self.config,
            energy_correction=energy_correction,
        )
        if not signal.is_fire:
            heat_state = self.gun_heat.update(target_id, current_turn, cooling_rate)
            return EnemyFireDetection(signal, distance, None, heat_state)

        previous_prediction = self.previous_predictions.pop(target_id, None)
        fire_power = signal.fire_power or self.gun_heat.config.default_fire_power
        self.fire_power.record(
            target_id,
            enemy_energy=previous_energy,
            our_energy=our_energy,
            distance=distance,
            fire_power=fire_power,
            previous_prediction=previous_prediction,
        )
        heat_state = self.gun_heat.record_fire(target_id, current_turn, fire_power, cooling_rate)
        return EnemyFireDetection(signal, distance, previous_prediction, heat_state)

    def record_correction(self, target_id: int, turn_number: int, correction: float, reason: str) -> None:
        self.correction_ledger.record(target_id, turn_number, correction, reason)

    def consume_correction(self, target_id: int, current_turn: int, after_turn: int) -> float:
        return self.correction_ledger.consume(target_id, current_turn, after_turn)

    def clear_round_state(self) -> None:
        self.correction_ledger.clear()
        self.previous_predictions.clear()
        self.gun_heat.clear_round_state()

    def remove_target(self, target_id: int) -> None:
        self.previous_predictions.pop(target_id, None)
        self.gun_heat.remove_target(target_id)


class FireGate:
    def __init__(self, config: FireGateConfig) -> None:
        self.config = config

    def decide(
        self,
        age: int,
        distance: float,
        gun_bearing: float,
        firepower: float,
        energy: float,
    ) -> FireDecision:
        alignment_limit = self.alignment_limit(distance)
        if age > self.config.fire_memory_turns:
            return FireDecision(False, "stale", alignment_limit)
        if self.config.critical_energy_hold is not None and energy <= self.config.critical_energy_hold:
            return FireDecision(False, "critical_energy", alignment_limit)
        if (
            self.config.low_energy_hold is not None
            and self.config.low_energy_max_distance is not None
            and energy <= self.config.low_energy_hold
            and distance > self.config.low_energy_max_distance
        ):
            return FireDecision(False, "low_energy_range", alignment_limit)
        if abs(gun_bearing) > alignment_limit:
            return FireDecision(False, "gun_alignment", alignment_limit)
        if energy <= firepower + self.config.energy_margin:
            return FireDecision(False, "energy_margin", alignment_limit)
        return FireDecision(True, "ready", alignment_limit)

    def alignment_limit(self, distance: float) -> float:
        if (
            self.config.far_alignment_distance is not None
            and self.config.far_alignment_degrees is not None
            and distance > self.config.far_alignment_distance
        ):
            return self.config.far_alignment_degrees
        return self.config.alignment_degrees


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

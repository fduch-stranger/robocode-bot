from dataclasses import dataclass

from bot_core.energy.corrections import EnemyEnergyCorrectionLedger
from bot_core.energy.drops import EnergyDropConfig, EnergyDropSignal, classify_energy_drop
from bot_core.energy.fire_power import EnemyFirePowerPrediction, EnemyFirePowerPredictor
from bot_core.energy.gun_heat import GunHeatState, GunHeatTracker


@dataclass(frozen=True)
class EnemyFireDetection:
    signal: EnergyDropSignal
    distance: float
    previous_prediction: "EnemyFirePowerPrediction | None"
    heat_state: "GunHeatState | None"

    @property
    def is_fire(self) -> bool:
        return self.signal.is_fire


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

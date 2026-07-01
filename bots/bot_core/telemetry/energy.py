from bot_core.energy import EnergyDropSignal, EnemyFirePowerPrediction, GunHeatState
from bot_core.telemetry.sink import TelemetrySink
from bot_core.telemetry.tick import rounded

_UNSET = object()


class EnergyTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def record_drop_ignored(
        self,
        target_id: int,
        signal: EnergyDropSignal,
        scan_gap: int,
        distance: float,
        previous_energy: float | None = None,
        energy: float | None = None,
    ) -> None:
        self._sink.log("enemy.energy_drop_ignored", **_energy_drop_ignored_fields(target_id, signal, scan_gap, distance, previous_energy, energy))

    def record_enemy_fire_detected(
        self,
        target_id: int,
        signal: EnergyDropSignal,
        scan_gap: int,
        distance: float,
        evasion: str,
        evade_until: int,
        movement_wave_created: bool,
        previous_prediction: EnemyFirePowerPrediction | None,
        power_samples: int,
        power_mae: float | None,
        *,
        previous_energy: float | None = None,
        energy: float | None = None,
        evade_direction: int | None = None,
        evading: bool | None = None,
        move_direction: int | None = None,
        known_targets: int | None = None,
        heat_state: GunHeatState | None | object = _UNSET,
    ) -> None:
        self._sink.log(
            "enemy.fire_detected",
            **_enemy_fire_detected_fields(
                target_id,
                signal,
                scan_gap,
                distance,
                evasion,
                evade_until,
                movement_wave_created,
                previous_prediction,
                power_samples,
                power_mae,
                previous_energy=previous_energy,
                energy=energy,
                evade_direction=evade_direction,
                evading=evading,
                move_direction=move_direction,
                known_targets=known_targets,
                heat_state=heat_state,
            ),
        )

    def record_gun_heat_wave(
        self,
        target_id: int,
        fire_power: float,
        prediction: EnemyFirePowerPrediction,
        distance: float,
        age: int,
        movement_wave_created: bool,
    ) -> None:
        self._sink.log(
            "enemy.gun_heat_wave",
            **_gun_heat_wave_fields(target_id, fire_power, prediction, distance, age, movement_wave_created),
        )


def _energy_drop_ignored_fields(
    target_id: int,
    signal: EnergyDropSignal,
    scan_gap: int,
    distance: float,
    previous_energy: float | None = None,
    energy: float | None = None,
) -> dict[str, object]:
    fields = {
        "bot_id": target_id,
        "reason": signal.reason,
        "raw_drop": round(signal.raw_energy_drop, 2),
        "corrected_drop": round(signal.energy_drop, 2),
        "correction": round(signal.energy_correction, 2),
        "scan_gap": scan_gap,
        "distance": round(distance, 1),
    }
    if previous_energy is not None:
        fields["previous_energy"] = round(previous_energy, 1)
    if energy is not None:
        fields["energy"] = round(energy, 1)
    return fields


def _enemy_fire_detected_fields(
    target_id: int,
    signal: EnergyDropSignal,
    scan_gap: int,
    distance: float,
    evasion: str,
    evade_until: int,
    movement_wave_created: bool,
    previous_prediction: EnemyFirePowerPrediction | None,
    power_samples: int,
    power_mae: float | None,
    *,
    previous_energy: float | None = None,
    energy: float | None = None,
    evade_direction: int | None = None,
    evading: bool | None = None,
    move_direction: int | None = None,
    known_targets: int | None = None,
    heat_state: GunHeatState | None | object = _UNSET,
) -> dict[str, object]:
    actual_fire_power = signal.fire_power or 1.5
    fields = {
        "bot_id": target_id,
        "power": round(signal.fire_power or 0.0, 2),
        "raw_drop": round(signal.raw_energy_drop, 2),
        "corrected_drop": round(signal.energy_drop, 2),
        "correction": round(signal.energy_correction, 2),
        "scan_gap": scan_gap,
        "distance": round(distance, 1),
        "bullet_travel_ticks": signal.bullet_travel_ticks,
        "evasion": evasion,
        "evade_until": evade_until,
        "movement_wave": movement_wave_created,
        "predicted_power": round(previous_prediction.fire_power, 2) if previous_prediction is not None else None,
        "prediction_error": round(abs(previous_prediction.fire_power - actual_fire_power), 2)
        if previous_prediction is not None
        else None,
        "power_samples": power_samples,
        "power_mae": rounded(power_mae, 3),
    }
    if previous_energy is not None:
        fields["previous_energy"] = round(previous_energy, 1)
    if energy is not None:
        fields["energy"] = round(energy, 1)
    if evade_direction is not None:
        fields["evade_direction"] = evade_direction
    if evading is not None:
        fields["evading"] = evading
    if move_direction is not None:
        fields["move_direction"] = move_direction
    if known_targets is not None:
        fields["known_targets"] = known_targets
    if heat_state is not _UNSET:
        fields["gun_heat"] = round(heat_state.heat, 2) if heat_state is not None else None
    if previous_prediction is not None and evading is not None:
        fields["prediction_confidence"] = round(previous_prediction.confidence, 3)
        fields["prediction_reason"] = previous_prediction.reason
    return fields


def _gun_heat_wave_fields(
    target_id: int,
    fire_power: float,
    prediction: EnemyFirePowerPrediction,
    distance: float,
    target_age: int,
    movement_wave_created: bool,
) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "power": round(fire_power, 2),
        "confidence": round(prediction.confidence, 3),
        "samples": prediction.samples,
        "reason": prediction.reason,
        "power_mae": rounded(prediction.mean_absolute_error, 3),
        "distance": round(distance, 1),
        "target_age": target_age,
        "movement_wave": movement_wave_created,
    }

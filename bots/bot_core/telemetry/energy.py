from bot_core.energy import EnergyDropSignal, EnemyFirePowerPrediction, GunHeatState
from bot_core.telemetry.tick import rounded


def energy_drop_ignored_fields(
    target_id: int,
    signal: EnergyDropSignal,
    scan_gap: int,
    distance: float,
    previous_energy: float,
    energy: float,
) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "reason": signal.reason,
        "raw_drop": round(signal.raw_energy_drop, 2),
        "corrected_drop": round(signal.energy_drop, 2),
        "correction": round(signal.energy_correction, 2),
        "scan_gap": scan_gap,
        "distance": round(distance, 1),
        "previous_energy": round(previous_energy, 1),
        "energy": round(energy, 1),
    }


def enemy_fire_detected_fields(
    target_id: int,
    signal: EnergyDropSignal,
    scan_gap: int,
    distance: float,
    previous_energy: float,
    energy: float,
    evasion: str,
    evade_direction: int,
    evade_until: int,
    known_targets: int,
    movement_wave_created: bool,
    heat_state: GunHeatState | None,
    previous_prediction: EnemyFirePowerPrediction | None,
    power_samples: int,
    power_mae: float | None,
) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "power": round(signal.fire_power or 0.0, 2),
        "raw_drop": round(signal.raw_energy_drop, 2),
        "corrected_drop": round(signal.energy_drop, 2),
        "correction": round(signal.energy_correction, 2),
        "scan_gap": scan_gap,
        "distance": round(distance, 1),
        "bullet_travel_ticks": signal.bullet_travel_ticks,
        "previous_energy": round(previous_energy, 1),
        "energy": round(energy, 1),
        "evasion": evasion,
        "evade_direction": evade_direction,
        "evade_until": evade_until,
        "known_targets": known_targets,
        "movement_wave": movement_wave_created,
        "gun_heat": round(heat_state.heat, 2) if heat_state is not None else None,
        "predicted_power": round(previous_prediction.fire_power, 2) if previous_prediction is not None else None,
        "prediction_error": round(abs(previous_prediction.fire_power - (signal.fire_power or 1.5)), 2)
        if previous_prediction is not None
        else None,
        "power_samples": power_samples,
        "power_mae": rounded(power_mae, 3),
    }


def gun_heat_wave_fields(
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

from dataclasses import dataclass

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
    energy_drop: float
    fire_power: float | None
    bullet_travel_ticks: int | None
    evade_ticks: int


def classify_energy_drop(
    previous_energy: float,
    current_energy: float,
    scan_gap: int,
    distance: float,
    config: EnergyDropConfig,
) -> EnergyDropSignal:
    energy_drop = previous_energy - current_energy
    if energy_drop <= 0:
        return EnergyDropSignal(False, "no_drop", energy_drop, None, None, 0)

    if scan_gap > config.max_scan_gap:
        return EnergyDropSignal(False, "stale_scan", energy_drop, None, None, 0)

    if not (config.min_fire_power <= energy_drop <= config.max_fire_power):
        return EnergyDropSignal(False, "outside_fire_power", energy_drop, None, None, 0)

    if distance <= config.close_collision_distance and energy_drop <= config.close_collision_max_drop:
        return EnergyDropSignal(False, "close_collision_noise", energy_drop, None, None, 0)

    bullet_speed = max(0.1, 20 - 3 * energy_drop)
    bullet_travel_ticks = max(1, round(distance / bullet_speed))
    evade_ticks = round(
        clamp(
            bullet_travel_ticks + config.evade_lead_ticks,
            config.min_evade_ticks,
            config.max_evade_ticks,
        )
    )
    return EnergyDropSignal(True, "fire", energy_drop, energy_drop, bullet_travel_ticks, evade_ticks)

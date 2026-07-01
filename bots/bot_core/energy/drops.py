from dataclasses import dataclass

from bot_core.geometry.numeric import clamp
from bot_core.physics import bullet_speed_for_power


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

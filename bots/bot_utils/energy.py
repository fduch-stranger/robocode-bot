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
        state.heat = 1.0 + clamp(fire_power, self.config.min_fire_power, self.config.max_fire_power) / 5.0
        state.last_expected_wave_turn = turn_number
        state.observed_fire = True
        return state

    def expected_fire_power(self, target_id: int, turn_number: int, cooling_rate: float) -> float | None:
        state = self.update(target_id, turn_number, cooling_rate)
        if not state.observed_fire:
            return None
        if state.heat > self.config.ready_tolerance:
            return None
        if turn_number - state.last_expected_wave_turn < self.config.min_ticks_between_expected_waves:
            return None
        state.last_expected_wave_turn = turn_number
        fire_power = self.config.default_fire_power
        state.heat = 1.0 + clamp(fire_power, self.config.min_fire_power, self.config.max_fire_power) / 5.0
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

    bullet_speed = max(0.1, 20 - 3 * energy_drop)
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

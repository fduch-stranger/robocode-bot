from dataclasses import dataclass

from bot_core.geometry.numeric import clamp
from bot_core.physics import gun_heat_for_power


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

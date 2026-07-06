from dataclasses import dataclass

ENERGY_EPSILON = 1e-9
MIN_FIREPOWER = 0.1


@dataclass(frozen=True)
class FireGateConfig:
    fire_memory_turns: int
    alignment_degrees: float
    energy_margin: float
    critical_energy_hold: float | None = None
    low_energy_hold: float | None = None
    low_energy_max_distance: float | None = None
    last_stand_energy: float | None = None
    last_stand_energy_reserve: float = 0.1
    last_stand_max_distance: float | None = None
    last_stand_alignment_degrees: float | None = None
    far_alignment_distance: float | None = None
    far_alignment_degrees: float | None = None


@dataclass(frozen=True)
class FireDecision:
    can_fire: bool
    reason: str
    alignment_limit: float


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
        last_stand_limit = self._last_stand_alignment_limit(alignment_limit)
        if (
            self.config.last_stand_energy is not None
            and energy <= self.config.last_stand_energy
            and energy + ENERGY_EPSILON >= firepower + self.config.last_stand_energy_reserve
            and (
                self.config.last_stand_max_distance is None
                or distance <= self.config.last_stand_max_distance
            )
            and abs(gun_bearing) <= last_stand_limit
        ):
            return FireDecision(True, "last_stand", last_stand_limit)
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

    def _last_stand_alignment_limit(self, alignment_limit: float) -> float:
        if self.config.last_stand_alignment_degrees is None:
            return alignment_limit
        return min(alignment_limit, self.config.last_stand_alignment_degrees)


def last_stand_firepower(
    energy: float,
    max_firepower: float,
    energy_reserve: float,
    *,
    min_firepower: float = MIN_FIREPOWER,
) -> float | None:
    available = energy - energy_reserve
    if available + ENERGY_EPSILON < min_firepower:
        return None
    return max(min_firepower, min(max_firepower, available))

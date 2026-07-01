from dataclasses import dataclass


@dataclass(frozen=True)
class FlatteningDecision:
    direction: int
    changed: bool
    reason: str
    bucket: int
    current_count: float
    alternative_count: float


@dataclass(frozen=True)
class MovementProfileVisit:
    target_id: int
    guess_factor: float
    bin_index: int
    bucket: int
    visits: float
    wave_age: int
    ensemble_danger: float = 0.0
    ensemble_samples: float = 0.0


@dataclass(frozen=True)
class GoToSurfDecision:
    x: float
    y: float
    danger: float
    candidates: int
    wave_kind: str
    hit_guess_factor: float
    hit_bin: int
    hit_turn: int
    direction: int
    profile_danger: float
    ensemble_danger: float
    ensemble_samples: float
    ensemble_weight: float
    wall_risk: float
    distance_risk: float
    travel_risk: float


@dataclass(frozen=True)
class MovementDangerBreakdown:
    profile_danger: float
    ensemble_danger: float
    ensemble_samples: float
    ensemble_weight: float
    total_danger: float

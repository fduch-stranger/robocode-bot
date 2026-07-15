from dataclasses import dataclass


@dataclass(frozen=True)
class FlatteningDecision:
    direction: int
    changed: bool
    reason: str
    bucket: int
    current_count: float
    alternative_count: float
    shadow_direction: int | None = None
    current_occupancy: float = 0.0
    alternative_occupancy: float = 0.0
    current_hit_danger: float = 0.0
    alternative_hit_danger: float = 0.0
    current_expected_pressure: float = 0.0
    alternative_expected_pressure: float = 0.0
    current_shadow_danger: float = 0.0
    alternative_shadow_danger: float = 0.0
    hit_profile_support: float = 0.0
    hit_fallback_level: str = "occupancy"
    legacy_direction: int | None = None
    score_source: str = "legacy"
    selected_current_danger: float = 0.0
    selected_alternative_danger: float = 0.0


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
    evidence_kind: str = "occupancy"
    wave_kind: str = "confirmed"
    occupancy_visits: float = 0.0
    hit_profile_support: float = 0.0
    match_error: float | None = None


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
    occupancy_danger: float = 0.0
    hit_danger: float = 0.0
    hit_profile_support: float = 0.0
    hit_fallback_level: str = "occupancy"
    expected_pressure: float = 0.0
    shadow_danger: float = 0.0
    shadow_x: float | None = None
    shadow_y: float | None = None
    shadow_direction: int | None = None
    shadow_selected_danger: float | None = None
    live_x: float | None = None
    live_y: float | None = None
    live_direction: int | None = None
    live_selected_danger: float | None = None
    score_source: str = "legacy"


@dataclass(frozen=True)
class MovementEvidenceBreakdown:
    occupancy_danger: float
    hit_danger: float
    hit_profile_support: float
    hit_fallback_level: str
    expected_pressure: float
    shadow_danger: float


@dataclass(frozen=True)
class MovementDangerBreakdown:
    profile_danger: float
    ensemble_danger: float
    ensemble_samples: float
    ensemble_weight: float
    total_danger: float

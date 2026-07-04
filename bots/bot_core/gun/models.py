from dataclasses import dataclass, field


@dataclass(frozen=True)
class FireContext:
    movement_tags: frozenset[str] = frozenset()
    bullet_flight_time: float = 0.0
    lateral_direction: int = 1
    lateral_speed_signed: float = 0.0
    lateral_direction_confidence: float = 0.0
    wall_margin: float = 0.0
    wall_escape_balance: float = 0.0
    positive_escape_angle: float = 0.0
    negative_escape_angle: float = 0.0
    distance_bucket: int = 0
    firepower_bucket: int = 0


@dataclass(frozen=True)
class TargetMotion:
    acceleration: float = 0.0
    velocity_change_age: int = 0


@dataclass
class GunSample:
    target_id: int
    turn: int
    features: tuple[float, ...]
    guess_factor: float
    fire_context: FireContext = field(default_factory=FireContext)


@dataclass
class GunWave:
    source_x: float
    source_y: float
    fire_turn: int
    fire_bearing: float
    target_id: int
    bullet_power: float
    bullet_speed: float
    max_escape_angle_positive: float
    max_escape_angle_negative: float
    lateral_direction: int
    features: tuple[float, ...]
    segment_key: tuple[int, ...]
    aim_mode: str
    aim_guess_factor: float | None
    virtual_bearings: dict[str, float]
    fire_context: FireContext = field(default_factory=FireContext)
    gun_metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class GunStats:
    visits: int = 0
    hits: int = 0
    rolling_score: float = 0.0


@dataclass(frozen=True)
class TargetPosition:
    turn: int
    x: float
    y: float
    speed: float
    direction: float = 0.0
    observed_lateral_speed: float | None = None
    observed_advancing_speed: float | None = None
    observed_wall_margin: float | None = None
    observed_distance: float | None = None


@dataclass
class AimSolution:
    predicted_x: float
    predicted_y: float
    gun_bearing: float
    mode: str
    guess_factor: float | None
    features: tuple[float, ...]
    segment_key: tuple[int, ...]
    virtual_bearings: dict[str, float]
    fire_context: FireContext = field(default_factory=FireContext)
    previous_mode: str | None = None
    mode_changed: bool = False
    switch_candidates: tuple["GunSwitchCandidate", ...] = ()
    gun_diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GunSwitchCandidate:
    mode: str
    available: bool
    score: float
    current_score: float
    visits: int
    required_visits: int
    min_score: float
    margin: float
    reason: str
    raw_score: float | None = None
    raw_current_score: float | None = None
    confidence_penalty: float = 0.0
    current_confidence_penalty: float = 0.0
    source_penalty: float = 0.0
    current_source_penalty: float = 0.0
    decision_source: str | None = None
    decision_bonus: float = 0.0
    current_decision_bonus: float = 0.0
    eval_score_bonus: float = 0.0
    current_eval_score_bonus: float = 0.0
    eval_visits: int = 0
    effective_visits: int = 0


@dataclass
class WaveVisit:
    target_id: int
    guess_factor: float
    samples: int
    traveled: float
    distance: float
    selected_gun: str
    virtual_scores: dict[str, float]
    gun_scores: dict[str, str]
    fire_context: FireContext = field(default_factory=FireContext)
    gun_diagnostics: dict[str, object] = field(default_factory=dict)

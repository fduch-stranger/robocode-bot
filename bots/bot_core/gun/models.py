from dataclasses import dataclass, field


@dataclass(frozen=True)
class GunConfig:
    max_samples: int = 1200
    max_samples_per_target: int = 900
    max_waves: int = 80
    knn_min_samples: int = 60
    knn_blend_samples: int = 150
    knn_neighbors: int = 17
    knn_decay_half_life: float = 0.0
    knn_min_effective_samples: float = 0.0
    wave_visit_margin: float = 18
    guess_factor_bins: int = 31
    guess_factor_bandwidth: float = 0.18
    default_mode: str = "linear"
    forced_mode: str | None = None
    eval_waves_enabled: bool = False
    eval_wave_min_interval: int = 8
    max_eval_waves: int = 80
    selectable_modes: frozenset[str] = frozenset({"linear", "traditional_gf", "dynamic_cluster"})
    min_visits: int = 90
    switch_margin: float = 0.08
    min_switch_score: float = 0.30
    head_on_min_switch_score: float = 0.45
    displacement_min_switch_visits: int = 90
    displacement_min_switch_score: float = 0.30
    switch_confidence_visits: int = 0
    switch_confidence_penalty: float = 0.0
    score_alpha: float = 0.12
    virtual_hit_radius: float = 18
    max_target_history: int = 80
    displacement_min_samples: int = 4
    displacement_time_tolerance: int = 2
    traditional_gf_min_samples: int = 28
    traditional_gf_smoothing_bins: float = 1.25
    traditional_gf_decay: float = 0.985
    traditional_gf_centering_factor: float = 1.0
    traditional_gf_segment_min_samples: int = 0
    traditional_gf_segment_full_weight_samples: int = 80
    traditional_gf_coarse_segment_min_samples: int = 8
    traditional_gf_coarse_segment_full_weight_samples: int = 36
    traditional_gf_peak_selection: str = "max"
    traditional_gf_peak_support_radius: int = 1
    traditional_gf_min_switch_visits: int = 260
    traditional_gf_min_switch_score: float = 0.42
    traditional_gf_global_source_penalty: float = 0.0
    traditional_gf_blend_source_penalty: float = 0.0
    traditional_gf_coarse_blend_source_penalty: float = 0.0
    anti_surfer_min_samples: int = 7
    anti_surfer_smoothing_bins: float = 0.9
    anti_surfer_decay: float = 0.92
    anti_surfer_min_switch_visits: int = 80
    anti_surfer_min_switch_score: float = 0.32
    segment_min_visits: int = 18
    segment_full_weight_visits: int = 80


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
    traditional_gf_source: str | None = None


@dataclass
class GunStats:
    visits: int = 0
    hits: int = 0
    rolling_score: float = 0.0


@dataclass
class GuessFactorProfile:
    visits: int = 0
    effective_weight: float = 0.0
    bins: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class TraditionalGfDiagnostics:
    global_guess_factor: float
    global_weight: float
    segment_guess_factor: float | None = None
    segment_weight: float = 0.0
    blend: float = 0.0
    selected_guess_factor: float | None = None
    source: str = "global"


@dataclass(frozen=True)
class TargetPosition:
    turn: int
    x: float
    y: float
    speed: float


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
    previous_mode: str | None = None
    mode_changed: bool = False
    switch_candidates: tuple["GunSwitchCandidate", ...] = ()
    traditional_gf: TraditionalGfDiagnostics | None = None


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
    traditional_gf_source: str | None = None


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
    traditional_gf_guess_factor: float | None = None
    traditional_gf_error: float | None = None
    traditional_gf_abs_error: float | None = None
    traditional_gf_source: str | None = None

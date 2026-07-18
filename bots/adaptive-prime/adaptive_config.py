import hashlib
import json
import os
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, cast

from bot_core.energy import EnergyDropConfig, FireGate, FireGateConfig
from bot_core.gun import (
    DEFAULT_LIVE_GUN_MODES,
    DynamicClusterPolicy,
    SHARED_GUN_POLICY_DEFAULTS,
    STANDARD_FORCE_GUN_MODES,
    gun_mode_from_env,
    gun_modes_from_env,
    gun_policy_status_fields,
)
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.movement import MinimumRiskConfig, MovementFlatteningConfig
from bot_core.radar import RadarLockConfig


ADAPTIVE_CONFIG_PROFILE = "adaptive-default-v1"
ADAPTIVE_SELECTABLE_GUN_MODES = DEFAULT_LIVE_GUN_MODES
ADAPTIVE_FORCE_GUN_MODES = STANDARD_FORCE_GUN_MODES
ADAPTIVE_DYNAMIC_CLUSTER_POLICY = DynamicClusterPolicy.from_env("ROBOCODE_ADAPTIVE")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _selectable_gun_modes() -> frozenset[str]:
    return gun_modes_from_env("ROBOCODE_ADAPTIVE", ADAPTIVE_SELECTABLE_GUN_MODES, ADAPTIVE_FORCE_GUN_MODES)


def _forced_gun_mode() -> str | None:
    return gun_mode_from_env("ROBOCODE_ADAPTIVE", ADAPTIVE_FORCE_GUN_MODES)


@dataclass(frozen=True)
class TraditionalGfPolicy:
    min_switch_visits: int = SHARED_GUN_POLICY_DEFAULTS.traditional_gf_min_switch_visits
    min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.traditional_gf_min_switch_score
    global_source_min_switch_visits: int = 60
    global_source_min_switch_score: float = 0.16
    trusted_source_min_switch_visits: int = 32
    trusted_source_min_switch_score: float = 0.08

    def __post_init__(self) -> None:
        if min(
            self.min_switch_visits,
            self.global_source_min_switch_visits,
            self.trusted_source_min_switch_visits,
        ) < 1:
            raise ValueError("Traditional GF switch visits must be positive")
        if not all(
            0.0 <= score <= 1.0
            for score in (
                self.min_switch_score,
                self.global_source_min_switch_score,
                self.trusted_source_min_switch_score,
            )
        ):
            raise ValueError("Traditional GF switch scores must be between 0 and 1")


def traditional_gf_config_from_policy(policy: TraditionalGfPolicy) -> TraditionalGfGunConfig:
    return TraditionalGfGunConfig(
        min_switch_visits=policy.min_switch_visits,
        min_switch_score=policy.min_switch_score,
        global_source_min_switch_visits=policy.global_source_min_switch_visits,
        global_source_min_switch_score=policy.global_source_min_switch_score,
        trusted_source_min_switch_visits=policy.trusted_source_min_switch_visits,
        trusted_source_min_switch_score=policy.trusted_source_min_switch_score,
    )


@dataclass(frozen=True)
class GunPolicy:
    selectable_modes: frozenset[str] = _selectable_gun_modes()
    forced_mode: str | None = _forced_gun_mode()
    eval_waves_enabled: bool = _env_flag("ROBOCODE_ADAPTIVE_GUN_EVAL")
    eval_wave_min_interval: int = _env_int("ROBOCODE_ADAPTIVE_GUN_EVAL_INTERVAL", 8)
    eval_wave_max_target_age: int = 2
    knn_min_samples: int = SHARED_GUN_POLICY_DEFAULTS.knn_min_samples
    min_visits: int = SHARED_GUN_POLICY_DEFAULTS.min_visits
    switch_margin: float = 0.08
    primary_over_fallback_margin: float = SHARED_GUN_POLICY_DEFAULTS.primary_over_fallback_margin
    fallback_over_primary_margin: float = 0.18
    situational_over_primary_margin: float = SHARED_GUN_POLICY_DEFAULTS.situational_over_primary_margin
    primary_slump_visits: int = SHARED_GUN_POLICY_DEFAULTS.primary_slump_visits
    primary_slump_score: float = SHARED_GUN_POLICY_DEFAULTS.primary_slump_score
    primary_slump_situational_margin: float = SHARED_GUN_POLICY_DEFAULTS.primary_slump_situational_margin
    min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.min_switch_score
    displacement_min_switch_visits: int = SHARED_GUN_POLICY_DEFAULTS.displacement_min_switch_visits
    displacement_min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.displacement_min_switch_score
    traditional_gf: TraditionalGfPolicy = field(default_factory=TraditionalGfPolicy)
    switch_confidence_visits: int = 120
    switch_confidence_penalty: float = 0.04
    primary_confidence_penalty_scale: float = 0.25
    switch_diagnostics_interval: int = 24
    dynamic_cluster: DynamicClusterPolicy = ADAPTIVE_DYNAMIC_CLUSTER_POLICY


@dataclass(frozen=True)
class DuelFirepowerPolicy:
    low_energy_threshold: float = 18.0
    low_energy_close_distance: float = 260.0
    low_energy_close_power: float = 0.8
    low_energy_far_power: float = 0.6
    finisher_distance: float = 320.0
    finisher_max_power: float = 2.2
    finisher_min_power: float = 0.6
    finisher_energy_divisor: float = 3.5
    finisher_power_bonus: float = 0.2
    close_distance: float = 160.0
    close_high_energy: float = 36.0
    close_high_power: float = 2.2
    close_low_power: float = 1.6
    near_distance: float = 280.0
    near_power: float = 1.8
    mid_distance: float = 420.0
    mid_confidence_visits: int = 45
    mid_energy_lead: float = 12.0
    mid_strong_power: float = 1.6
    mid_base_power: float = 1.3
    far_distance: float = 620.0
    far_confidence_visits: int = 70
    far_confidence_score: float = 0.28
    far_energy_lead: float = 18.0
    far_strong_power: float = 1.3
    far_base_power: float = 1.0
    very_far_power: float = 0.8

    def __post_init__(self) -> None:
        if not (self.close_distance < self.near_distance < self.mid_distance < self.far_distance):
            raise ValueError("Duel firepower distance bands must be strictly increasing")
        if self.finisher_energy_divisor <= 0:
            raise ValueError("Duel finisher energy divisor must be positive")
        if not 0.0 <= self.far_confidence_score <= 1.0:
            raise ValueError("Duel far confidence score must be between 0 and 1")


@dataclass(frozen=True)
class MeleeFirepowerPolicy:
    low_energy_threshold: float = 16.0
    low_energy_close_distance: float = 220.0
    low_energy_close_power: float = 0.8
    low_energy_far_power: float = 0.6
    finisher_distance: float = 260.0
    finisher_max_power: float = 2.2
    finisher_min_power: float = 0.8
    finisher_energy_divisor: float = 3.2
    finisher_power_bonus: float = 0.2
    close_distance: float = 160.0
    close_power: float = 2.0
    confidence_distance: float = 300.0
    confidence_visits: int = 70
    confidence_score: float = 0.36
    confidence_min_energy: float = 28.0
    confidence_power: float = 1.6
    mid_distance: float = 360.0
    mid_power: float = 1.2
    far_power: float = 0.8

    def __post_init__(self) -> None:
        if not (self.close_distance < self.confidence_distance < self.mid_distance):
            raise ValueError("Melee firepower distance bands must be strictly increasing")
        if self.finisher_energy_divisor <= 0:
            raise ValueError("Melee finisher energy divisor must be positive")
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError("Melee confidence score must be between 0 and 1")


@dataclass(frozen=True)
class FirePolicy:
    alignment_degrees: float = 7
    memory_turns: int = 1
    energy_margin: float = 5
    finish_target_energy: float = 14
    melee_finish_target_energy: float = 10
    finish_distance: float = 240
    dynamic_shot_quality_power_scaling_enabled: bool = _env_flag(
        "ROBOCODE_ADAPTIVE_DYNAMIC_SHOT_QUALITY_POWER_SCALING",
        default=True,
    )
    minimum_firepower: float = 0.1
    power_adjustment_epsilon: float = 0.01
    last_stand_energy: float = 7
    last_stand_firepower: float = 0.6
    last_stand_energy_reserve: float = 0.1
    last_stand_max_distance: float = 320
    last_stand_alignment_degrees: float = 3
    enemy_fire_fallback_power: float = 1.5
    enemy_fire_active_evasion_min_distance: float = 0
    melee_fire_active_evasion_min_distance: float = 0
    gun_heat_waves_active: bool = _env_flag("ROBOCODE_ADAPTIVE_GUN_HEAT_WAVES", default=True)
    gun_heat_wave_min_distance: float = 220
    gun_heat_wave_max_target_age: int = 2
    duel: DuelFirepowerPolicy = field(default_factory=DuelFirepowerPolicy)
    melee: MeleeFirepowerPolicy = field(default_factory=MeleeFirepowerPolicy)

    def __post_init__(self) -> None:
        if self.minimum_firepower <= 0 or self.power_adjustment_epsilon <= 0:
            raise ValueError("Firepower floors and epsilons must be positive")
        if self.finish_target_energy < self.melee_finish_target_energy:
            raise ValueError("Duel finisher energy must not be below melee finisher energy")


@dataclass(frozen=True)
class TargetPolicy:
    memory_turns: int = 24
    reacquire_turns: int = 4
    drop_lost_turns: int = 9
    current_target_bonus: float = 58
    recent_threat_bonus: float = 82
    melee_current_target_bonus: float = 18
    melee_recent_threat_bonus: float = 34
    threat_memory_turns: int = 35
    motion_speed_change_threshold: float = 0.35
    motion_direction_change_threshold: float = 7.0
    duel_distance_weight: float = 0.7
    duel_energy_weight: float = 2.5
    duel_age_weight: float = 60.0
    melee_distance_weight: float = 0.45
    melee_energy_weight: float = 2.0
    melee_age_weight: float = 92.0

    def __post_init__(self) -> None:
        if not (0 <= self.reacquire_turns < self.drop_lost_turns <= self.memory_turns):
            raise ValueError("Target reacquire, drop, and memory turns must be ordered")
        if min(
            self.motion_speed_change_threshold,
            self.motion_direction_change_threshold,
            self.duel_distance_weight,
            self.duel_energy_weight,
            self.duel_age_weight,
            self.melee_distance_weight,
            self.melee_energy_weight,
            self.melee_age_weight,
        ) < 0:
            raise ValueError("Target motion thresholds and score weights must be non-negative")


@dataclass(frozen=True)
class RadarPolicy:
    search_rate: float = 18
    lost_sweep_rate: float = 24
    gun_search_rate: float = 18
    gun_alignment_error: float = 5
    reacquire_overshoot: float = 8
    reacquire_widen_per_turn: float = 2
    reacquire_max_overshoot: float = 42
    visible_reacquire_overscan: float = 18


@dataclass(frozen=True)
class MovementPolicy:
    preferred_min_distance: float = 360
    preferred_max_distance: float = 560
    melee_pressure_min_distance: float = 360
    melee_pressure_max_distance: float = 620
    panic_retreat_distance: float = 190
    melee_panic_retreat_distance: float = 245
    close_reset_distance: float = 330
    melee_close_reset_distance: float = 340
    field_margin: float = 18
    wall_margin: float = 90
    wall_lookahead_ticks: int = 11
    wall_escape_speed: float = 6
    wall_escape_turn_limit: float = 35
    approach_strafe_offset: float = 68
    orbit_strafe_offset: float = 92
    evade_strafe_offset: float = 102
    retreat_strafe_offset: float = 124
    evade_turns: int = 36
    max_speed: float = 8
    cruise_speed: float = 7
    panic_retreat_speed: float = -7
    search_wall_projection_speed: float = 6
    search_speed: float = 4
    search_turn_rate: float = 3
    collision_reverse_speed: float = -4
    flattener_direction_min_visits: float = 2.0
    flattener_direction_control_active: bool = _env_flag(
        "ROBOCODE_ADAPTIVE_FLATTENER_DIRECTION_CONTROL",
        default=True,
    )
    goto_surfing_active: bool = _env_flag("ROBOCODE_ADAPTIVE_GOTO_SURFING", default=True)

    def __post_init__(self) -> None:
        if not (self.panic_retreat_distance < self.close_reset_distance <= self.preferred_min_distance):
            raise ValueError("Duel fallback movement distances must be ordered")
        if self.preferred_min_distance >= self.preferred_max_distance:
            raise ValueError("Preferred movement distance band must be non-empty")
        if self.melee_pressure_min_distance >= self.melee_pressure_max_distance:
            raise ValueError("Melee movement distance band must be non-empty")


@dataclass(frozen=True)
class DuelMovementPolicy:
    potential_step: float = 205.0
    preferred_distance: float = 580.0
    min_distance: float = 430.0
    max_distance: float = 730.0
    critical_distance: float = 300.0
    wall_margin: float = 130.0
    centering_margin: float = 245.0
    enemy_repel_weight: float = 1.65
    close_repel_base: float = 0.4
    close_repel_scale: float = 3.0
    critical_repel_multiplier: float = 2.0
    wall_repel_weight: float = 4.0
    wall_axis_base: float = 0.35
    wall_axis_scale: float = 4.0
    orbit_weight: float = 1.15
    dodge_orbit_weight: float = 1.9
    close_orbit_scale: float = 0.75
    far_orbit_scale: float = 0.55
    range_attract_weight: float = 0.72
    far_attract_base: float = 0.35
    center_attract_weight: float = 0.48
    threat_repel_weight: float = 0.68
    threat_urgency_floor: float = 0.25
    evade_step_bonus: float = 45.0
    near_wall_step_bonus: float = 35.0

    def __post_init__(self) -> None:
        if not (self.critical_distance < self.min_distance < self.preferred_distance < self.max_distance):
            raise ValueError("Duel potential movement distances must be strictly ordered")
        if not 0.0 <= self.threat_urgency_floor <= 1.0:
            raise ValueError("Threat urgency floor must be between 0 and 1")


GUN_POLICY = GunPolicy()
FIRE_POLICY = FirePolicy()
TARGET_POLICY = TargetPolicy()
RADAR_POLICY = RadarPolicy()
MOVEMENT_POLICY = MovementPolicy()
DUEL_MOVEMENT_POLICY = DuelMovementPolicy()

RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_POLICY.search_rate,
    reacquire_overscan=RADAR_POLICY.visible_reacquire_overscan,
)
ENERGY_DROP_CONFIG = EnergyDropConfig()
FIRE_GATE = FireGate(
    FireGateConfig(
        fire_memory_turns=FIRE_POLICY.memory_turns,
        alignment_degrees=FIRE_POLICY.alignment_degrees,
        energy_margin=FIRE_POLICY.energy_margin,
        last_stand_energy=FIRE_POLICY.last_stand_energy,
        last_stand_energy_reserve=FIRE_POLICY.last_stand_energy_reserve,
        last_stand_max_distance=FIRE_POLICY.last_stand_max_distance,
        last_stand_alignment_degrees=FIRE_POLICY.last_stand_alignment_degrees,
    )
)
MOVEMENT_FLATTENING_CONFIG = MovementFlatteningConfig(
    bullet_shadow_enabled=True,
    goto_use_expected_waves=True,
    goto_expected_wave_min_confidence=0.62,
)
MINIMUM_RISK_CONFIG = MinimumRiskConfig(
    candidate_distances=(220.0, 320.0, 430.0, 560.0),
    field_margin=105.0,
    preferred_target_distance=500.0,
    max_target_distance=780.0,
    close_enemy_distance=330.0,
    travel_weight=0.0009,
    enemy_weight=36000.0,
    close_enemy_weight=55.0,
    target_distance_weight=0.0002,
    threat_lateral_weight=2.2,
    threat_distance_weight=12000.0,
    destination_commit_ticks=8,
    destination_switch_risk_ratio=0.86,
)


def _json_ready(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        dataclass_value = cast(Any, value)
        return {item.name: _json_ready(getattr(dataclass_value, item.name)) for item in fields(dataclass_value)}
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_ready(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def adaptive_config_snapshot() -> dict[str, object]:
    return {
        "profile": ADAPTIVE_CONFIG_PROFILE,
        "gun": _json_ready(GUN_POLICY),
        "fire": _json_ready(FIRE_POLICY),
        "target": _json_ready(TARGET_POLICY),
        "radar": _json_ready(RADAR_POLICY),
        "radar_lock": _json_ready(RADAR_CONFIG),
        "energy_drop": _json_ready(ENERGY_DROP_CONFIG),
        "movement": _json_ready(MOVEMENT_POLICY),
        "duel_movement": _json_ready(DUEL_MOVEMENT_POLICY),
        "movement_flattening": _json_ready(MOVEMENT_FLATTENING_CONFIG),
        "minimum_risk": _json_ready(MINIMUM_RISK_CONFIG),
    }


def adaptive_config_fingerprint(snapshot: dict[str, object] | None = None) -> str:
    effective = adaptive_config_snapshot() if snapshot is None else snapshot
    encoded = json.dumps(effective, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def adaptive_config_status_fields() -> dict[str, object]:
    snapshot = adaptive_config_snapshot()
    return {
        **gun_policy_status_fields(GUN_POLICY, ADAPTIVE_FORCE_GUN_MODES),
        "config_profile": ADAPTIVE_CONFIG_PROFILE,
        "config_fingerprint": adaptive_config_fingerprint(snapshot),
        "effective_config": snapshot,
    }

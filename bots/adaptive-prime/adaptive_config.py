import os
from dataclasses import dataclass, field

from bot_core.energy import EnergyDropConfig, FireGate, FireGateConfig
from bot_core.gun import (
    DEFAULT_LIVE_GUN_MODES,
    DynamicClusterPolicy,
    SHARED_GUN_POLICY_DEFAULTS,
    STANDARD_FORCE_GUN_MODES,
    gun_mode_from_env,
    gun_modes_from_env,
)
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.radar import RadarLockConfig


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
    min_switch_visits: int = 45
    min_switch_score: float = 0.10
    global_source_min_switch_visits: int = 60
    global_source_min_switch_score: float = 0.16
    trusted_source_min_switch_visits: int = 32
    trusted_source_min_switch_score: float = 0.08


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
    displacement_markov_enabled: bool = _env_flag("ROBOCODE_ADAPTIVE_DISPLACEMENT_MARKOV", True)
    traditional_gf: TraditionalGfPolicy = field(default_factory=TraditionalGfPolicy)
    anti_surfer_min_switch_visits: int = 95
    anti_surfer_min_switch_score: float = 0.28
    switch_confidence_visits: int = 120
    switch_confidence_penalty: float = 0.04
    primary_confidence_penalty_scale: float = 0.25
    switch_diagnostics_interval: int = 24
    dynamic_cluster: DynamicClusterPolicy = ADAPTIVE_DYNAMIC_CLUSTER_POLICY


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
    last_stand_energy: float = 7
    last_stand_firepower: float = 0.6
    last_stand_energy_reserve: float = 0.1
    last_stand_max_distance: float = 320
    last_stand_alignment_degrees: float = 3
    enemy_fire_min_drop: float = 0.1
    enemy_fire_max_drop: float = 3.0
    enemy_fire_scan_gap_turns: int = 4
    enemy_fire_close_collision_distance: float = 75
    enemy_fire_close_collision_max_drop: float = 0.8
    enemy_fire_active_evasion_min_distance: float = 0
    melee_fire_active_evasion_min_distance: float = 0
    gun_heat_waves_active: bool = True
    gun_heat_wave_min_distance: float = 220
    gun_heat_wave_max_target_age: int = 2


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


@dataclass(frozen=True)
class RadarPolicy:
    lock_rate: float = 24
    search_rate: float = 18
    reacquire_rate: float = 24
    lost_sweep_rate: float = 24
    gun_search_rate: float = 18
    reacquire_min_error: float = 8
    reacquire_overshoot: float = 8
    reacquire_widen_per_turn: float = 2
    reacquire_max_overshoot: float = 42
    lock_overscan: float = 12
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
    approach_strafe_offset: float = 68
    orbit_strafe_offset: float = 92
    evade_strafe_offset: float = 102
    retreat_strafe_offset: float = 124
    evade_turns: int = 36
    flattener_active: bool = True
    goto_surfing_active: bool = True


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
    wall_repel_weight: float = 4.0
    orbit_weight: float = 1.15
    dodge_orbit_weight: float = 1.9
    range_attract_weight: float = 0.72
    center_attract_weight: float = 0.48
    threat_repel_weight: float = 0.68


GUN_POLICY = GunPolicy()
FIRE_POLICY = FirePolicy()
TARGET_POLICY = TargetPolicy()
RADAR_POLICY = RadarPolicy()
MOVEMENT_POLICY = MovementPolicy()
DUEL_MOVEMENT_POLICY = DuelMovementPolicy()
RADAR_CONFIG = RadarLockConfig(
    search_rate=RADAR_POLICY.search_rate,
    lock_rate=RADAR_POLICY.lock_rate,
    reacquire_rate=RADAR_POLICY.reacquire_rate,
    reacquire_min_error=RADAR_POLICY.reacquire_min_error,
    lock_overscan=RADAR_POLICY.lock_overscan,
    reacquire_overscan=RADAR_POLICY.visible_reacquire_overscan,
)
ENERGY_DROP_CONFIG = EnergyDropConfig(
    min_fire_power=FIRE_POLICY.enemy_fire_min_drop,
    max_fire_power=FIRE_POLICY.enemy_fire_max_drop,
    max_scan_gap=FIRE_POLICY.enemy_fire_scan_gap_turns,
    close_collision_distance=FIRE_POLICY.enemy_fire_close_collision_distance,
    close_collision_max_drop=FIRE_POLICY.enemy_fire_close_collision_max_drop,
)
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

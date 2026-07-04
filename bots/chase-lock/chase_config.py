import os
from dataclasses import dataclass

from bot_core.energy import EnergyDropConfig, FireGate, FireGateConfig
from bot_core.gun import (
    DEFAULT_LIVE_GUN_MODES,
    DynamicClusterPolicy,
    SHARED_GUN_POLICY_DEFAULTS,
    STANDARD_FORCE_GUN_MODES,
    gun_mode_from_env,
    gun_modes_from_env,
)
from bot_core.radar import RadarLockConfig


CHASE_SELECTABLE_GUN_MODES = DEFAULT_LIVE_GUN_MODES
CHASE_FORCE_GUN_MODES = STANDARD_FORCE_GUN_MODES
CHASE_DYNAMIC_CLUSTER_POLICY = DynamicClusterPolicy.from_env("ROBOCODE_CHASE")


def _selectable_gun_modes() -> frozenset[str]:
    return gun_modes_from_env("ROBOCODE_CHASE", CHASE_SELECTABLE_GUN_MODES, CHASE_FORCE_GUN_MODES)


def _forced_gun_mode() -> str | None:
    return gun_mode_from_env("ROBOCODE_CHASE", CHASE_FORCE_GUN_MODES)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


@dataclass(frozen=True)
class GunPolicy:
    selectable_modes: frozenset[str] = _selectable_gun_modes()
    forced_mode: str | None = _forced_gun_mode()
    eval_waves_enabled: bool = _env_flag("ROBOCODE_CHASE_GUN_EVAL")
    eval_wave_min_interval: int = _env_int("ROBOCODE_CHASE_GUN_EVAL_INTERVAL", 8)
    knn_min_samples: int = SHARED_GUN_POLICY_DEFAULTS.knn_min_samples
    min_visits: int = SHARED_GUN_POLICY_DEFAULTS.min_visits
    switch_margin: float = SHARED_GUN_POLICY_DEFAULTS.switch_margin
    primary_over_fallback_margin: float = SHARED_GUN_POLICY_DEFAULTS.primary_over_fallback_margin
    situational_over_primary_margin: float = SHARED_GUN_POLICY_DEFAULTS.situational_over_primary_margin
    primary_slump_visits: int = SHARED_GUN_POLICY_DEFAULTS.primary_slump_visits
    primary_slump_score: float = SHARED_GUN_POLICY_DEFAULTS.primary_slump_score
    primary_slump_situational_margin: float = SHARED_GUN_POLICY_DEFAULTS.primary_slump_situational_margin
    min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.min_switch_score
    traditional_gf_min_switch_visits: int = SHARED_GUN_POLICY_DEFAULTS.traditional_gf_min_switch_visits
    traditional_gf_min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.traditional_gf_min_switch_score
    displacement_min_switch_visits: int = SHARED_GUN_POLICY_DEFAULTS.displacement_min_switch_visits
    displacement_min_switch_score: float = SHARED_GUN_POLICY_DEFAULTS.displacement_min_switch_score
    displacement_markov_enabled: bool = _env_flag("ROBOCODE_CHASE_DISPLACEMENT_MARKOV", True)
    switch_diagnostics_interval: int = 30
    dynamic_cluster: DynamicClusterPolicy = CHASE_DYNAMIC_CLUSTER_POLICY


@dataclass(frozen=True)
class FirePolicy:
    alignment_degrees: float = 7
    memory_turns: int = 1
    finish_target_energy: float = 18
    melee_finish_target_energy: float = 28
    finish_distance: float = 240
    enemy_fire_min_drop: float = 0.1
    enemy_fire_max_drop: float = 3.0
    enemy_fire_scan_gap_turns: int = 4
    enemy_fire_close_collision_distance: float = 75
    enemy_fire_close_collision_max_drop: float = 0.8
    enemy_fire_active_evasion_min_distance: float = 220
    melee_fire_active_evasion_min_distance: float = 120
    gun_heat_waves_active: bool = True
    gun_heat_wave_min_distance: float = 220
    gun_heat_wave_max_target_age: int = 2


@dataclass(frozen=True)
class TargetPolicy:
    memory_turns: int = 24
    reacquire_turns: int = 4
    drop_lost_turns: int = 9
    current_target_bonus: float = 80
    recent_threat_bonus: float = 120
    melee_current_target_bonus: float = 28
    melee_recent_threat_bonus: float = 48
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
    preferred_min_distance: float = 320
    preferred_max_distance: float = 470
    melee_pressure_min_distance: float = 260
    melee_pressure_max_distance: float = 430
    panic_retreat_distance: float = 160
    melee_panic_retreat_distance: float = 180
    close_reset_distance: float = 285
    melee_close_reset_distance: float = 240
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


GUN_POLICY = GunPolicy()
FIRE_POLICY = FirePolicy()
TARGET_POLICY = TargetPolicy()
RADAR_POLICY = RadarPolicy()
MOVEMENT_POLICY = MovementPolicy()


def build_radar_config() -> RadarLockConfig:
    return RadarLockConfig(
        search_rate=RADAR_POLICY.search_rate,
        lock_rate=RADAR_POLICY.lock_rate,
        reacquire_rate=RADAR_POLICY.reacquire_rate,
        reacquire_min_error=RADAR_POLICY.reacquire_min_error,
        lock_overscan=RADAR_POLICY.lock_overscan,
        reacquire_overscan=RADAR_POLICY.visible_reacquire_overscan,
    )


def build_energy_drop_config() -> EnergyDropConfig:
    return EnergyDropConfig(
        min_fire_power=FIRE_POLICY.enemy_fire_min_drop,
        max_fire_power=FIRE_POLICY.enemy_fire_max_drop,
        max_scan_gap=FIRE_POLICY.enemy_fire_scan_gap_turns,
        close_collision_distance=FIRE_POLICY.enemy_fire_close_collision_distance,
        close_collision_max_drop=FIRE_POLICY.enemy_fire_close_collision_max_drop,
    )


def build_fire_gate() -> FireGate:
    return FireGate(
        FireGateConfig(
            fire_memory_turns=FIRE_POLICY.memory_turns,
            alignment_degrees=FIRE_POLICY.alignment_degrees,
            energy_margin=5,
        )
    )

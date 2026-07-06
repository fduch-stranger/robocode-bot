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


SWEEP_SELECTABLE_GUN_MODES = DEFAULT_LIVE_GUN_MODES
SWEEP_FORCE_GUN_MODES = STANDARD_FORCE_GUN_MODES
SWEEP_DYNAMIC_CLUSTER_POLICY = DynamicClusterPolicy.from_env("ROBOCODE_SWEEP")


def _selectable_gun_modes() -> frozenset[str]:
    return gun_modes_from_env("ROBOCODE_SWEEP", SWEEP_SELECTABLE_GUN_MODES, SWEEP_FORCE_GUN_MODES)


def _forced_gun_mode() -> str | None:
    return gun_mode_from_env("ROBOCODE_SWEEP", SWEEP_FORCE_GUN_MODES)


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
    eval_waves_enabled: bool = _env_flag("ROBOCODE_SWEEP_GUN_EVAL")
    eval_wave_min_interval: int = _env_int("ROBOCODE_SWEEP_GUN_EVAL_INTERVAL", 8)
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
    displacement_markov_enabled: bool = _env_flag("ROBOCODE_SWEEP_DISPLACEMENT_MARKOV", True)
    switch_diagnostics_interval: int = 24
    dynamic_cluster: DynamicClusterPolicy = SWEEP_DYNAMIC_CLUSTER_POLICY


@dataclass(frozen=True)
class FirePolicy:
    alignment_degrees: float = 8
    memory_turns: int = 4
    enemy_fire_min_drop: float = 0.1
    enemy_fire_max_drop: float = 3.0
    enemy_fire_scan_gap_turns: int = 4
    enemy_fire_close_collision_distance: float = 75
    enemy_fire_close_collision_max_drop: float = 0.8
    low_energy_hold: float = 18
    critical_energy_hold: float = 10
    energy_margin: float = 6
    low_energy_max_distance: float = 220
    last_stand_energy: float = 7
    last_stand_firepower: float = 0.6
    last_stand_energy_reserve: float = 0.1
    last_stand_max_distance: float = 320
    last_stand_alignment_degrees: float = 3
    far_alignment_distance: float = 360
    far_alignment_degrees: float = 5


@dataclass(frozen=True)
class TargetPolicy:
    memory_turns: int = 30
    current_target_bonus: float = 160
    switch_margin: float = 95
    force_switch_target_age: int = 10


@dataclass(frozen=True)
class RadarPolicy:
    search_rate: float = 16
    lock_rate: float = 24
    reacquire_rate: float = 24
    rescan_interval: int = 30
    rescan_turns: int = 5
    reacquire_min_error: float = 8
    lock_overscan: float = 12
    reacquire_overscan: float = 24


@dataclass(frozen=True)
class MovementPolicy:
    field_margin: float = 18
    wall_margin: float = 45
    wall_clear_margin: float = 75
    wall_lookahead_ticks: int = 12
    wall_escape_turns: int = 12
    wall_escape_speed: float = 7
    sweep_speed: float = 7
    sweep_turn_rate: float = 3.5
    flattener_strafe_offset: float = 92
    flattener_switch_margin: float = 2.2
    flattener_switch_cooldown: int = 30
    wall_hit_flip_cooldown: int = 8
    feint_ticks: int = 12
    feint_cooldown: int = 42


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
        rescan_interval=RADAR_POLICY.rescan_interval,
        rescan_turns=RADAR_POLICY.rescan_turns,
        reacquire_min_error=RADAR_POLICY.reacquire_min_error,
        lock_overscan=RADAR_POLICY.lock_overscan,
        reacquire_overscan=RADAR_POLICY.reacquire_overscan,
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
            energy_margin=FIRE_POLICY.energy_margin,
            critical_energy_hold=FIRE_POLICY.critical_energy_hold,
            low_energy_hold=FIRE_POLICY.low_energy_hold,
            low_energy_max_distance=FIRE_POLICY.low_energy_max_distance,
            last_stand_energy=FIRE_POLICY.last_stand_energy,
            last_stand_energy_reserve=FIRE_POLICY.last_stand_energy_reserve,
            last_stand_max_distance=FIRE_POLICY.last_stand_max_distance,
            last_stand_alignment_degrees=FIRE_POLICY.last_stand_alignment_degrees,
            far_alignment_distance=FIRE_POLICY.far_alignment_distance,
            far_alignment_degrees=FIRE_POLICY.far_alignment_degrees,
        )
    )

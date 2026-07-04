import os
from dataclasses import dataclass, fields
from typing import cast

from bot_core.gun.config import GunSelectorConfig
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig


DEFAULT_LIVE_GUN_MODES = frozenset({"linear", "traditional_gf", "dynamic_cluster", "displacement"})
STANDARD_FORCE_GUN_MODES = DEFAULT_LIVE_GUN_MODES | frozenset({
    "anti_surfer",
    "head_on",
    "linear_wall_aware",
})
DEFAULT_MODE_PRIORITY = (
    "linear",
    "dynamic_cluster",
    "traditional_gf",
    "linear_wall_aware",
    "head_on",
    "displacement",
    "anti_surfer",
)


@dataclass(frozen=True)
class SharedGunPolicyDefaults:
    knn_min_samples: int = 30
    min_visits: int = 12
    switch_margin: float = 0.05
    primary_over_fallback_margin: float = 0.02
    situational_over_primary_margin: float = 0.08
    primary_slump_visits: int = 80
    primary_slump_score: float = 0.13
    primary_slump_situational_margin: float = 0.025
    min_switch_score: float = 0.03
    traditional_gf_min_switch_visits: int = 45
    traditional_gf_min_switch_score: float = 0.10
    displacement_min_switch_visits: int = 60
    displacement_min_switch_score: float = 0.08
    displacement_markov_enabled: bool = True


SHARED_GUN_POLICY_DEFAULTS = SharedGunPolicyDefaults()
DYNAMIC_CLUSTER_DEFAULTS = DynamicClusterGunConfig()


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def gun_mode_from_env(prefix: str, allowed_modes: frozenset[str]) -> str | None:
    per_bot_mode = os.environ.get(f"{prefix}_GUN_MODE", "").strip()
    if per_bot_mode:
        return per_bot_mode if per_bot_mode in allowed_modes else None
    global_mode = os.environ.get("ROBOCODE_GUN_MODE", "").strip()
    if global_mode in allowed_modes:
        return global_mode
    return None


def gun_modes_from_env(
    prefix: str,
    default_modes: frozenset[str],
    allowed_modes: frozenset[str],
) -> frozenset[str]:
    per_bot_modes = _parse_gun_modes(os.environ.get(f"{prefix}_GUN_SET", ""))
    if per_bot_modes:
        return frozenset(per_bot_modes) if all(mode in allowed_modes for mode in per_bot_modes) else default_modes
    global_modes = _parse_gun_modes(os.environ.get("ROBOCODE_GUN_SET", ""))
    if global_modes and all(mode in allowed_modes for mode in global_modes):
        return frozenset(global_modes)
    return default_modes


def _parse_gun_modes(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.strip().replace(",", " ").split())


def default_gun_mode_for(selectable_modes: frozenset[str]) -> str:
    for mode in DEFAULT_MODE_PRIORITY:
        if mode in selectable_modes:
            return mode
    return sorted(selectable_modes)[0]


def gun_policy_status_fields(policy: object, force_modes: frozenset[str]) -> dict[str, object]:
    return {
        "selectable_guns": sorted(getattr(policy, "selectable_modes", ())),
        "force_guns": sorted(force_modes),
        "forced_gun": getattr(policy, "forced_mode", None),
        "eval_waves": bool(getattr(policy, "eval_waves_enabled", False)),
    }


@dataclass(frozen=True)
class DynamicClusterPolicy:
    bandwidth: float = DYNAMIC_CLUSTER_DEFAULTS.bandwidth
    bandwidth_min: float = DYNAMIC_CLUSTER_DEFAULTS.bandwidth_min
    bandwidth_max: float = DYNAMIC_CLUSTER_DEFAULTS.bandwidth_max
    bandwidth_hit_width_scale: float = DYNAMIC_CLUSTER_DEFAULTS.bandwidth_hit_width_scale
    second_peak_suppression_bandwidth_scale: float = DYNAMIC_CLUSTER_DEFAULTS.second_peak_suppression_bandwidth_scale
    second_peak_suppression_bin_scale: float = DYNAMIC_CLUSTER_DEFAULTS.second_peak_suppression_bin_scale
    centroid_window_bandwidth_scale: float = DYNAMIC_CLUSTER_DEFAULTS.centroid_window_bandwidth_scale
    centroid_window_bin_scale: float = DYNAMIC_CLUSTER_DEFAULTS.centroid_window_bin_scale
    ambiguous_peak_score_ratio: float = DYNAMIC_CLUSTER_DEFAULTS.ambiguous_peak_score_ratio
    ambiguous_peak_centering_factor: float = DYNAMIC_CLUSTER_DEFAULTS.ambiguous_peak_centering_factor
    confidence_mature_samples: int = DYNAMIC_CLUSTER_DEFAULTS.confidence_mature_samples
    confidence_max_neighbor_distance: float = DYNAMIC_CLUSTER_DEFAULTS.confidence_max_neighbor_distance
    confidence_peak_margin_reference: float = DYNAMIC_CLUSTER_DEFAULTS.confidence_peak_margin_reference
    context_weighting_enabled: bool = DYNAMIC_CLUSTER_DEFAULTS.context_weighting_enabled
    tag_match_bonus: float = DYNAMIC_CLUSTER_DEFAULTS.tag_match_bonus
    flight_time_mismatch_penalty: float = DYNAMIC_CLUSTER_DEFAULTS.flight_time_mismatch_penalty
    wall_escape_mismatch_penalty: float = DYNAMIC_CLUSTER_DEFAULTS.wall_escape_mismatch_penalty
    lateral_confidence_penalty: float = DYNAMIC_CLUSTER_DEFAULTS.lateral_confidence_penalty
    context_weight_min: float = DYNAMIC_CLUSTER_DEFAULTS.context_weight_min
    context_weight_max: float = DYNAMIC_CLUSTER_DEFAULTS.context_weight_max
    shot_quality_enabled: bool = DYNAMIC_CLUSTER_DEFAULTS.shot_quality_enabled
    shot_quality_good_threshold: float = DYNAMIC_CLUSTER_DEFAULTS.shot_quality_good_threshold
    shot_quality_weak_threshold: float = DYNAMIC_CLUSTER_DEFAULTS.shot_quality_weak_threshold
    shot_quality_medium_power_scale: float = DYNAMIC_CLUSTER_DEFAULTS.shot_quality_medium_power_scale
    shot_quality_low_power_scale: float = DYNAMIC_CLUSTER_DEFAULTS.shot_quality_low_power_scale

    @classmethod
    def from_env(cls, prefix: str) -> "DynamicClusterPolicy":
        return cls(
            bandwidth=_env_float(f"{prefix}_DYNAMIC_BANDWIDTH", DYNAMIC_CLUSTER_DEFAULTS.bandwidth, minimum=0.001),
            bandwidth_min=_env_float(
                f"{prefix}_DYNAMIC_BANDWIDTH_MIN",
                DYNAMIC_CLUSTER_DEFAULTS.bandwidth_min,
                minimum=0.001,
            ),
            bandwidth_max=_env_float(
                f"{prefix}_DYNAMIC_BANDWIDTH_MAX",
                DYNAMIC_CLUSTER_DEFAULTS.bandwidth_max,
                minimum=0.001,
            ),
            bandwidth_hit_width_scale=_env_float(
                f"{prefix}_DYNAMIC_BANDWIDTH_HIT_WIDTH_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.bandwidth_hit_width_scale,
                minimum=0.0,
            ),
            second_peak_suppression_bandwidth_scale=_env_float(
                f"{prefix}_DYNAMIC_SECOND_PEAK_SUPPRESSION_BANDWIDTH_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.second_peak_suppression_bandwidth_scale,
                minimum=0.0,
            ),
            second_peak_suppression_bin_scale=_env_float(
                f"{prefix}_DYNAMIC_SECOND_PEAK_SUPPRESSION_BIN_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.second_peak_suppression_bin_scale,
                minimum=0.0,
            ),
            centroid_window_bandwidth_scale=_env_float(
                f"{prefix}_DYNAMIC_CENTROID_WINDOW_BANDWIDTH_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.centroid_window_bandwidth_scale,
                minimum=0.0,
            ),
            centroid_window_bin_scale=_env_float(
                f"{prefix}_DYNAMIC_CENTROID_WINDOW_BIN_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.centroid_window_bin_scale,
                minimum=0.0,
            ),
            ambiguous_peak_score_ratio=_env_float(
                f"{prefix}_DYNAMIC_AMBIGUOUS_PEAK_SCORE_RATIO",
                DYNAMIC_CLUSTER_DEFAULTS.ambiguous_peak_score_ratio,
                minimum=0.0,
                maximum=1.0,
            ),
            ambiguous_peak_centering_factor=_env_float(
                f"{prefix}_DYNAMIC_AMBIGUOUS_PEAK_CENTERING_FACTOR",
                DYNAMIC_CLUSTER_DEFAULTS.ambiguous_peak_centering_factor,
                minimum=0.0,
                maximum=1.0,
            ),
            confidence_mature_samples=_env_int(
                f"{prefix}_DYNAMIC_CONFIDENCE_MATURE_SAMPLES",
                DYNAMIC_CLUSTER_DEFAULTS.confidence_mature_samples,
                minimum=1,
            ),
            confidence_max_neighbor_distance=_env_float(
                f"{prefix}_DYNAMIC_CONFIDENCE_MAX_NEIGHBOR_DISTANCE",
                DYNAMIC_CLUSTER_DEFAULTS.confidence_max_neighbor_distance,
                minimum=0.001,
            ),
            confidence_peak_margin_reference=_env_float(
                f"{prefix}_DYNAMIC_CONFIDENCE_PEAK_MARGIN_REFERENCE",
                DYNAMIC_CLUSTER_DEFAULTS.confidence_peak_margin_reference,
                minimum=0.001,
            ),
            context_weighting_enabled=not _env_flag(f"{prefix}_DYNAMIC_CONTEXT_WEIGHTING_DISABLED"),
            tag_match_bonus=_env_float(
                f"{prefix}_DYNAMIC_TAG_MATCH_BONUS",
                DYNAMIC_CLUSTER_DEFAULTS.tag_match_bonus,
                minimum=0.0,
            ),
            flight_time_mismatch_penalty=_env_float(
                f"{prefix}_DYNAMIC_FLIGHT_TIME_MISMATCH_PENALTY",
                DYNAMIC_CLUSTER_DEFAULTS.flight_time_mismatch_penalty,
                minimum=0.0,
                maximum=1.0,
            ),
            wall_escape_mismatch_penalty=_env_float(
                f"{prefix}_DYNAMIC_WALL_ESCAPE_MISMATCH_PENALTY",
                DYNAMIC_CLUSTER_DEFAULTS.wall_escape_mismatch_penalty,
                minimum=0.0,
                maximum=1.0,
            ),
            lateral_confidence_penalty=_env_float(
                f"{prefix}_DYNAMIC_LATERAL_CONFIDENCE_PENALTY",
                DYNAMIC_CLUSTER_DEFAULTS.lateral_confidence_penalty,
                minimum=0.0,
                maximum=1.0,
            ),
            context_weight_min=_env_float(
                f"{prefix}_DYNAMIC_CONTEXT_WEIGHT_MIN",
                DYNAMIC_CLUSTER_DEFAULTS.context_weight_min,
                minimum=0.0,
            ),
            context_weight_max=_env_float(
                f"{prefix}_DYNAMIC_CONTEXT_WEIGHT_MAX",
                DYNAMIC_CLUSTER_DEFAULTS.context_weight_max,
                minimum=0.0,
            ),
            shot_quality_enabled=not _env_flag(f"{prefix}_DYNAMIC_SHOT_QUALITY_DISABLED"),
            shot_quality_good_threshold=_env_float(
                f"{prefix}_DYNAMIC_SHOT_QUALITY_GOOD_THRESHOLD",
                DYNAMIC_CLUSTER_DEFAULTS.shot_quality_good_threshold,
                minimum=0.0,
                maximum=1.0,
            ),
            shot_quality_weak_threshold=_env_float(
                f"{prefix}_DYNAMIC_SHOT_QUALITY_WEAK_THRESHOLD",
                DYNAMIC_CLUSTER_DEFAULTS.shot_quality_weak_threshold,
                minimum=0.0,
                maximum=1.0,
            ),
            shot_quality_medium_power_scale=_env_float(
                f"{prefix}_DYNAMIC_SHOT_QUALITY_MEDIUM_POWER_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.shot_quality_medium_power_scale,
                minimum=0.0,
                maximum=1.0,
            ),
            shot_quality_low_power_scale=_env_float(
                f"{prefix}_DYNAMIC_SHOT_QUALITY_LOW_POWER_SCALE",
                DYNAMIC_CLUSTER_DEFAULTS.shot_quality_low_power_scale,
                minimum=0.0,
                maximum=1.0,
            ),
        )

    def __post_init__(self) -> None:
        if self.bandwidth_min > self.bandwidth_max:
            bandwidth_min = self.bandwidth_min
            bandwidth_max = self.bandwidth_max
            object.__setattr__(self, "bandwidth_min", bandwidth_max)
            object.__setattr__(self, "bandwidth_max", bandwidth_min)
        if self.context_weight_min > self.context_weight_max:
            context_weight_min = self.context_weight_min
            context_weight_max = self.context_weight_max
            object.__setattr__(self, "context_weight_min", context_weight_max)
            object.__setattr__(self, "context_weight_max", context_weight_min)
        if self.shot_quality_weak_threshold > self.shot_quality_good_threshold:
            weak_threshold = self.shot_quality_weak_threshold
            good_threshold = self.shot_quality_good_threshold
            object.__setattr__(self, "shot_quality_weak_threshold", good_threshold)
            object.__setattr__(self, "shot_quality_good_threshold", weak_threshold)


def selector_config_from_policy(policy: object) -> GunSelectorConfig:
    defaults = GunSelectorConfig()
    values = {field.name: getattr(policy, field.name, getattr(defaults, field.name)) for field in fields(GunSelectorConfig)}
    selectable_modes = cast(frozenset[str], values["selectable_modes"])
    if values["default_mode"] not in selectable_modes:
        values["default_mode"] = default_gun_mode_for(selectable_modes)
    return GunSelectorConfig(**values)


def dynamic_cluster_config_from_policy(policy: object) -> DynamicClusterGunConfig:
    defaults = SHARED_GUN_POLICY_DEFAULTS
    dynamic = getattr(policy, "dynamic_cluster", DynamicClusterPolicy())
    return DynamicClusterGunConfig(
        min_samples=getattr(policy, "knn_min_samples", defaults.knn_min_samples),
        min_switch_visits=getattr(policy, "min_visits", defaults.min_visits),
        min_switch_score=getattr(policy, "min_switch_score", defaults.min_switch_score),
        bandwidth=dynamic.bandwidth,
        bandwidth_min=dynamic.bandwidth_min,
        bandwidth_max=dynamic.bandwidth_max,
        bandwidth_hit_width_scale=dynamic.bandwidth_hit_width_scale,
        second_peak_suppression_bandwidth_scale=dynamic.second_peak_suppression_bandwidth_scale,
        second_peak_suppression_bin_scale=dynamic.second_peak_suppression_bin_scale,
        centroid_window_bandwidth_scale=dynamic.centroid_window_bandwidth_scale,
        centroid_window_bin_scale=dynamic.centroid_window_bin_scale,
        ambiguous_peak_score_ratio=dynamic.ambiguous_peak_score_ratio,
        ambiguous_peak_centering_factor=dynamic.ambiguous_peak_centering_factor,
        confidence_mature_samples=dynamic.confidence_mature_samples,
        confidence_max_neighbor_distance=dynamic.confidence_max_neighbor_distance,
        confidence_peak_margin_reference=dynamic.confidence_peak_margin_reference,
        context_weighting_enabled=dynamic.context_weighting_enabled,
        tag_match_bonus=dynamic.tag_match_bonus,
        flight_time_mismatch_penalty=dynamic.flight_time_mismatch_penalty,
        wall_escape_mismatch_penalty=dynamic.wall_escape_mismatch_penalty,
        lateral_confidence_penalty=dynamic.lateral_confidence_penalty,
        context_weight_min=dynamic.context_weight_min,
        context_weight_max=dynamic.context_weight_max,
        shot_quality_enabled=dynamic.shot_quality_enabled,
        shot_quality_good_threshold=dynamic.shot_quality_good_threshold,
        shot_quality_weak_threshold=dynamic.shot_quality_weak_threshold,
        shot_quality_medium_power_scale=dynamic.shot_quality_medium_power_scale,
        shot_quality_low_power_scale=dynamic.shot_quality_low_power_scale,
    )


def displacement_config_from_policy(policy: object) -> DisplacementGunConfig:
    defaults = SHARED_GUN_POLICY_DEFAULTS
    return DisplacementGunConfig(
        min_switch_visits=getattr(
            policy,
            "displacement_min_switch_visits",
            defaults.displacement_min_switch_visits,
        ),
        min_switch_score=getattr(
            policy,
            "displacement_min_switch_score",
            defaults.displacement_min_switch_score,
        ),
        markov_enabled=getattr(
            policy,
            "displacement_markov_enabled",
            defaults.displacement_markov_enabled,
        ),
    )

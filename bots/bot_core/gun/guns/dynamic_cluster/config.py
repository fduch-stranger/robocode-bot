from dataclasses import dataclass

from bot_core.gun.config import GunModePolicy, GunModeTraits


@dataclass(frozen=True)
class DynamicClusterGunConfig:
    max_samples: int = 1200
    max_samples_per_target: int = 900
    min_samples: int = 60
    blend_samples: int = 150
    neighbors: int = 17
    decay_half_life: float = 0.0
    min_effective_samples: float = 0.0
    guess_factor_bins: int = 31
    bandwidth: float = 0.18
    bandwidth_min: float = 0.12
    bandwidth_max: float = 0.30
    bandwidth_hit_width_scale: float = 1.5
    second_peak_suppression_bandwidth_scale: float = 1.0
    second_peak_suppression_bin_scale: float = 1.5
    centroid_window_bandwidth_scale: float = 1.0
    centroid_window_bin_scale: float = 1.5
    centroid_min_weight: float = 1e-6
    ambiguous_peak_score_ratio: float = 0.85
    ambiguous_peak_centering_factor: float = 0.8
    confidence_mature_samples: int = 150
    confidence_max_neighbor_distance: float = 1.2
    confidence_peak_margin_reference: float = 3.0
    min_switch_visits: int = 90
    min_switch_score: float = 0.30
    context_weighting_enabled: bool = True
    tag_match_bonus: float = 0.12
    flight_time_mismatch_penalty: float = 0.18
    wall_escape_mismatch_penalty: float = 0.12
    lateral_confidence_penalty: float = 0.12
    context_weight_min: float = 0.25
    context_weight_max: float = 1.5
    shot_quality_enabled: bool = True
    shot_quality_good_threshold: float = 0.55
    shot_quality_weak_threshold: float = 0.35
    shot_quality_medium_power_scale: float = 0.75
    shot_quality_low_power_scale: float = 0.55

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            "dynamic_cluster",
            self.min_switch_visits,
            self.min_switch_score,
            GunModeTraits(
                role="primary",
                family="knn_gf",
                phases=frozenset({"warmup", "late"}),
                strengths=frozenset({"surfer", "nonlinear_mover", "adaptive_mover"}),
            ),
        )

__all__ = ["DynamicClusterGunConfig"]

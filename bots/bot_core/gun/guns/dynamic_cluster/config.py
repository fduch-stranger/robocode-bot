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
    min_switch_visits: int = 90
    min_switch_score: float = 0.30

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

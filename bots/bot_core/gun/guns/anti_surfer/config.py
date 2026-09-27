from dataclasses import dataclass

from bot_core.gun.config import GunModePolicy, GunModeTraits
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig


@dataclass(frozen=True)
class AntiSurferGunConfig(DynamicClusterGunConfig):
    """Dynamic Cluster tuned to follow a surfer that adapts to being hit.

    The differences from the primary Dynamic Cluster are a short recency
    half-life (in observed waves) and few neighbors, so the aim tracks where
    the target has gone lately rather than its long-run profile.
    """

    neighbors: int = 7
    decay_half_life: float = 90.0
    min_samples: int = 30

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            "anti_surfer",
            self.min_switch_visits,
            self.min_switch_score,
            GunModeTraits(
                role="situational",
                family="knn_gf",
                phases=frozenset({"late"}),
                strengths=frozenset({"surfer", "adaptive_mover"}),
            ),
        )


__all__ = ["AntiSurferGunConfig"]

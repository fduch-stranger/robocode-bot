from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.dynamic_cluster.gun import DynamicClusterGun


class AntiSurferGun(DynamicClusterGun):
    """A second Dynamic Cluster learner with recency weighting and few neighbors."""

    mode = "anti_surfer"

    def __init__(self, config: AntiSurferGunConfig) -> None:
        super().__init__(config)


__all__ = ["AntiSurferGun"]

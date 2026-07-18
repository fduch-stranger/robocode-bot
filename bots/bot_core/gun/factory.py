from __future__ import annotations

from bot_core.gun.config import GunRuntimeConfig, GunScoringConfig, GunSelectorConfig, GunSystemConfig
from bot_core.gun.context import TargetHistoryStore
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.anti_surfer.gun import AntiSurferGun
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.guns.displacement.gun import DisplacementGun
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.gun import DynamicClusterGun
from bot_core.gun.guns.head_on.gun import HeadOnGun
from bot_core.gun.guns.linear.gun import LinearGun
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.gun.guns.traditional_gf.gun import TraditionalGfGun


def standard_runtime_config(
    *,
    system: GunSystemConfig | None = None,
    selector: GunSelectorConfig | None = None,
    scoring: GunScoringConfig | None = None,
    head_on_min_switch_score: float = 0.45,
    min_visits: int = 90,
    min_switch_score: float = 0.30,
    displacement: DisplacementGunConfig | None = None,
    dynamic_cluster: DynamicClusterGunConfig | None = None,
    traditional_gf: TraditionalGfGunConfig | None = None,
    anti_surfer: AntiSurferGunConfig | None = None,
) -> GunRuntimeConfig:
    system_config = system or GunSystemConfig()
    selector_config = selector or GunSelectorConfig()
    scoring_config = scoring or GunScoringConfig()
    displacement_config = displacement or DisplacementGunConfig(
        min_switch_visits=min_visits,
        min_switch_score=min_switch_score,
    )
    dynamic_cluster_config = dynamic_cluster or DynamicClusterGunConfig(
        min_switch_visits=min_visits,
        min_switch_score=min_switch_score,
    )
    traditional_gf_config = traditional_gf or TraditionalGfGunConfig()
    anti_surfer_config = anti_surfer or AntiSurferGunConfig()

    def component_factory(history: TargetHistoryStore):
        return [
            HeadOnGun(min_switch_visits=min_visits, min_switch_score=head_on_min_switch_score),
            LinearGun(min_switch_visits=min_visits, min_switch_score=min_switch_score),
            DisplacementGun(displacement_config, history),
            TraditionalGfGun(traditional_gf_config),
            AntiSurferGun(anti_surfer_config),
            DynamicClusterGun(dynamic_cluster_config),
        ]

    return GunRuntimeConfig(
        system=system_config,
        selector=selector_config,
        scoring=scoring_config,
        component_factory=component_factory,
    )


__all__ = ["standard_runtime_config"]

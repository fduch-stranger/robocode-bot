from dataclasses import dataclass, fields

from bot_core.gun.config import GunSelectorConfig


DEFAULT_LIVE_GUN_MODES = frozenset({"linear", "traditional_gf", "dynamic_cluster"})


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


SHARED_GUN_POLICY_DEFAULTS = SharedGunPolicyDefaults()


def selector_config_from_policy(policy: object) -> GunSelectorConfig:
    defaults = GunSelectorConfig()
    values = {field.name: getattr(policy, field.name, getattr(defaults, field.name)) for field in fields(GunSelectorConfig)}
    return GunSelectorConfig(**values)

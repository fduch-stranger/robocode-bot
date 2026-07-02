from dataclasses import dataclass

from bot_core.gun.config import GunModePolicy


@dataclass(frozen=True)
class DisplacementGunConfig:
    min_samples: int = 4
    time_tolerance: int = 2
    min_switch_visits: int = 90
    min_switch_score: float = 0.30

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy("displacement", self.min_switch_visits, self.min_switch_score)

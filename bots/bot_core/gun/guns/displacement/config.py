from dataclasses import dataclass

from bot_core.gun.config import GunModePolicy, GunModeTraits


@dataclass(frozen=True)
class DisplacementGunConfig:
    min_samples: int = 4
    min_switch_visits: int = 90
    min_switch_score: float = 0.30

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            "displacement",
            self.min_switch_visits,
            self.min_switch_score,
            GunModeTraits(
                role="situational",
                family="history_displacement",
                phases=frozenset({"warmup", "late"}),
                strengths=frozenset({"stable_pattern"}),
            ),
        )

from dataclasses import dataclass

from bot_core.gun.config import GunModePolicy, GunModeTraits


@dataclass(frozen=True)
class AntiSurferGunConfig:
    min_samples: int = 7
    smoothing_bins: float = 0.9
    decay: float = 0.92
    guess_factor_bins: int = 31
    min_switch_visits: int = 80
    min_switch_score: float = 0.32

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            "anti_surfer",
            self.min_switch_visits,
            self.min_switch_score,
            GunModeTraits(
                role="situational",
                family="anti_surfer",
                phases=frozenset({"warmup", "late"}),
                strengths=frozenset({"surfer"}),
            ),
        )

__all__ = ["AntiSurferGunConfig"]

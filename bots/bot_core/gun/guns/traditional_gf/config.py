from dataclasses import dataclass

from bot_core.gun.config import GunDecisionContext, GunModePolicy


@dataclass(frozen=True)
class TraditionalGfGunConfig:
    min_samples: int = 28
    smoothing_bins: float = 1.25
    decay: float = 0.985
    centering_factor: float = 1.0
    global_source_centering_factor: float = 1.0
    blend_source_centering_factor: float = 1.0
    segment_source_centering_factor: float = 1.0
    coarse_source_centering_factor: float = 1.0
    coarse_blend_source_centering_factor: float = 1.0
    source_bias_min_samples: int = 12
    source_bias_learning_rate: float = 0.08
    source_bias_max_correction: float = 0.0
    segment_min_samples: int = 0
    segment_full_weight_samples: int = 80
    coarse_segment_min_samples: int = 8
    coarse_segment_full_weight_samples: int = 36
    peak_selection: str = "max"
    peak_support_radius: int = 1
    guess_factor_bins: int = 31
    min_switch_visits: int = 260
    min_switch_score: float = 0.42
    global_source_penalty: float = 0.0
    blend_source_penalty: float = 0.0
    coarse_blend_source_penalty: float = 0.0

    def decision_score_penalty(self, context: GunDecisionContext | None) -> tuple[float, str | None]:
        if context is None or context.mode != "traditional_gf":
            return 0.0, None
        source = context.data.get("source")
        if source == "global":
            return self.global_source_penalty, "global"
        if source == "blend":
            return self.blend_source_penalty * (1.0 - self._blend(context)), "blend"
        if source == "coarse_blend":
            return self.coarse_blend_source_penalty * (1.0 - self._blend(context)), "coarse_blend"
        return 0.0, source if isinstance(source, str) else None

    @staticmethod
    def _blend(context: GunDecisionContext) -> float:
        blend = context.data.get("blend")
        return blend if isinstance(blend, float) else 0.0

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            "traditional_gf",
            self.min_switch_visits,
            self.min_switch_score,
            self.decision_score_penalty,
        )

__all__ = ["TraditionalGfGunConfig"]

from dataclasses import dataclass

from bot_core.gun.config import GunDecisionContext, GunModePolicy, GunModeTraits


@dataclass(frozen=True)
class TraditionalGfGunConfig:
    min_samples: int = 12
    smoothing_bins: float = 1.25
    decay: float = 0.985
    segment_min_samples: int = 8
    segment_full_weight_samples: int = 36
    guess_factor_bins: int = 31
    max_aim_guess_factor: float = 0.87
    min_switch_visits: int = 260
    min_switch_score: float = 0.42
    global_source_min_switch_visits: int | None = None
    global_source_min_switch_score: float | None = None
    trusted_source_min_switch_visits: int | None = None
    trusted_source_min_switch_score: float | None = None
    global_source_penalty: float = 0.10
    blend_source_penalty: float = 0.06

    def decision_score_penalty(self, context: GunDecisionContext | None) -> tuple[float, str | None]:
        if context is None or context.mode != "traditional_gf":
            return 0.0, None
        source = context.data.get("source")
        if source == "global":
            return self.global_source_penalty, "global"
        if source == "blend":
            return self.blend_source_penalty * (1.0 - self._blend(context)), "blend"
        return 0.0, source if isinstance(source, str) else None

    @staticmethod
    def _blend(context: GunDecisionContext) -> float:
        blend = context.data.get("blend")
        return blend if isinstance(blend, float) else 0.0

    def decision_min_switch_visits(self, context: GunDecisionContext | None) -> int:
        if context is None or context.mode != "traditional_gf":
            return self.min_switch_visits
        source = context.data.get("source")
        if source == "global":
            return self._global_source_min_switch_visits()
        if source == "segment":
            return self._trusted_source_min_switch_visits()
        if source == "blend":
            return self._blended_min_switch_visits(context)
        return self.min_switch_visits

    def decision_min_switch_score(self, context: GunDecisionContext | None) -> float:
        if context is None or context.mode != "traditional_gf":
            return self.min_switch_score
        source = context.data.get("source")
        if source == "global":
            return self._global_source_min_switch_score()
        if source == "segment":
            return self._trusted_source_min_switch_score()
        if source == "blend":
            return self._blended_min_switch_score(context)
        return self.min_switch_score

    def _global_source_min_switch_visits(self) -> int:
        return self.min_switch_visits if self.global_source_min_switch_visits is None else self.global_source_min_switch_visits

    def _global_source_min_switch_score(self) -> float:
        return self.min_switch_score if self.global_source_min_switch_score is None else self.global_source_min_switch_score

    def _trusted_source_min_switch_visits(self) -> int:
        return (
            self.min_switch_visits
            if self.trusted_source_min_switch_visits is None
            else self.trusted_source_min_switch_visits
        )

    def _trusted_source_min_switch_score(self) -> float:
        return (
            self.min_switch_score
            if self.trusted_source_min_switch_score is None
            else self.trusted_source_min_switch_score
        )

    def _blended_min_switch_visits(self, context: GunDecisionContext) -> int:
        blend = self._blend(context)
        return round(
            self._global_source_min_switch_visits() * (1.0 - blend)
            + self._trusted_source_min_switch_visits() * blend
        )

    def _blended_min_switch_score(self, context: GunDecisionContext) -> float:
        blend = self._blend(context)
        return (
            self._global_source_min_switch_score() * (1.0 - blend)
            + self._trusted_source_min_switch_score() * blend
        )

    def mode_policy(self) -> GunModePolicy:
        return GunModePolicy(
            mode="traditional_gf",
            min_switch_visits=self.min_switch_visits,
            min_switch_score=self.min_switch_score,
            traits=GunModeTraits(
                role="situational",
                family="profile_gf",
                phases=frozenset({"early", "warmup", "late"}),
                strengths=frozenset({"stable_pattern", "trusted_segment"}),
            ),
            decision_score_penalty=self.decision_score_penalty,
            decision_min_switch_visits=self.decision_min_switch_visits,
            decision_min_switch_score=self.decision_min_switch_score,
        )

__all__ = ["TraditionalGfGunConfig"]

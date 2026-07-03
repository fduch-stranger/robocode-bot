from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot_core.gun.guns.base import GunComponent
    from bot_core.gun.context import TargetHistoryStore


@dataclass(frozen=True)
class GunDecisionContext:
    mode: str
    data: Mapping[str, object]


DecisionPenalty = Callable[[GunDecisionContext | None], tuple[float, str | None]]
DecisionMinSwitchVisits = Callable[[GunDecisionContext | None], int]
DecisionMinSwitchScore = Callable[[GunDecisionContext | None], float]


def no_decision_penalty(_: GunDecisionContext | None) -> tuple[float, str | None]:
    return 0.0, None


@dataclass(frozen=True)
class GunModeTraits:
    role: str = "situational"
    family: str = "generic"
    phases: frozenset[str] = frozenset()
    strengths: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GunModePolicy:
    mode: str
    min_switch_visits: int
    min_switch_score: float
    traits: GunModeTraits | None = None
    decision_score_penalty: DecisionPenalty = no_decision_penalty
    decision_min_switch_visits: DecisionMinSwitchVisits | None = None
    decision_min_switch_score: DecisionMinSwitchScore | None = None

    def __post_init__(self) -> None:
        if self.traits is None:
            object.__setattr__(self, "traits", GunModeTraits())

    def visits_for(self, context: GunDecisionContext | None) -> int:
        if self.decision_min_switch_visits is None:
            return self.min_switch_visits
        return max(0, self.decision_min_switch_visits(context))

    def score_for(self, context: GunDecisionContext | None) -> float:
        if self.decision_min_switch_score is None:
            return self.min_switch_score
        return max(0.0, self.decision_min_switch_score(context))


@dataclass(frozen=True)
class GunSystemConfig:
    max_waves: int = 80
    eval_waves_enabled: bool = False
    eval_wave_min_interval: int = 8
    max_eval_waves: int = 80
    max_target_history: int = 80
    wave_visit_margin: float = 18


@dataclass(frozen=True)
class GunSelectorConfig:
    default_mode: str = "linear"
    forced_mode: str | None = None
    selectable_modes: frozenset[str] = frozenset({"linear", "traditional_gf", "dynamic_cluster"})
    switch_margin: float = 0.08
    primary_over_fallback_margin: float = 0.0
    situational_over_primary_margin: float = 0.0
    primary_slump_visits: int = 0
    primary_slump_score: float = 0.0
    primary_slump_situational_margin: float = 0.0
    switch_confidence_visits: int = 0
    switch_confidence_penalty: float = 0.0
    primary_confidence_penalty_scale: float = 1.0
    primary_role_bonus: float = 0.04
    fallback_role_penalty: float = 0.03
    experimental_role_penalty: float = 0.04
    context_match_bonus: float = 0.04
    sample_maturity_bonus: float = 0.04
    sample_maturity_visits: int = 60
    eval_influence_min_visits: int = 18
    eval_influence_weight: float = 0.25
    eval_influence_cap: float = 0.035
    eval_visit_credit_ratio: float = 0.5


@dataclass(frozen=True)
class GunScoringConfig:
    score_alpha: float = 0.12
    virtual_hit_radius: float = 18
    segment_min_visits: int = 18
    segment_full_weight_visits: int = 80
    selectable_modes: frozenset[str] = frozenset({"linear", "traditional_gf", "dynamic_cluster"})


ComponentFactory = Callable[["TargetHistoryStore"], list["GunComponent"]]


@dataclass(frozen=True)
class GunRuntimeConfig:
    system: GunSystemConfig
    selector: GunSelectorConfig
    scoring: GunScoringConfig
    component_factory: ComponentFactory

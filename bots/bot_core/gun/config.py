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


def no_decision_penalty(_: GunDecisionContext | None) -> tuple[float, str | None]:
    return 0.0, None


@dataclass(frozen=True)
class GunModePolicy:
    mode: str
    min_switch_visits: int
    min_switch_score: float
    decision_score_penalty: DecisionPenalty = no_decision_penalty


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
    switch_confidence_visits: int = 0
    switch_confidence_penalty: float = 0.0


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

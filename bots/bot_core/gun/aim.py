from collections.abc import Mapping
from dataclasses import replace

from bot_core.gun.config import GunDecisionContext, GunModePolicy, GunSelectorConfig
from bot_core.gun.models import GunStats, GunSwitchCandidate
from bot_core.gun.scoring import VirtualGunScorer


class AimModeSelector:
    def __init__(
        self,
        config: GunSelectorConfig,
        scorer: VirtualGunScorer,
        active_modes: dict[int, str],
        stats: dict[tuple[int, str], GunStats],
        mode_policies: Mapping[str, GunModePolicy] | None = None,
        eval_scorer: VirtualGunScorer | None = None,
    ) -> None:
        self.config = config
        self.scorer = scorer
        self.eval_scorer = eval_scorer
        self.active_modes = active_modes
        self.stats = stats
        self.mode_policies = dict(mode_policies or {})

    def select(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None = None,
    ) -> tuple[str, str | None, bool]:
        mode, previous, changed, _ = self.select_with_diagnostics(
            target_id,
            virtual_bearings,
            segment_key,
            decision_contexts,
        )
        return mode, previous, changed

    def select_with_diagnostics(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None = None,
    ) -> tuple[str, str | None, bool, tuple[GunSwitchCandidate, ...]]:
        previous = self.active_modes.get(target_id)
        forced_mode = self.config.forced_mode
        if (
            forced_mode is not None
            and forced_mode in virtual_bearings
        ):
            self.active_modes[target_id] = forced_mode
            raw_score, score, penalty, source_penalty, bonus, eval_bonus, eval_visits = self._score_with_confidence(
                target_id,
                forced_mode,
                segment_key,
                decision_contexts,
            )
            current_mode = previous if previous in virtual_bearings else None
            if current_mode is None:
                current_mode = self.config.default_mode if self.config.default_mode in virtual_bearings else forced_mode
            forced_context = decision_contexts.get(forced_mode) if decision_contexts is not None else None
            (
                raw_current_score,
                current_score,
                current_penalty,
                current_source_penalty,
                current_bonus,
                current_eval_bonus,
                current_eval_visits,
            ) = self._score_with_confidence(
                target_id,
                current_mode,
                segment_key,
                decision_contexts,
            )
            stats = self.stats.get((target_id, forced_mode))
            candidate = GunSwitchCandidate(
                forced_mode,
                True,
                score,
                current_score,
                stats.visits if stats is not None else 0,
                self.min_switch_visits(forced_mode, forced_context),
                self.min_switch_score(forced_mode, forced_context),
                self.config.switch_margin,
                "forced",
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(forced_mode, decision_contexts)[1],
                bonus,
                current_bonus,
                eval_bonus,
                current_eval_bonus,
                eval_visits,
                self._effective_visits(stats.visits if stats is not None else 0, eval_visits),
            )
            return forced_mode, previous, previous != forced_mode, (candidate,)

        current = self.active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        (
            raw_current_score,
            current_score,
            current_penalty,
            current_source_penalty,
            current_bonus,
            current_eval_bonus,
            current_eval_visits,
        ) = self._score_with_confidence(
            target_id,
            current,
            segment_key,
            decision_contexts,
        )
        current_degraded = self._situational_current_degraded(current, decision_contexts)
        best_score = -self.config.switch_margin if current_degraded else current_score
        candidates: dict[str, GunSwitchCandidate] = {}
        ordered_modes: list[str] = []
        for mode in virtual_bearings:
            if mode not in self.config.selectable_modes:
                continue
            ordered_modes.append(mode)
            stats = self.stats.get((target_id, mode))
            visits = stats.visits if stats is not None else 0
            effective_visits = visits
            decision_context = decision_contexts.get(mode) if decision_contexts is not None else None
            required_visits = self.min_switch_visits(mode, decision_context)
            min_score = self.min_switch_score(mode, decision_context)
            switch_margin = self._switch_margin(target_id, current, mode, segment_key, decision_contexts)
            raw_score, score, penalty, source_penalty, bonus, eval_bonus, eval_visits = self._score_with_confidence(
                target_id,
                mode,
                segment_key,
                decision_contexts,
            )
            effective_visits = self._effective_visits(visits, eval_visits)
            reason = "source_degraded" if mode == current and current_degraded else "current" if mode == current else "margin"
            if mode != current and effective_visits < required_visits:
                reason = "visits"
            elif mode != current and score < min_score:
                reason = "score_floor"
            elif mode != current and score > best_score + switch_margin:
                reason = "selected"
                best_mode = mode
                best_score = score
            elif mode != current and score > current_score + switch_margin:
                reason = "superseded"
            candidates[mode] = GunSwitchCandidate(
                mode,
                True,
                score,
                current_score,
                visits,
                required_visits,
                min_score,
                switch_margin,
                reason,
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(mode, decision_contexts)[1],
                bonus,
                current_bonus,
                eval_bonus,
                current_eval_bonus,
                eval_visits,
                effective_visits,
            )
        for mode, candidate in list(candidates.items()):
            if candidate.reason == "selected" and mode != best_mode:
                candidates[mode] = replace(candidate, reason="superseded")
        if best_mode in candidates and best_mode != current:
            candidates[best_mode] = replace(candidates[best_mode], reason="selected")
        for mode in sorted(self.config.selectable_modes - set(virtual_bearings)):
            stats = self.stats.get((target_id, mode))
            visits = stats.visits if stats is not None else 0
            decision_context = decision_contexts.get(mode) if decision_contexts is not None else None
            raw_score, score, penalty, source_penalty, bonus, eval_bonus, eval_visits = self._score_with_confidence(
                target_id,
                mode,
                segment_key,
                decision_contexts,
            )
            ordered_modes.append(mode)
            candidates[mode] = GunSwitchCandidate(
                mode,
                False,
                score,
                current_score,
                visits,
                self.min_switch_visits(mode, decision_context),
                self.min_switch_score(mode, decision_context),
                self.config.switch_margin,
                "unavailable",
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(mode, decision_contexts)[1],
                bonus,
                current_bonus,
                eval_bonus,
                current_eval_bonus,
                eval_visits,
                self._effective_visits(visits, eval_visits),
            )

        self.active_modes[target_id] = best_mode
        return best_mode, previous, previous != best_mode, tuple(candidates[mode] for mode in ordered_modes)

    def _score_with_confidence(
        self,
        target_id: int,
        mode: str,
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None = None,
    ) -> tuple[float, float, float, float, float, float, int]:
        raw_score = self.scorer.gun_score(target_id, mode, segment_key)
        confidence_penalty = self._confidence_penalty(target_id, mode)
        source_penalty, _ = self._decision_penalty(mode, decision_contexts)
        decision_bonus = self._decision_bonus(target_id, mode, decision_contexts)
        eval_bonus, eval_visits = self._eval_score_bonus(target_id, mode, segment_key, raw_score)
        return (
            raw_score,
            min(1.0, max(0.0, raw_score - confidence_penalty - source_penalty + decision_bonus + eval_bonus)),
            confidence_penalty,
            source_penalty,
            decision_bonus,
            eval_bonus,
            eval_visits,
        )

    def _eval_score_bonus(
        self,
        target_id: int,
        mode: str,
        segment_key: tuple[int, ...] | None,
        production_score: float,
    ) -> tuple[float, int]:
        if (
            self.eval_scorer is None
            or self.config.eval_influence_weight <= 0
            or self.config.eval_influence_cap <= 0
            or self.config.eval_influence_min_visits <= 0
        ):
            return 0.0, 0
        eval_score, eval_visits = self.eval_scorer.mode_confidence(target_id, mode, segment_key)
        if eval_visits < self.config.eval_influence_min_visits:
            return 0.0, eval_visits
        delta = (eval_score - production_score) * self.config.eval_influence_weight
        cap = self.config.eval_influence_cap
        return min(cap, max(-cap, delta)), eval_visits

    def _effective_visits(self, production_visits: int, eval_visits: int) -> int:
        if self.config.eval_visit_credit_ratio <= 0 or eval_visits < self.config.eval_influence_min_visits:
            return production_visits
        eval_credit = int(eval_visits * self.config.eval_visit_credit_ratio)
        return max(production_visits, eval_credit)

    def _decision_penalty(
        self,
        mode: str,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> tuple[float, str | None]:
        context = decision_contexts.get(mode) if decision_contexts is not None else None
        return self._policy_for(mode).decision_score_penalty(context)

    def _decision_bonus(
        self,
        target_id: int,
        mode: str,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> float:
        policy = self._policy_for(mode)
        traits = policy.traits
        context = decision_contexts.get(mode) if decision_contexts is not None else None
        context_tags = self._context_tags(context)
        sample_count = self._context_number(context, "samples")
        if sample_count is None:
            stats = self.stats.get((target_id, mode))
            sample_count = float(stats.visits if stats is not None else 0)
        maturity = min(1.0, sample_count / max(1, self.config.sample_maturity_visits))

        bonus = 0.0
        if traits.role == "primary":
            bonus += self.config.primary_role_bonus * maturity
            if maturity >= 1.0:
                bonus += self.config.sample_maturity_bonus
        elif traits.role == "fallback":
            bonus -= self.config.fallback_role_penalty
        elif traits.role == "experimental":
            bonus -= self.config.experimental_role_penalty

        if context_tags and traits.strengths.intersection(context_tags):
            bonus += self.config.context_match_bonus
        return bonus

    @staticmethod
    def _context_tags(context: GunDecisionContext | None) -> frozenset[str]:
        if context is None:
            return frozenset()
        tags = context.data.get("context_tags")
        if isinstance(tags, frozenset):
            return tags
        if isinstance(tags, set):
            return frozenset(str(tag) for tag in tags)
        if isinstance(tags, tuple | list):
            return frozenset(str(tag) for tag in tags)
        return frozenset()

    @staticmethod
    def _context_number(context: GunDecisionContext | None, key: str) -> float | None:
        if context is None:
            return None
        value = context.data.get(key)
        return float(value) if isinstance(value, int | float) else None

    def _confidence_penalty(self, target_id: int, mode: str) -> float:
        if self.config.switch_confidence_visits <= 0 or self.config.switch_confidence_penalty <= 0:
            return 0.0
        stats = self.stats.get((target_id, mode))
        visits = stats.visits if stats is not None else 0
        if visits >= self.config.switch_confidence_visits:
            return 0.0
        missing_ratio = 1.0 - visits / self.config.switch_confidence_visits
        penalty = self.config.switch_confidence_penalty * missing_ratio
        if self._policy_for(mode).traits.role == "primary":
            penalty *= max(0.0, self.config.primary_confidence_penalty_scale)
        return penalty

    def _switch_margin(
        self,
        target_id: int,
        current: str,
        candidate: str,
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> float:
        margin = self.config.switch_margin
        if candidate == current:
            return margin
        current_role = self._policy_for(current).traits.role
        candidate_role = self._policy_for(candidate).traits.role
        if (
            current_role == "fallback"
            and candidate_role == "primary"
            and self.config.primary_over_fallback_margin > 0
        ):
            return min(margin, self.config.primary_over_fallback_margin)
        if current_role == "primary" and candidate_role == "situational" and self.config.situational_over_primary_margin > 0:
            if self._primary_slump_allows_situational(target_id, current, candidate, segment_key, decision_contexts):
                return min(
                    self.config.situational_over_primary_margin,
                    max(0.0, self.config.primary_slump_situational_margin),
                )
            return max(margin, self.config.situational_over_primary_margin)
        return margin

    def _primary_slump_allows_situational(
        self,
        target_id: int,
        current: str,
        candidate: str,
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> bool:
        if (
            self.config.primary_slump_visits <= 0
            or self.config.primary_slump_situational_margin <= 0
            or self._policy_for(current).traits.role != "primary"
            or self._policy_for(candidate).traits.role != "situational"
        ):
            return False
        current_stats = self.stats.get((target_id, current))
        if current_stats is None or current_stats.visits < self.config.primary_slump_visits:
            return False
        if self.scorer.gun_score(target_id, current, segment_key) > self.config.primary_slump_score:
            return False
        candidate_context = decision_contexts.get(candidate) if decision_contexts is not None else None
        if candidate_context is None:
            return False
        source = candidate_context.data.get("source")
        return source in {"segment", "coarse", "blend", "coarse_blend"} or bool(self._context_tags(candidate_context))

    def _situational_current_degraded(
        self,
        current: str,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> bool:
        if self._policy_for(current).traits.role != "situational" or decision_contexts is None:
            return False
        current_context = decision_contexts.get(current)
        if current_context is None:
            return False
        return current_context.data.get("source") == "global"

    def min_switch_score(self, mode: str, context: GunDecisionContext | None = None) -> float:
        return self._policy_for(mode).score_for(context)

    def min_switch_visits(self, mode: str, context: GunDecisionContext | None = None) -> int:
        return self._policy_for(mode).visits_for(context)

    def _policy_for(self, mode: str) -> GunModePolicy:
        fallback = self.mode_policies.get(self.config.default_mode)
        if fallback is None and self.mode_policies:
            fallback = next(iter(self.mode_policies.values()))
        if fallback is None:
            fallback = GunModePolicy(mode, 0, 0.0)
        return self.mode_policies.get(mode, fallback)

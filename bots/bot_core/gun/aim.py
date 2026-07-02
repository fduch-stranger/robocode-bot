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
    ) -> None:
        self.config = config
        self.scorer = scorer
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
            raw_score, score, penalty, source_penalty = self._score_with_confidence(
                target_id,
                forced_mode,
                segment_key,
                decision_contexts,
            )
            current_mode = previous if previous in virtual_bearings else None
            if current_mode is None:
                current_mode = self.config.default_mode if self.config.default_mode in virtual_bearings else forced_mode
            raw_current_score, current_score, current_penalty, current_source_penalty = self._score_with_confidence(
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
                self.min_switch_visits(forced_mode),
                self.min_switch_score(forced_mode),
                self.config.switch_margin,
                "forced",
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(forced_mode, decision_contexts)[1],
            )
            return forced_mode, previous, previous != forced_mode, (candidate,)

        current = self.active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        raw_current_score, current_score, current_penalty, current_source_penalty = self._score_with_confidence(
            target_id,
            current,
            segment_key,
            decision_contexts,
        )
        best_score = current_score
        candidates: dict[str, GunSwitchCandidate] = {}
        ordered_modes: list[str] = []
        for mode in virtual_bearings:
            if mode not in self.config.selectable_modes:
                continue
            ordered_modes.append(mode)
            stats = self.stats.get((target_id, mode))
            visits = stats.visits if stats is not None else 0
            required_visits = self.min_switch_visits(mode)
            min_score = self.min_switch_score(mode)
            raw_score, score, penalty, source_penalty = self._score_with_confidence(
                target_id,
                mode,
                segment_key,
                decision_contexts,
            )
            reason = "current" if mode == current else "margin"
            if mode != current and visits < required_visits:
                reason = "visits"
            elif mode != current and score < min_score:
                reason = "score_floor"
            elif mode != current and score > best_score + self.config.switch_margin:
                reason = "selected"
                best_mode = mode
                best_score = score
            elif mode != current and score > current_score + self.config.switch_margin:
                reason = "superseded"
            candidates[mode] = GunSwitchCandidate(
                mode,
                True,
                score,
                current_score,
                visits,
                required_visits,
                min_score,
                self.config.switch_margin,
                reason,
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(mode, decision_contexts)[1],
            )
        for mode, candidate in list(candidates.items()):
            if candidate.reason == "selected" and mode != best_mode:
                candidates[mode] = replace(candidate, reason="superseded")
        if best_mode in candidates and best_mode != current:
            candidates[best_mode] = replace(candidates[best_mode], reason="selected")
        for mode in sorted(self.config.selectable_modes - set(virtual_bearings)):
            stats = self.stats.get((target_id, mode))
            visits = stats.visits if stats is not None else 0
            raw_score, score, penalty, source_penalty = self._score_with_confidence(
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
                self.min_switch_visits(mode),
                self.min_switch_score(mode),
                self.config.switch_margin,
                "unavailable",
                raw_score,
                raw_current_score,
                penalty,
                current_penalty,
                source_penalty,
                current_source_penalty,
                self._decision_penalty(mode, decision_contexts)[1],
            )

        self.active_modes[target_id] = best_mode
        return best_mode, previous, previous != best_mode, tuple(candidates[mode] for mode in ordered_modes)

    def _score_with_confidence(
        self,
        target_id: int,
        mode: str,
        segment_key: tuple[int, ...] | None,
        decision_contexts: Mapping[str, GunDecisionContext] | None = None,
    ) -> tuple[float, float, float, float]:
        raw_score = self.scorer.gun_score(target_id, mode, segment_key)
        confidence_penalty = self._confidence_penalty(target_id, mode)
        source_penalty, _ = self._decision_penalty(mode, decision_contexts)
        return raw_score, max(0.0, raw_score - confidence_penalty - source_penalty), confidence_penalty, source_penalty

    def _decision_penalty(
        self,
        mode: str,
        decision_contexts: Mapping[str, GunDecisionContext] | None,
    ) -> tuple[float, str | None]:
        context = decision_contexts.get(mode) if decision_contexts is not None else None
        return self._policy_for(mode).decision_score_penalty(context)

    def _confidence_penalty(self, target_id: int, mode: str) -> float:
        if self.config.switch_confidence_visits <= 0 or self.config.switch_confidence_penalty <= 0:
            return 0.0
        stats = self.stats.get((target_id, mode))
        visits = stats.visits if stats is not None else 0
        if visits >= self.config.switch_confidence_visits:
            return 0.0
        missing_ratio = 1.0 - visits / self.config.switch_confidence_visits
        return self.config.switch_confidence_penalty * missing_ratio

    def min_switch_score(self, mode: str) -> float:
        return self._policy_for(mode).min_switch_score

    def min_switch_visits(self, mode: str) -> int:
        return self._policy_for(mode).min_switch_visits

    def _policy_for(self, mode: str) -> GunModePolicy:
        fallback = self.mode_policies.get(self.config.default_mode)
        if fallback is None and self.mode_policies:
            fallback = next(iter(self.mode_policies.values()))
        if fallback is None:
            fallback = GunModePolicy(mode, 0, 0.0)
        return self.mode_policies.get(mode, fallback)

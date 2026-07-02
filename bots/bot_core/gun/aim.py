from dataclasses import replace

from bot_core.gun.models import GunConfig, GunStats, GunSwitchCandidate
from bot_core.gun.scoring import VirtualGunScorer


class AimModeSelector:
    def __init__(
        self,
        config: GunConfig,
        scorer: VirtualGunScorer,
        active_modes: dict[int, str],
        stats: dict[tuple[int, str], GunStats],
    ) -> None:
        self.config = config
        self.scorer = scorer
        self.active_modes = active_modes
        self.stats = stats

    def select(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
    ) -> tuple[str, str | None, bool]:
        mode, previous, changed, _ = self.select_with_diagnostics(target_id, virtual_bearings, segment_key)
        return mode, previous, changed

    def select_with_diagnostics(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
    ) -> tuple[str, str | None, bool, tuple[GunSwitchCandidate, ...]]:
        previous = self.active_modes.get(target_id)
        forced_mode = self.config.forced_mode
        if (
            forced_mode is not None
            and forced_mode in virtual_bearings
        ):
            self.active_modes[target_id] = forced_mode
            raw_score, score, penalty = self._score_with_confidence(target_id, forced_mode, segment_key)
            stats = self.stats.get((target_id, forced_mode))
            candidate = GunSwitchCandidate(
                forced_mode,
                True,
                score,
                score,
                stats.visits if stats is not None else 0,
                self.min_switch_visits(forced_mode),
                self.min_switch_score(forced_mode),
                self.config.switch_margin,
                "forced",
                raw_score,
                raw_score,
                penalty,
                penalty,
            )
            return forced_mode, previous, previous != forced_mode, (candidate,)

        current = self.active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        raw_current_score, current_score, current_penalty = self._score_with_confidence(target_id, current, segment_key)
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
            raw_score, score, penalty = self._score_with_confidence(target_id, mode, segment_key)
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
            )
        for mode, candidate in list(candidates.items()):
            if candidate.reason == "selected" and mode != best_mode:
                candidates[mode] = replace(candidate, reason="superseded")
        if best_mode in candidates and best_mode != current:
            candidates[best_mode] = replace(candidates[best_mode], reason="selected")
        for mode in sorted(self.config.selectable_modes - set(virtual_bearings)):
            ordered_modes.append(mode)
            candidates[mode] = GunSwitchCandidate(
                mode,
                False,
                0.0,
                current_score,
                0,
                self.min_switch_visits(mode),
                self.min_switch_score(mode),
                self.config.switch_margin,
                "unavailable",
                0.0,
                raw_current_score,
                0.0,
                current_penalty,
            )

        self.active_modes[target_id] = best_mode
        return best_mode, previous, previous != best_mode, tuple(candidates[mode] for mode in ordered_modes)

    def _score_with_confidence(
        self,
        target_id: int,
        mode: str,
        segment_key: tuple[int, ...] | None,
    ) -> tuple[float, float, float]:
        raw_score = self.scorer.gun_score(target_id, mode, segment_key)
        penalty = self._confidence_penalty(target_id, mode)
        return raw_score, max(0.0, raw_score - penalty), penalty

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
        if mode == "head_on":
            return self.config.head_on_min_switch_score
        if mode == "displacement":
            return self.config.displacement_min_switch_score
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_score
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_score
        return self.config.min_switch_score

    def min_switch_visits(self, mode: str) -> int:
        if mode == "displacement":
            return self.config.displacement_min_switch_visits
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_visits
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_visits
        return self.config.min_visits

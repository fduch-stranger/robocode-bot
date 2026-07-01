from bot_core.gun.models import GunConfig, GunStats
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
        current = self.active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        best_score = self.scorer.gun_score(target_id, current, segment_key)
        for mode in virtual_bearings:
            if mode not in self.config.selectable_modes:
                continue
            stats = self.stats.get((target_id, mode))
            if stats is None or stats.visits < self.min_switch_visits(mode):
                continue
            score = self.scorer.gun_score(target_id, mode, segment_key)
            if score < self.min_switch_score(mode):
                continue
            if score > best_score + self.config.switch_margin:
                best_mode = mode
                best_score = score

        previous = self.active_modes.get(target_id)
        self.active_modes[target_id] = best_mode
        return best_mode, previous, previous != best_mode

    def min_switch_score(self, mode: str) -> float:
        if mode == "head_on":
            return self.config.head_on_min_switch_score
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_score
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_score
        return self.config.min_switch_score

    def min_switch_visits(self, mode: str) -> int:
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_visits
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_visits
        return self.config.min_visits

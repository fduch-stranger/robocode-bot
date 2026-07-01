import math

from bot_core.geometry.angles import relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.gun.models import GunConfig, GunStats, GunWave


class VirtualGunScorer:
    def __init__(
        self,
        config: GunConfig,
        stats: dict[tuple[int, str], GunStats],
        segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats],
    ) -> None:
        self.config = config
        self.stats = stats
        self.segment_stats = segment_stats

    def score_virtual_guns(
        self,
        wave: GunWave,
        actual_bearing: float,
        target_distance: float,
    ) -> dict[str, float]:
        hit_angle = math.degrees(math.atan2(self.config.virtual_hit_radius, max(1.0, target_distance)))
        scores: dict[str, float] = {}
        for mode, aim_bearing in wave.virtual_bearings.items():
            error = abs(relative_bearing(actual_bearing, aim_bearing))
            score = max(0.0, 1.0 - error / max(hit_angle, 0.1))
            self.update_stats(self.stats.setdefault((wave.target_id, mode), GunStats()), score)
            self.update_stats(
                self.segment_stats.setdefault((wave.target_id, mode, wave.segment_key), GunStats()),
                score,
            )
            scores[mode] = round(score, 3)
        return scores

    def score_summary(self, target_id: int, segment_key: tuple[int, ...] | None = None) -> dict[str, str]:
        summary: dict[str, str] = {}
        for (stats_target_id, mode), stats in self.stats.items():
            if stats_target_id != target_id:
                continue
            if segment_key is None:
                summary[mode] = f"{self.gun_score(target_id, mode):.3f}/{stats.visits}"
                continue

            segment_stats = self.segment_stats.get((target_id, mode, segment_key))
            segment_visits = segment_stats.visits if segment_stats is not None else 0
            summary[mode] = (
                f"{self.gun_score(target_id, mode, segment_key):.3f}/{stats.visits}"
                f"/s{segment_visits}"
            )
        return summary

    def target_confidence(self, target_id: int) -> tuple[float, int]:
        best_score = 0.0
        best_visits = 0
        for (stats_target_id, mode), stats in self.stats.items():
            if stats_target_id != target_id or mode not in self.config.selectable_modes:
                continue
            score = self.gun_score(target_id, mode)
            if score > best_score:
                best_score = score
                best_visits = stats.visits
        return best_score, best_visits

    def gun_score(self, target_id: int, mode: str, segment_key: tuple[int, ...] | None = None) -> float:
        stats = self.stats.get((target_id, mode))
        if stats is None:
            return 0.0
        global_score = self.raw_gun_score(stats)
        if segment_key is None:
            return global_score

        segment_stats = self.segment_stats.get((target_id, mode, segment_key))
        if segment_stats is None or segment_stats.visits < self.config.segment_min_visits:
            return global_score

        segment_score = self.raw_gun_score(segment_stats)
        blend = clamp(
            (segment_stats.visits - self.config.segment_min_visits)
            / max(1, self.config.segment_full_weight_visits - self.config.segment_min_visits),
            0.0,
            1.0,
        )
        return global_score * (1.0 - blend) + segment_score * blend

    @staticmethod
    def raw_gun_score(stats: GunStats) -> float:
        accuracy = stats.hits / max(1, stats.visits)
        return 0.7 * stats.rolling_score + 0.3 * accuracy

    def update_stats(self, stats: GunStats, score: float) -> None:
        stats.visits += 1
        if score > 0:
            stats.hits += 1
        stats.rolling_score = (1.0 - self.config.score_alpha) * stats.rolling_score + self.config.score_alpha * score

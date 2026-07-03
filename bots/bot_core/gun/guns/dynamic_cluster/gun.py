import math

from bot_core.geometry.numeric import clamp
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, guess_factor_aim_bearing
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.memory import RollingKnnBuffer
from bot_core.gun.models import GunSample
from bot_core.gun.utils import feature_distance


class DynamicClusterGun:
    mode = "dynamic_cluster"

    def __init__(self, config: DynamicClusterGunConfig) -> None:
        self.config = config
        self.memory = RollingKnnBuffer(config.max_samples, config.max_samples_per_target)
        self.sequence = 0
        self.mode_policy = config.mode_policy()

    @property
    def sample_count(self) -> int:
        return self.memory.sample_count

    def target_sample_count(self, target_id: int) -> int:
        return self.memory.target_sample_count(target_id)

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        if target_id is None:
            return {"sample_count": self.sample_count}
        return {"target_sample_count": self.target_sample_count(target_id)}

    def aim(self, context: AimContext) -> GunBearing | None:
        samples = self.memory.samples_for(context.target.bot_id)
        sample_count = len(samples)
        guess_factor = self.guess_factor_from_samples(context.target.bot_id, context.features, samples)
        if guess_factor is None:
            return None
        return GunBearing(
            self.mode,
            guess_factor_aim_bearing(context.bot, context.target, context.firepower, guess_factor),
            guess_factor=guess_factor,
            decision_context=GunDecisionContext(
                self.mode,
                {
                    "samples": sample_count,
                    "blend": self._warmup_blend(sample_count),
                    "context_tags": self._context_tags(context),
                },
            ),
        )

    def observe_visit(self, visit: GunVisit) -> None:
        self.sequence += 1
        self.memory.add(GunSample(visit.wave.target_id, self.sequence, visit.wave.features, visit.guess_factor))

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        return {}

    @staticmethod
    def _context_tags(context: AimContext) -> frozenset[str]:
        return context.movement_tags.intersection({"surfer", "nonlinear_mover", "adaptive_mover"})

    def guess_factor(self, target_id: int, features: tuple[float, ...]) -> float | None:
        samples = self.memory.samples_for(target_id)
        return self.guess_factor_from_samples(target_id, features, samples)

    def guess_factor_from_samples(
        self,
        target_id: int,
        features: tuple[float, ...],
        samples: list[GunSample],
    ) -> float | None:
        sample_count = len(samples)
        if sample_count < self.config.min_samples:
            return None
        current_turn = self.sequence
        effective_count = self.memory.effective_count(
            target_id,
            current_turn=current_turn,
            half_life=self.config.decay_half_life,
        )
        if effective_count < self.config.min_effective_samples:
            return None

        neighbors = sorted(
            samples,
            key=lambda neighbor_sample: feature_distance(features, neighbor_sample.features)
            / max(
                0.25,
                self.memory.decayed_weight(
                    neighbor_sample,
                    current_turn=current_turn,
                    half_life=self.config.decay_half_life,
                ),
            ),
        )[: min(self.config.neighbors, sample_count)]
        weighted_neighbors: list[tuple[GunSample, float]] = []
        for sample in neighbors:
            distance = feature_distance(features, sample.features)
            recency = self.memory.decayed_weight(sample, current_turn, self.config.decay_half_life)
            weight = recency / (0.05 + distance)
            weighted_neighbors.append((sample, weight))
        if not weighted_neighbors:
            return None

        guess_factor = 0.0
        best_score = -1.0
        for index in range(self.config.guess_factor_bins):
            candidate = -1.0 + 2.0 * index / (self.config.guess_factor_bins - 1)
            score = 0.0
            for sample, weight in weighted_neighbors:
                offset = (sample.guess_factor - candidate) / self.config.bandwidth
                score += weight * math.exp(-(offset * offset))
            if score > best_score:
                best_score = score
                guess_factor = candidate

        if sample_count < self.config.blend_samples:
            guess_factor *= self._warmup_blend(sample_count)
        return clamp(guess_factor, -1.0, 1.0)

    def _warmup_blend(self, sample_count: int) -> float:
        if sample_count >= self.config.blend_samples:
            return 1.0
        return clamp(
            (sample_count - self.config.min_samples) / max(1, self.config.blend_samples - self.config.min_samples),
            0.0,
            1.0,
        )

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None

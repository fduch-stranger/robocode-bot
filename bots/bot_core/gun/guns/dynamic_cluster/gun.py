import math
from dataclasses import dataclass

from bot_core.geometry.numeric import clamp
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, guess_factor_aim_bearing
from bot_core.gun.features import feature_distance
from bot_core.gun.guns.dynamic_cluster.config import DynamicClusterGunConfig
from bot_core.gun.guns.dynamic_cluster.memory import RollingKnnBuffer
from bot_core.gun.models import FireContext, GunSample


@dataclass(frozen=True)
class KnnPrediction:
    guess_factor: float
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class DensityAnalysis:
    selected_guess_factor: float
    best_bin_guess_factor: float
    best_peak_score: float
    second_peak_guess_factor: float
    second_peak_score: float
    effective_bandwidth: float


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
        prediction = self._prediction_from_samples(
            context.target.bot_id,
            context.features,
            samples,
            context.fire_context,
            context.distance,
        )
        if prediction is None:
            return None
        return GunBearing(
            self.mode,
            guess_factor_aim_bearing(context.bot, context.target, context.firepower, prediction.guess_factor),
            guess_factor=prediction.guess_factor,
            decision_context=GunDecisionContext(
                self.mode,
                {
                    "samples": sample_count,
                    "blend": self._warmup_blend(sample_count),
                    "context_tags": self._context_tags(context),
                },
            ),
            metadata={self.mode: prediction.diagnostics},
        )

    def observe_visit(self, visit: GunVisit) -> None:
        self.sequence += 1
        self.memory.add(
            GunSample(
                visit.wave.target_id,
                self.sequence,
                visit.wave.features,
                visit.guess_factor,
                visit.wave.fire_context,
            )
        )

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        return self._visit_base_diagnostics(visit)

    def _visit_base_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        metadata = visit.wave.gun_metadata.get(self.mode)
        if isinstance(metadata, dict):
            return dict(metadata)
        prediction = self._prediction_from_samples(
            visit.wave.target_id,
            visit.wave.features,
            self.memory.samples_for(visit.wave.target_id),
            visit.wave.fire_context,
            visit.wave.fire_context.bullet_flight_time * visit.wave.bullet_speed,
        )
        return prediction.diagnostics if prediction is not None else {}

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
        prediction = self._prediction_from_samples(target_id, features, samples, FireContext(), 0.0)
        return prediction.guess_factor if prediction is not None else None

    def _prediction_from_samples(
        self,
        target_id: int,
        features: tuple[float, ...],
        samples: list[GunSample],
        fire_context: FireContext,
        target_distance: float,
    ) -> KnnPrediction | None:
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
            context_factor = self._context_weight_factor(fire_context, sample.fire_context)
            weight = context_factor * recency / (0.05 + distance)
            weighted_neighbors.append((sample, weight))
        if not weighted_neighbors:
            return None

        density = self._analyze_density(weighted_neighbors, target_distance, fire_context)
        guess_factor = density.selected_guess_factor

        if sample_count < self.config.blend_samples:
            guess_factor *= self._warmup_blend(sample_count)
        diagnostics = self._neighbor_diagnostics(features, fire_context, weighted_neighbors, density, sample_count)
        diagnostics["selected_guess_factor"] = clamp(guess_factor, -1.0, 1.0)
        return KnnPrediction(clamp(guess_factor, -1.0, 1.0), diagnostics)

    def _analyze_density(
        self,
        weighted_neighbors: list[tuple[GunSample, float]],
        target_distance: float,
        fire_context: FireContext,
    ) -> DensityAnalysis:
        effective_bandwidth = self._effective_bandwidth(target_distance, fire_context)
        scored_bins: list[tuple[float, float]] = []
        for density_bin_index in range(self.config.guess_factor_bins):
            candidate = -1.0 + 2.0 * density_bin_index / (self.config.guess_factor_bins - 1)
            score = self._density_score(candidate, weighted_neighbors, effective_bandwidth)
            scored_bins.append((candidate, score))

        best_index = max(range(len(scored_bins)), key=lambda scored_bin_index: scored_bins[scored_bin_index][1])
        best_guess_factor, best_score = scored_bins[best_index]
        second_guess_factor, second_score = self._second_peak(scored_bins, best_index, effective_bandwidth)
        selected_guess_factor = self._local_peak_centroid(
            best_guess_factor,
            weighted_neighbors,
            effective_bandwidth,
        )
        peak_score_ratio = second_score / max(best_score, 1e-6)
        if peak_score_ratio >= self.config.ambiguous_peak_score_ratio:
            selected_guess_factor *= self.config.ambiguous_peak_centering_factor
        return DensityAnalysis(
            selected_guess_factor=selected_guess_factor,
            best_bin_guess_factor=best_guess_factor,
            best_peak_score=best_score,
            second_peak_guess_factor=second_guess_factor,
            second_peak_score=second_score,
            effective_bandwidth=effective_bandwidth,
        )

    def _second_peak(
        self,
        scored_bins: list[tuple[float, float]],
        best_index: int,
        effective_bandwidth: float,
    ) -> tuple[float, float]:
        if not scored_bins:
            return 0.0, 0.0

        best_guess_factor, _ = scored_bins[best_index]
        bin_width = 2.0 / max(1, self.config.guess_factor_bins - 1)
        suppression_window = max(
            effective_bandwidth * self.config.second_peak_suppression_bandwidth_scale,
            self.config.second_peak_suppression_bin_scale * bin_width,
        )
        previous_scores = [float("-inf"), *(score for _, score in scored_bins[:-1])]
        next_scores = [*(score for _, score in scored_bins[1:]), float("-inf")]
        local_peaks: list[tuple[float, float]] = []
        for (guess_factor, score), previous_score, next_score in zip(scored_bins, previous_scores, next_scores):
            if abs(guess_factor - best_guess_factor) <= suppression_window:
                continue
            if score >= previous_score and score >= next_score:
                local_peaks.append((guess_factor, score))
        if local_peaks:
            return max(local_peaks, key=lambda peak: peak[1])

        separated_bins = [
            scored
            for scored in scored_bins
            if abs(scored[0] - best_guess_factor) > suppression_window
        ]
        if separated_bins:
            return max(separated_bins, key=lambda scored: scored[1])
        return best_guess_factor, 0.0

    @staticmethod
    def _density_score(
        candidate: float,
        weighted_neighbors: list[tuple[GunSample, float]],
        effective_bandwidth: float,
    ) -> float:
        score = 0.0
        for sample, weight in weighted_neighbors:
            offset = (sample.guess_factor - candidate) / effective_bandwidth
            score += weight * math.exp(-(offset * offset))
        return score

    def _local_peak_centroid(
        self,
        best_guess_factor: float,
        weighted_neighbors: list[tuple[GunSample, float]],
        effective_bandwidth: float,
    ) -> float:
        bin_width = 2.0 / max(1, self.config.guess_factor_bins - 1)
        window = max(
            effective_bandwidth * self.config.centroid_window_bandwidth_scale,
            self.config.centroid_window_bin_scale * bin_width,
        )
        total_weight = 0.0
        weighted_guess_factor = 0.0
        for sample, weight in weighted_neighbors:
            distance = abs(sample.guess_factor - best_guess_factor)
            if distance > window:
                continue
            offset = distance / effective_bandwidth
            local_weight = weight * math.exp(-(offset * offset))
            total_weight += local_weight
            weighted_guess_factor += sample.guess_factor * local_weight
        if total_weight <= self.config.centroid_min_weight:
            return best_guess_factor
        return clamp(weighted_guess_factor / total_weight, -1.0, 1.0)

    def _effective_bandwidth(self, target_distance: float, fire_context: FireContext) -> float:
        if target_distance <= 0:
            return self.config.bandwidth
        max_escape_angle = max(
            0.1,
            fire_context.positive_escape_angle,
            fire_context.negative_escape_angle,
        )
        hit_angle = math.atan2(18.0, target_distance)
        gf_hit_width = hit_angle / max_escape_angle
        return clamp(
            max(self.config.bandwidth_min, gf_hit_width * self.config.bandwidth_hit_width_scale),
            self.config.bandwidth_min,
            self.config.bandwidth_max,
        )

    def _context_weight_factor(self, current: FireContext, sample: FireContext) -> float:
        if not self.config.context_weighting_enabled or current == FireContext():
            return 1.0
        factor = 1.0 + self.config.tag_match_bonus * self._tag_match_ratio(current, sample)
        flight_delta = self._flight_time_delta(current, sample)
        wall_delta = abs(current.wall_escape_balance - sample.wall_escape_balance)
        lateral_confidence = min(current.lateral_direction_confidence, sample.lateral_direction_confidence)
        factor *= 1.0 - self.config.flight_time_mismatch_penalty * clamp(flight_delta / 0.5, 0.0, 1.0)
        factor *= 1.0 - self.config.wall_escape_mismatch_penalty * clamp(wall_delta, 0.0, 1.0)
        factor *= 1.0 - self.config.lateral_confidence_penalty * (1.0 - lateral_confidence)
        return clamp(factor, self.config.context_weight_min, self.config.context_weight_max)

    def _neighbor_diagnostics(
        self,
        features: tuple[float, ...],
        fire_context: FireContext,
        weighted_neighbors: list[tuple[GunSample, float]],
        density: DensityAnalysis,
        maturity_sample_count: float,
    ) -> dict[str, object]:
        neighbor_count = len(weighted_neighbors)
        distances = [feature_distance(features, sample.features) for sample, _ in weighted_neighbors]
        tag_matches = [
            DynamicClusterGun._tag_match_ratio(fire_context, sample.fire_context)
            for sample, _ in weighted_neighbors
        ]
        flight_deltas = [
            DynamicClusterGun._flight_time_delta(fire_context, sample.fire_context)
            for sample, _ in weighted_neighbors
        ]
        wall_deltas = [
            abs(fire_context.wall_escape_balance - sample.fire_context.wall_escape_balance)
            for sample, _ in weighted_neighbors
        ]
        lateral_confidences = [
            sample.fire_context.lateral_direction_confidence
            for sample, _ in weighted_neighbors
        ]
        total_weight = sum(weight for _, weight in weighted_neighbors)
        agreement_window = max(density.effective_bandwidth, 2.0 / max(1, neighbor_count))
        agreement_weight = sum(
            weight
            for sample, weight in weighted_neighbors
            if abs(sample.guess_factor - density.selected_guess_factor) <= agreement_window
        )
        context_match = sum(
            DynamicClusterGun._context_match_score(fire_context, sample.fire_context) * weight
            for sample, weight in weighted_neighbors
        ) / max(total_weight, 1e-6)
        avg_distance = sum(distances) / neighbor_count
        peak_margin = density.best_peak_score - density.second_peak_score
        peak_score_ratio = density.second_peak_score / max(density.best_peak_score, 1e-6)
        neighbor_agreement = agreement_weight / max(total_weight, 1e-6)
        confidence = self._aim_confidence(
            maturity_sample_count,
            avg_distance,
            peak_margin,
            neighbor_agreement,
            context_match,
        )
        diagnostics: dict[str, object] = {
            "neighbor_count": neighbor_count,
            "avg_neighbor_distance": avg_distance,
            "neighbor_distance_min": min(distances),
            "neighbor_distance_max": max(distances),
            "tag_match_ratio": sum(tag_matches) / neighbor_count,
            "avg_flight_time_delta": sum(flight_deltas) / neighbor_count,
            "avg_wall_escape_delta": sum(wall_deltas) / neighbor_count,
            "avg_lateral_confidence": sum(lateral_confidences) / neighbor_count,
            "density_score": density.best_peak_score,
            "effective_bandwidth": density.effective_bandwidth,
            "best_bin_guess_factor": density.best_bin_guess_factor,
            "peak_margin": peak_margin,
            "neighbor_agreement": neighbor_agreement,
            "aim_confidence": confidence,
            "best_peak_gf": density.best_bin_guess_factor,
            "best_peak_score": density.best_peak_score,
            "second_peak_gf": density.second_peak_guess_factor,
            "second_peak_score": density.second_peak_score,
            "peak_separation": abs(density.best_bin_guess_factor - density.second_peak_guess_factor),
            "peak_score_ratio": peak_score_ratio,
            "ambiguous_peak": peak_score_ratio >= self.config.ambiguous_peak_score_ratio,
        }
        diagnostics.update(self._shot_quality_diagnostics(fire_context, diagnostics))
        return diagnostics

    def _shot_quality_diagnostics(
        self,
        fire_context: FireContext,
        diagnostics: dict[str, object],
    ) -> dict[str, object]:
        if not self.config.shot_quality_enabled:
            return {
                "shot_quality": 1.0,
                "quality_reason": "disabled",
                "recommended_power_scale": 1.0,
            }
        aim_confidence = self._diagnostic_float(diagnostics, "aim_confidence") or 0.0
        neighbor_agreement = self._diagnostic_float(diagnostics, "neighbor_agreement") or 0.0
        ambiguous_peak = bool(diagnostics.get("ambiguous_peak", False))
        wall_delta = self._diagnostic_float(diagnostics, "avg_wall_escape_delta") or 0.0
        lateral_confidence = min(
            1.0,
            fire_context.lateral_direction_confidence,
            self._diagnostic_float(diagnostics, "avg_lateral_confidence") or 0.0,
        )
        ambiguity_factor = 0.75 if ambiguous_peak else 1.0
        wall_stability = 1.0 - clamp(wall_delta, 0.0, 1.0)
        quality = clamp(
            aim_confidence * neighbor_agreement * ambiguity_factor * wall_stability * lateral_confidence,
            0.0,
            1.0,
        )
        reason = "strong"
        power_scale = 1.0
        if quality < self.config.shot_quality_weak_threshold:
            reason = "very_weak"
            power_scale = self.config.shot_quality_low_power_scale
        elif quality < self.config.shot_quality_good_threshold:
            reason = "weak"
            power_scale = self.config.shot_quality_medium_power_scale
        return {
            "shot_quality": quality,
            "quality_reason": reason,
            "recommended_power_scale": power_scale,
        }

    @staticmethod
    def _diagnostic_float(diagnostics: dict[str, object], key: str) -> float | None:
        value = diagnostics.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    @staticmethod
    def _context_match_score(current: FireContext, sample: FireContext) -> float:
        tag_score = DynamicClusterGun._tag_match_ratio(current, sample)
        flight_score = 1.0 - clamp(DynamicClusterGun._flight_time_delta(current, sample) / 0.5, 0.0, 1.0)
        wall_score = 1.0 - clamp(abs(current.wall_escape_balance - sample.wall_escape_balance), 0.0, 1.0)
        lateral_score = min(current.lateral_direction_confidence, sample.lateral_direction_confidence)
        return clamp((tag_score + flight_score + wall_score + lateral_score) / 4.0, 0.0, 1.0)

    def _aim_confidence(
        self,
        maturity_sample_count: float,
        avg_distance: float,
        peak_margin: float,
        neighbor_agreement: float,
        context_match: float,
    ) -> float:
        sample_maturity = clamp(maturity_sample_count / max(1, self.config.confidence_mature_samples), 0.0, 1.0)
        neighbor_quality = 1.0 - clamp(avg_distance / max(1e-6, self.config.confidence_max_neighbor_distance), 0.0, 1.0)
        peak_quality = clamp(peak_margin / max(1e-6, self.config.confidence_peak_margin_reference), 0.0, 1.0)
        return clamp(sample_maturity * neighbor_quality * peak_quality * neighbor_agreement * context_match, 0.0, 1.0)

    @staticmethod
    def _tag_match_ratio(left: FireContext, right: FireContext) -> float:
        tags = left.movement_tags.union(right.movement_tags)
        if not tags:
            return 1.0
        return len(left.movement_tags.intersection(right.movement_tags)) / len(tags)

    @staticmethod
    def _flight_time_delta(left: FireContext, right: FireContext) -> float:
        return abs(left.bullet_flight_time - right.bullet_flight_time) / max(left.bullet_flight_time, 1.0)

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

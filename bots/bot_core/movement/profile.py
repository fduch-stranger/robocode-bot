from dataclasses import dataclass

from bot_core.geometry.numeric import clamp
from bot_core.movement.config import MovementFlatteningConfig
from bot_core.movement.waves import MovementWave


@dataclass(frozen=True)
class MovementStatsBufferSpec:
    name: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class MovementStatsBufferDanger:
    name: str
    danger: float
    samples: float


class MovementStatsBuffer:
    def __init__(self, spec: MovementStatsBufferSpec, config: MovementFlatteningConfig) -> None:
        self.spec = spec
        self.config = config
        self._visits: dict[tuple[int, tuple[int, ...], int], float] = {}
        self._samples: dict[tuple[int, tuple[int, ...]], float] = {}

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> None:
        segment = self._segment(wave)
        self._decay_segment(wave.target_id, segment)
        key = (wave.target_id, segment, bin_index)
        self._visits[key] = self._visits.get(key, 0.0) + weight
        sample_key = (wave.target_id, segment)
        self._samples[sample_key] = self._samples.get(sample_key, 0.0) + weight

    def danger(self, wave: MovementWave, bin_index: int) -> MovementStatsBufferDanger:
        segment = self._segment(wave)
        score = 0.0
        for offset, smooth_weight in ((0, 1.0), (-1, 0.55), (1, 0.55), (-2, 0.25), (2, 0.25)):
            neighbor = bin_index + offset
            if 0 <= neighbor < self.config.bin_count:
                score += self._visits.get((wave.target_id, segment, neighbor), 0.0) * smooth_weight
        samples = self._samples.get((wave.target_id, segment), 0.0)
        return MovementStatsBufferDanger(self.spec.name, score, samples)

    def remove_target(self, target_id: int) -> None:
        self._visits = {key: value for key, value in self._visits.items() if key[0] != target_id}
        self._samples = {key: value for key, value in self._samples.items() if key[0] != target_id}

    def _decay_segment(self, target_id: int, segment: tuple[int, ...]) -> None:
        decay = self.config.stats_buffer_decay
        sample_key = (target_id, segment)
        total = 0.0
        for key in list(self._visits):
            if key[0] == target_id and key[1] == segment:
                decayed = self._visits[key] * decay
                if decayed < 0.001:
                    del self._visits[key]
                else:
                    self._visits[key] = decayed
                    total += decayed
        if total > 0.0:
            self._samples[sample_key] = total
        else:
            self._samples.pop(sample_key, None)

    def _segment(self, wave: MovementWave) -> tuple[int, ...]:
        return tuple(self._bucket(wave, dimension) for dimension in self.spec.dimensions)

    @staticmethod
    def _bucket(wave: MovementWave, dimension: str) -> int:
        features = wave.features
        if dimension == "distance":
            return wave.distance_bucket
        if dimension == "lateral":
            return round(clamp((features.lateral_velocity + 8.0) / 4.0, 0.0, 4.0))
        if dimension == "advancing":
            return round(clamp((features.advancing_velocity + 8.0) / 4.0, 0.0, 4.0))
        if dimension == "flight":
            if features.bullet_flight_time < 18:
                return 0
            if features.bullet_flight_time < 32:
                return 1
            return 2
        if dimension == "accel":
            if features.acceleration < -0.4:
                return 0
            if features.acceleration > 0.4:
                return 2
            return 1
        if dimension == "dir_age":
            if features.direction_change_age < 8:
                return 0
            if features.direction_change_age < 28:
                return 1
            return 2
        if dimension == "decel_age":
            if features.decel_age < 8:
                return 0
            if features.decel_age < 28:
                return 1
            return 2
        if dimension == "wall":
            if features.wall_distance < 90:
                return 0
            if features.wall_distance < 180:
                return 1
            return 2
        return 0


class MovementStatsBufferSet:
    SPECS: tuple[MovementStatsBufferSpec, ...] = (
        MovementStatsBufferSpec("distance", ("distance",)),
        MovementStatsBufferSpec("lateral", ("lateral",)),
        MovementStatsBufferSpec("advancing", ("advancing",)),
        MovementStatsBufferSpec("accel", ("accel",)),
        MovementStatsBufferSpec("wall", ("wall",)),
        MovementStatsBufferSpec("flight", ("flight",)),
        MovementStatsBufferSpec("distance_lateral", ("distance", "lateral")),
        MovementStatsBufferSpec("distance_wall", ("distance", "wall")),
        MovementStatsBufferSpec("distance_flight", ("distance", "flight")),
        MovementStatsBufferSpec("lateral_accel", ("lateral", "accel")),
        MovementStatsBufferSpec("lateral_wall", ("lateral", "wall")),
        MovementStatsBufferSpec("distance_decel", ("distance", "decel_age")),
    )

    def __init__(self, config: MovementFlatteningConfig) -> None:
        self.config = config
        self._buffers = [MovementStatsBuffer(spec, config) for spec in self.SPECS]

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> None:
        if not self.config.stats_buffer_enabled:
            return
        for buffer in self._buffers:
            buffer.record(wave, bin_index, weight)

    def danger(self, wave: MovementWave, bin_index: int) -> MovementStatsBufferDanger:
        if not self.config.stats_buffer_enabled:
            return MovementStatsBufferDanger("disabled", 0.0, 0.0)
        dangers = [buffer.danger(wave, bin_index) for buffer in self._buffers]
        if not dangers:
            return MovementStatsBufferDanger("empty", 0.0, 0.0)
        weighted_danger = 0.0
        total_weight = 0.0
        total_samples = 0.0
        top = max(dangers, key=lambda item: item.danger)
        for danger in dangers:
            confidence = clamp(
                danger.samples / max(1.0, self.config.stats_buffer_min_samples),
                0.0,
                1.0,
            )
            if confidence <= 0.0:
                continue
            weighted_danger += danger.danger * confidence
            total_weight += confidence
            total_samples += danger.samples
        if total_weight <= 0.0:
            return MovementStatsBufferDanger(top.name, 0.0, 0.0)
        return MovementStatsBufferDanger(top.name, weighted_danger / total_weight, total_samples / len(dangers))

    def remove_target(self, target_id: int) -> None:
        for buffer in self._buffers:
            buffer.remove_target(target_id)


class MovementProfile:
    def __init__(self, config: MovementFlatteningConfig) -> None:
        self.config = config
        self.profile: dict[tuple[int, int, int], float] = {}
        self.stats_buffers = MovementStatsBufferSet(config)

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> float:
        key = (wave.target_id, wave.distance_bucket, bin_index)
        self.profile[key] = self.profile.get(key, 0.0) + weight
        self.stats_buffers.record(wave, bin_index, weight)
        self.decay_if_needed(wave.target_id)
        return self.profile[key]

    def smoothed_count(self, target_id: int, bucket: int, bin_index: int) -> float:
        score = 0.0
        for offset, weight in ((0, 1.0), (-1, 0.55), (1, 0.55), (-2, 0.25), (2, 0.25)):
            neighbor = bin_index + offset
            if 0 <= neighbor < self.config.bin_count:
                score += self.profile.get((target_id, bucket, neighbor), 0.0) * weight
        return score

    def remove_target(self, target_id: int) -> None:
        for key in list(self.profile):
            if key[0] == target_id:
                del self.profile[key]
        self.stats_buffers.remove_target(target_id)

    def decay_if_needed(self, target_id: int) -> None:
        total = sum(value for key, value in self.profile.items() if key[0] == target_id)
        if total <= self.config.profile_decay_after:
            return
        for key in list(self.profile):
            if key[0] == target_id:
                self.profile[key] *= 0.5

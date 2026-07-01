from dataclasses import dataclass, field

from bot_core.gun.models import GunSample


@dataclass
class RollingKnnBuffer:
    max_samples: int
    max_samples_per_target: int
    _samples_by_target: dict[int, list[GunSample]] = field(default_factory=dict)
    _sample_count: int = 0

    @property
    def sample_count(self) -> int:
        return self._sample_count

    def add(self, sample: GunSample) -> None:
        samples = self._samples_by_target.setdefault(sample.target_id, [])
        samples.append(sample)
        self._sample_count += 1
        self._trim_target(sample.target_id)
        self._trim_global()

    def samples_for(self, target_id: int) -> list[GunSample]:
        return self._samples_by_target.get(target_id, [])

    def target_sample_count(self, target_id: int) -> int:
        return len(self._samples_by_target.get(target_id, []))

    def decayed_weight(self, sample: GunSample, current_turn: int, half_life: float) -> float:
        if half_life <= 0:
            return 1.0
        age = max(0, current_turn - sample.turn)
        return 0.5 ** (age / half_life)

    def effective_count(self, target_id: int, current_turn: int, half_life: float) -> float:
        return sum(self.decayed_weight(sample, current_turn, half_life) for sample in self.samples_for(target_id))

    def clear(self) -> None:
        self._samples_by_target.clear()
        self._sample_count = 0

    def _trim_target(self, target_id: int) -> None:
        samples = self._samples_by_target.get(target_id)
        if samples is None or len(samples) <= self.max_samples_per_target:
            return
        removed = len(samples) - self.max_samples_per_target
        del samples[:removed]
        self._sample_count -= removed

    def _trim_global(self) -> None:
        while self._sample_count > self.max_samples:
            oldest_target = None
            oldest_turn = None
            for target_id, samples in self._samples_by_target.items():
                if not samples:
                    continue
                if oldest_turn is None or samples[0].turn < oldest_turn:
                    oldest_target = target_id
                    oldest_turn = samples[0].turn
            if oldest_target is None:
                self._sample_count = 0
                return
            samples = self._samples_by_target[oldest_target]
            del samples[0]
            self._sample_count -= 1
            if not samples:
                del self._samples_by_target[oldest_target]

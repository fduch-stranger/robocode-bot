import math
from dataclasses import dataclass, field

from bot_core.gun.utils import guess_factor_to_bin


@dataclass
class DecayedGuessFactorProfile:
    visits: int = 0
    effective_weight: float = 0.0
    bins: list[float] = field(default_factory=list)

    @classmethod
    def with_bins(cls, bin_count: int) -> "DecayedGuessFactorProfile":
        return cls(bins=[0.0] * bin_count)

    def record(self, guess_factor: float, bin_count: int, smoothing_bins: float, decay: float) -> None:
        self.visits += 1
        self.effective_weight = self.effective_weight * decay + 1.0
        bin_index = guess_factor_to_bin(guess_factor, bin_count)
        for index in range(bin_count):
            self.bins[index] *= decay
            offset = (index - bin_index) / smoothing_bins
            self.bins[index] += math.exp(-(offset * offset))

    def normalized_bin(self, index: int) -> float:
        return self.bins[index] / max(0.001, self.effective_weight)


__all__ = ["DecayedGuessFactorProfile"]

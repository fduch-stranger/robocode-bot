"""``voidious.utils.KnnView``: one kd-tree of timestamped observations plus the
knobs (weight, k, thresholds, decay) that the guns and the surfer read."""
from __future__ import annotations

from diamond_port.dia_utils import DistanceFormula, Timestamped, limit, power
from diamond_port.kd_tree import Entry, KdTree

NO_DECAY = 0.0


class KnnView:
    _name_index = 0

    def __init__(self, formula: DistanceFormula) -> None:
        self.formula = formula
        self.weight = 1.0
        self.k_size = 1
        self.k_divisor = 1
        self.max_data_points = 0
        self.log_bullet_hits = False
        self.log_visits = False
        self.log_virtual = False
        self.log_melee = False
        self.hit_threshold = 0.0
        self.padded_hit_threshold = 0.0
        self.decay_rate = NO_DECAY
        self.name = f"view-{KnnView._name_index}"
        KnnView._name_index += 1
        self._tree: KdTree | None = None
        self._init_tree()
        self.cached_neighbors: dict[int, list[Entry]] = {}

    def _init_tree(self) -> None:
        self._tree = KdTree(len(self.formula.weights), None if self.max_data_points == 0 else self.max_data_points)
        self._tree.set_weights(self.formula.weights)

    def set_formula(self, formula: DistanceFormula) -> "KnnView":
        self.formula = formula
        self._init_tree()
        return self

    def set_weight(self, weight: float) -> "KnnView":
        self.weight = weight
        return self

    def set_k(self, k_size: int) -> "KnnView":
        self.k_size = k_size
        return self

    def set_k_divisor(self, k_divisor: int) -> "KnnView":
        self.k_divisor = k_divisor
        return self

    def bullet_hits_on(self) -> "KnnView":
        self.log_bullet_hits = True
        return self

    def visits_on(self) -> "KnnView":
        self.log_visits = True
        return self

    def virtual_waves_on(self) -> "KnnView":
        self.log_virtual = True
        return self

    def melee_on(self) -> "KnnView":
        self.log_melee = True
        return self

    def set_hit_threshold(self, hit_threshold: float) -> "KnnView":
        self.hit_threshold = hit_threshold
        return self

    def set_padded_hit_threshold(self, padded_hit_threshold: float) -> "KnnView":
        self.padded_hit_threshold = padded_hit_threshold
        return self

    def set_max_data_points(self, max_data_points: int) -> "KnnView":
        self.max_data_points = max_data_points
        self._init_tree()
        return self

    def set_decay_rate(self, decay_rate: float) -> "KnnView":
        self.decay_rate = decay_rate
        return self

    def set_name(self, name: str) -> "KnnView":
        self.name = name
        return self

    def log_wave(self, wave, value) -> list[float]:
        data_point = self.formula.data_point_from_wave(wave)
        self._tree.add_point(data_point, value)
        return data_point

    def clear_cache(self) -> None:
        self.cached_neighbors.clear()

    def enabled(self, hit_percentage: float, margin_of_error: float) -> bool:
        return (
            self.size() > 0
            and hit_percentage >= self.hit_threshold
            and max(0.0, hit_percentage - margin_of_error) >= self.padded_hit_threshold
        )

    def size(self) -> int:
        return self._tree.size()

    def nearest_neighbors(self, wave, aiming: bool, k: int | None = None) -> list[Entry]:
        if k is None:
            k = int(limit(1, self.size() // self.k_divisor, self.k_size))
        wave_point = self.formula.data_point_from_wave(wave, aiming)
        return self._tree.nearest_neighbor(wave_point, k)

    def set_weights(self, weights: list[float]) -> None:
        self.formula.weights = weights
        self._tree.set_weights(weights)

    def get_decay_weights(self, entries: list[Entry]) -> dict[Timestamped, float]:
        weight_map: dict[Timestamped, float] = {}
        num_scans = len(entries)
        if self.decay_rate == NO_DECAY:
            for entry in entries:
                weight_map[entry.value] = 1.0
        else:
            ordered = sorted((entry.value for entry in entries), key=Timestamped.sort_key)
            for x, value in enumerate(ordered):
                weight_map[value] = 1.0 / power(self.decay_rate, num_scans - x - 1)
        return weight_map

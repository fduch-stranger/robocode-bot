class EnemyEnergyCorrectionLedger:
    def __init__(self, max_entries_per_target: int = 8) -> None:
        self.max_entries_per_target = max_entries_per_target
        self._corrections: dict[int, list[tuple[int, float, str]]] = {}

    def record(self, target_id: int, turn_number: int, correction: float, reason: str) -> None:
        corrections = self._corrections.setdefault(target_id, [])
        corrections.append((turn_number, correction, reason))
        if len(corrections) > self.max_entries_per_target:
            del corrections[: len(corrections) - self.max_entries_per_target]

    def consume(self, target_id: int, current_turn: int, after_turn: int) -> float:
        corrections = self._corrections.get(target_id)
        if not corrections:
            return 0.0

        correction = 0.0
        remaining: list[tuple[int, float, str]] = []
        for turn, value, reason in corrections:
            if turn > current_turn:
                remaining.append((turn, value, reason))
            elif turn > after_turn:
                correction += value

        if remaining:
            self._corrections[target_id] = remaining
        else:
            self._corrections.pop(target_id, None)
        return correction

    def clear(self) -> None:
        self._corrections.clear()

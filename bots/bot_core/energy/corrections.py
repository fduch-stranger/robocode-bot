# The server records scanned energy before it resolves bullet hits, so a hit reported on
# turn T first shows up in scans from turn T + 1.
BULLET_HIT_SCAN_DELAY_TURNS = 1


class EnemyEnergyCorrectionLedger:
    def __init__(self, max_entries_per_target: int = 8) -> None:
        self.max_entries_per_target = max_entries_per_target
        self._corrections: dict[int, list[tuple[int, float, str]]] = {}

    def record(
        self,
        target_id: int,
        turn_number: int,
        correction: float,
        reason: str,
        *,
        scan_delay_turns: int = BULLET_HIT_SCAN_DELAY_TURNS,
    ) -> None:
        corrections = self._corrections.setdefault(target_id, [])
        corrections.append((turn_number + scan_delay_turns, correction, reason))
        if len(corrections) > self.max_entries_per_target:
            del corrections[: len(corrections) - self.max_entries_per_target]

    def consume(self, target_id: int, current_turn: int, after_turn: int) -> float:
        """Sum corrections visible in the scan at current_turn but not in the scan at after_turn."""
        corrections = self._corrections.get(target_id)
        if not corrections:
            return 0.0

        correction = 0.0
        remaining: list[tuple[int, float, str]] = []
        for visible_turn, value, reason in corrections:
            if visible_turn > current_turn:
                remaining.append((visible_turn, value, reason))
            elif visible_turn > after_turn:
                correction += value

        if remaining:
            self._corrections[target_id] = remaining
        else:
            self._corrections.pop(target_id, None)
        return correction

    def clear(self) -> None:
        self._corrections.clear()

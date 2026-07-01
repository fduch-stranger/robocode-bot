from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass

from bot_core.tank_math import TargetSnapshot


class TargetMemory(MutableMapping[int, TargetSnapshot]):
    def __init__(self) -> None:
        self._targets: dict[int, TargetSnapshot] = {}

    def __getitem__(self, key: int) -> TargetSnapshot:
        return self._targets[key]

    def __setitem__(self, key: int, value: TargetSnapshot) -> None:
        self._targets[key] = value

    def __delitem__(self, key: int) -> None:
        del self._targets[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._targets)

    def __len__(self) -> int:
        return len(self._targets)

    def stale_ids(self, turn_number: int, max_age: int) -> list[int]:
        return [
            bot_id
            for bot_id, target in self._targets.items()
            if turn_number - target.seen_turn > max_age
        ]

    def fresh_targets(self, turn_number: int, max_age: int) -> list[TargetSnapshot]:
        return [
            target
            for target in self._targets.values()
            if turn_number - target.seen_turn <= max_age
        ]

    def active_fire_threat(
        self,
        threat_id: int | None,
        threat_turn: int,
        turn_number: int,
        memory_turns: int,
    ) -> TargetSnapshot | None:
        if threat_id is None:
            return None
        if turn_number - threat_turn > memory_turns:
            return None
        return self._targets.get(threat_id)


@dataclass(frozen=True)
class TargetSelection:
    target: TargetSnapshot
    previous_id: int | None
    fresh_candidates: int
    score: float

    @property
    def changed(self) -> bool:
        return self.previous_id != self.target.bot_id


class TargetSelector:
    def __init__(self, reacquire_turns: int) -> None:
        self.reacquire_turns = reacquire_turns

    def select(
        self,
        targets: TargetMemory,
        current_target_id: int | None,
        turn_number: int,
        score: Callable[[TargetSnapshot], float],
    ) -> TargetSelection | None:
        if not targets:
            return None

        fresh_targets = targets.fresh_targets(turn_number, self.reacquire_turns)
        candidates = fresh_targets if fresh_targets else list(targets.values())
        target = min(candidates, key=score)
        return TargetSelection(
            target=target,
            previous_id=current_target_id,
            fresh_candidates=len(fresh_targets),
            score=score(target),
        )

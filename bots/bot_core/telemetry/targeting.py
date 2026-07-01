from bot_core.target_snapshot import TargetSnapshot
from bot_core.telemetry.sink import TelemetrySink
from bot_core.targeting import TargetSelection


class TargetingTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink

    def record_scan_new(self, target_id: int, energy: float, x: float, y: float) -> None:
        self._sink.log("scan.new", **_scan_new_fields(target_id, energy, x, y))

    def record_scan_reacquired(
        self,
        target_id: int,
        age: int,
        previous: TargetSnapshot,
        x: float,
        y: float,
    ) -> None:
        self._sink.log("scan.reacquired", **_scan_reacquired_fields(target_id, age, previous, x, y))

    def record_target_selection(self, selection: TargetSelection, known_targets: int) -> None:
        self._sink.log("target.select", **_target_selection_fields(selection, known_targets))

    def record_candidate_selection(
        self,
        previous_id: int | None,
        selected: TargetSnapshot,
        score: float,
        candidate: TargetSnapshot,
        candidate_score: float,
        previous_age: int | None,
        known_targets: int,
    ) -> None:
        self._sink.log(
            "target.select",
            **_candidate_target_selection_fields(previous_id, selected, score, candidate, candidate_score, previous_age, known_targets),
        )

    def record_target_drop_lost(
        self,
        target: TargetSnapshot,
        age: int,
        distance: float,
        known_targets: int,
    ) -> None:
        self._sink.log("target.drop_lost", **_target_drop_lost_fields(target, age, distance, known_targets))


def _scan_new_fields(target_id: int, energy: float, x: float, y: float) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "energy": round(energy, 1),
        "x": round(x, 1),
        "y": round(y, 1),
    }


def _scan_reacquired_fields(
    target_id: int,
    previous_age: int,
    previous: TargetSnapshot,
    x: float,
    y: float,
) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "previous_age": previous_age,
        "previous_x": round(previous.x, 1),
        "previous_y": round(previous.y, 1),
        "x": round(x, 1),
        "y": round(y, 1),
    }


def _target_selection_fields(selection: TargetSelection, known_targets: int) -> dict[str, object]:
    return {
        "previous": selection.previous_id,
        "selected": selection.target.bot_id,
        "score": round(selection.score, 1),
        "fresh_candidates": selection.fresh_candidates,
        "known_targets": known_targets,
    }


def _candidate_target_selection_fields(
    previous_id: int | None,
    selected: TargetSnapshot,
    score: float,
    candidate: TargetSnapshot,
    candidate_score: float,
    previous_age: int | None,
    known_targets: int,
) -> dict[str, object]:
    return {
        "previous": previous_id,
        "selected": selected.bot_id,
        "score": round(score, 1),
        "candidate": candidate.bot_id,
        "candidate_score": round(candidate_score, 1),
        "previous_age": previous_age,
        "known_targets": known_targets,
    }


def _target_drop_lost_fields(target: TargetSnapshot, age: int, distance: float, known_targets: int) -> dict[str, object]:
    return {
        "bot_id": target.bot_id,
        "age": age,
        "cached_x": round(target.x, 1),
        "cached_y": round(target.y, 1),
        "cached_distance": round(distance, 1),
        "known_targets": known_targets,
    }

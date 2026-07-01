from bot_core.target_snapshot import TargetSnapshot
from bot_core.targeting import TargetSelection


def scan_new_fields(target_id: int, energy: float, x: float, y: float) -> dict[str, object]:
    return {
        "bot_id": target_id,
        "energy": round(energy, 1),
        "x": round(x, 1),
        "y": round(y, 1),
    }


def scan_reacquired_fields(
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


def target_selection_fields(selection: TargetSelection, known_targets: int) -> dict[str, object]:
    return {
        "previous": selection.previous_id,
        "selected": selection.target.bot_id,
        "score": round(selection.score, 1),
        "fresh_candidates": selection.fresh_candidates,
        "known_targets": known_targets,
    }


def candidate_target_selection_fields(
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


def target_drop_lost_fields(target: TargetSnapshot, age: int, distance: float, known_targets: int) -> dict[str, object]:
    return {
        "bot_id": target.bot_id,
        "age": age,
        "cached_x": round(target.x, 1),
        "cached_y": round(target.y, 1),
        "cached_distance": round(distance, 1),
        "known_targets": known_targets,
    }

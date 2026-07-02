from bot_core.gun.models import AimSolution


def should_log_switch_decision(aim: AimSolution, current_turn: int, last_logged_turn: int, interval: int) -> bool:
    if not aim.switch_candidates:
        return False
    if aim.mode_changed:
        return True

    blocked_better = any(
        candidate.available
        and candidate.reason in {"visits", "score_floor", "margin"}
        and candidate.score > candidate.current_score
        for candidate in aim.switch_candidates
    )
    return blocked_better and current_turn - last_logged_turn >= interval

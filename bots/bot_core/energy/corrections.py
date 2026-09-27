from bot_core.physics.rules import MAX_ROBOT_SPEED, ROBOT_ACCELERATION, ROBOT_DECELERATION, wall_collision_damage_for_speed

# The server records scanned energy before it resolves bullet hits, so a hit reported on
# turn T first shows up in scans from turn T + 1. Wall and ram damage is applied before the
# scan, so it shows up in the same turn's scan (delay 0).
BULLET_HIT_SCAN_DELAY_TURNS = 1
SAME_TURN_SCAN_DELAY_TURNS = 0
BOT_HALF_WIDTH = 18.0
RAM_DAMAGE = 0.6


def enemy_wall_hit_damage_bound(
    previous_speed: float,
    current_speed: float,
    x: float,
    y: float,
    arena_width: float,
    arena_height: float,
    *,
    wall_tolerance: float = 1.0,
) -> float:
    """Upper bound of wall damage an enemy took between consecutive scans, or 0 if it did not hit a wall.

    A wall collision zeroes speed and leaves the bot pinned at the wall margin. The collision
    speed is unknown but at most one acceleration step above the previous scan's speed.
    """
    if current_speed != 0.0 or previous_speed == 0.0:
        return 0.0
    wall_distance = min(x, arena_width - x, y, arena_height - y) - BOT_HALF_WIDTH
    if wall_distance > wall_tolerance:
        return 0.0
    # A bot that braked to zero without a collision had |speed| <= deceleration last scan.
    if abs(previous_speed) <= ROBOT_DECELERATION:
        return 0.0
    collision_speed = min(MAX_ROBOT_SPEED, abs(previous_speed) + ROBOT_ACCELERATION)
    return wall_collision_damage_for_speed(collision_speed)


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

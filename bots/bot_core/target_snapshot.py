from collections.abc import Iterable
from dataclasses import dataclass

from robocode_tank_royale.bot_api.events import HitBotEvent, ScannedBotEvent


@dataclass
class TargetSnapshot:
    bot_id: int
    energy: float
    x: float
    y: float
    direction: float
    speed: float
    seen_turn: int


def target_age(turn_number: int, target: TargetSnapshot) -> int:
    return turn_number - target.seen_turn


def oldest_seen_target(targets: Iterable[TargetSnapshot], turn_number: int) -> TargetSnapshot | None:
    oldest: TargetSnapshot | None = None
    oldest_age = -1
    for target in targets:
        age = target_age(turn_number, target)
        if age > oldest_age:
            oldest = target
            oldest_age = age
    return oldest


def target_from_scan(event: ScannedBotEvent, turn_number: int) -> TargetSnapshot:
    return TargetSnapshot(
        bot_id=event.scanned_bot_id,
        energy=event.energy,
        x=event.x,
        y=event.y,
        direction=event.direction,
        speed=event.speed,
        seen_turn=turn_number,
    )


def target_from_hit_bot(
    event: HitBotEvent,
    turn_number: int,
    previous: TargetSnapshot | None = None,
) -> TargetSnapshot:
    return TargetSnapshot(
        bot_id=event.victim_id,
        energy=event.energy,
        x=event.x,
        y=event.y,
        direction=previous.direction if previous is not None else 0,
        speed=previous.speed if previous is not None else 0,
        seen_turn=turn_number,
    )


def interpolate_target(previous: TargetSnapshot, current: TargetSnapshot, turn_number: int) -> TargetSnapshot:
    elapsed = current.seen_turn - previous.seen_turn
    if elapsed <= 0:
        return current
    ratio = min(1.0, max(0.0, (turn_number - previous.seen_turn) / elapsed))
    return TargetSnapshot(
        bot_id=current.bot_id,
        energy=current.energy,
        x=previous.x + (current.x - previous.x) * ratio,
        y=previous.y + (current.y - previous.y) * ratio,
        direction=current.direction,
        speed=previous.speed + (current.speed - previous.speed) * ratio,
        seen_turn=turn_number,
    )

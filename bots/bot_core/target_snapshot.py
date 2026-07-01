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


def target_from_hit_bot(event: HitBotEvent, turn_number: int) -> TargetSnapshot:
    return TargetSnapshot(
        bot_id=event.victim_id,
        energy=event.energy,
        x=event.x,
        y=event.y,
        direction=0,
        speed=0,
        seen_turn=turn_number,
    )

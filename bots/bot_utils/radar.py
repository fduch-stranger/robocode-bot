from collections.abc import Iterable
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_utils.tank_math import TargetSnapshot, bearing_to, clamp, oldest_seen_target


@dataclass(frozen=True)
class RadarLockConfig:
    search_rate: float
    lock_rate: float = 24
    reacquire_rate: float = 24
    rescan_interval: int = 30
    rescan_turns: int = 5
    reacquire_min_error: float = 8
    lock_overscan: float = 12
    reacquire_overscan: float = 24
    fresh_turns: int = 1


@dataclass(frozen=True)
class RadarCommand:
    target: TargetSnapshot
    turn: float
    mode: str
    bearing: float
    age: int


def choose_radar_target(
    targets: Iterable[TargetSnapshot],
    fire_target: TargetSnapshot,
    turn_number: int,
    fire_memory_turns: int,
    config: RadarLockConfig,
) -> TargetSnapshot:
    known_targets = list(targets)
    oldest = oldest_seen_target(known_targets, turn_number)
    if oldest is None or len(known_targets) == 1:
        return fire_target
    if turn_number % config.rescan_interval < config.rescan_turns:
        return oldest
    if turn_number - fire_target.seen_turn <= fire_memory_turns:
        return fire_target
    return oldest


def lock_radar_to_target(bot: Bot, target: TargetSnapshot, config: RadarLockConfig) -> RadarCommand:
    radar_bearing = bearing_to(bot, target.x, target.y, bot.radar_direction)
    age = bot.turn_number - target.seen_turn

    if age <= config.fresh_turns:
        direction = 1 if radar_bearing >= 0 else -1
        radar_turn = clamp(
            radar_bearing * 1.8 + config.lock_overscan * direction,
            -config.lock_rate,
            config.lock_rate,
        )
        bot.set_turn_radar_left(radar_turn)
        return RadarCommand(target, radar_turn, "lock", radar_bearing, age)

    if abs(radar_bearing) > config.reacquire_min_error:
        direction = 1 if radar_bearing > 0 else -1
        radar_turn = clamp(
            radar_bearing + config.reacquire_overscan * direction,
            -config.reacquire_rate,
            config.reacquire_rate,
        )
        bot.set_turn_radar_left(radar_turn)
        return RadarCommand(target, radar_turn, "reacquire", radar_bearing, age)

    bot.radar_turn_rate = config.search_rate
    return RadarCommand(target, config.search_rate, "widen", radar_bearing, age)


def lock_priority_radar(
    bot: Bot,
    targets: Iterable[TargetSnapshot],
    fire_target: TargetSnapshot,
    fire_memory_turns: int,
    config: RadarLockConfig,
) -> RadarCommand:
    radar_target = choose_radar_target(
        targets,
        fire_target,
        bot.turn_number,
        fire_memory_turns,
        config,
    )
    return lock_radar_to_target(bot, radar_target, config)

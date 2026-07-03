import math
from collections.abc import Iterable
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.angles import bearing_to
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import distance_to
from bot_core.target_snapshot import TargetSnapshot, oldest_seen_target


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
    lock_prediction_turns: int = 3
    lock_enemy_width: float = 36
    lock_min_overscan: float = 2
    lock_max_overscan: float = 8
    lock_overscan_scale: float = 1.2
    lock_field_margin: float = 18


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


def predict_radar_lock_point(
    bot: Bot,
    target: TargetSnapshot,
    lead_ticks: int,
    field_margin: float,
) -> tuple[float, float]:
    heading = math.radians(target.direction)
    predicted_x = target.x + math.cos(heading) * target.speed * lead_ticks
    predicted_y = target.y + math.sin(heading) * target.speed * lead_ticks
    return (
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
    )


def lock_overscan_for_distance(distance: float, config: RadarLockConfig) -> float:
    angular_width = math.degrees(
        2 * math.atan((config.lock_enemy_width / 2) / max(distance, 1.0))
    )
    max_overscan = max(config.lock_min_overscan, min(config.lock_max_overscan, config.lock_overscan))
    return clamp(
        angular_width * config.lock_overscan_scale,
        config.lock_min_overscan,
        max_overscan,
    )


def lock_radar_to_target(bot: Bot, target: TargetSnapshot, config: RadarLockConfig) -> RadarCommand:
    radar_bearing = bearing_to(bot, target.x, target.y, bot.radar_direction)
    age = bot.turn_number - target.seen_turn

    if age <= config.fresh_turns:
        lead_ticks = max(1, min(config.lock_prediction_turns, age + 1))
        lock_x, lock_y = predict_radar_lock_point(
            bot,
            target,
            lead_ticks,
            config.lock_field_margin,
        )
        lock_bearing = bearing_to(bot, lock_x, lock_y, bot.radar_direction)
        direction = 1 if lock_bearing >= 0 else -1
        overscan = lock_overscan_for_distance(distance_to(bot, lock_x, lock_y), config)
        radar_turn = clamp(
            lock_bearing * 1.8 + overscan * direction,
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

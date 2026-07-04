import math
from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_core.geometry.angles import absolute_bearing_between
from bot_core.geometry.numeric import clamp
from bot_core.geometry.waves import escape_angle_for_guess_factor, wall_limited_escape_angle
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.models import FireContext, GunWave, TargetMotion, TargetPosition
from bot_core.gun.utils import bucket, lateral_direction
from bot_core.physics import bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


@dataclass(frozen=True)
class AimContext:
    bot: Bot
    target: TargetSnapshot
    distance: float
    firepower: float
    motion: TargetMotion
    field_margin: float
    features: tuple[float, ...]
    segment_key: tuple[int, ...]
    disabled_modes: frozenset[str] = frozenset()
    movement_tags: frozenset[str] = frozenset()
    fire_context: FireContext = field(default_factory=FireContext)


@dataclass(frozen=True)
class GunBearing:
    mode: str
    absolute_bearing: float
    guess_factor: float | None = None
    decision_context: GunDecisionContext | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GunVisit:
    wave: GunWave
    actual_bearing: float
    target_distance: float
    guess_factor: float
    segment_key: tuple[int, ...]
    is_evaluation: bool = False


class TargetHistoryStore:
    def __init__(self, max_history: int) -> None:
        self.max_history = max_history
        self._history: dict[int, list[TargetPosition]] = {}

    def observe_target(self, target: TargetSnapshot, bot: Bot | None = None) -> None:
        history = self._history.setdefault(target.bot_id, [])
        position = self._position_from_target(target, bot)
        if history and history[-1].turn == target.seen_turn:
            history[-1] = position
        else:
            history.append(position)
        if len(history) > self.max_history:
            del history[: len(history) - self.max_history]

    @staticmethod
    def _position_from_target(target: TargetSnapshot, bot: Bot | None) -> TargetPosition:
        if bot is None:
            return TargetPosition(
                target.seen_turn,
                target.x,
                target.y,
                target.speed,
                target.direction,
            )
        bot_x = float(bot.x)
        bot_y = float(bot.y)
        arena_width = float(bot.arena_width)
        arena_height = float(bot.arena_height)
        absolute_bearing = math.radians(absolute_bearing_between(bot_x, bot_y, target.x, target.y))
        lateral_speed, advancing_speed = _target_velocity_components(target, absolute_bearing)
        arena_scale = max(arena_width, arena_height)
        wall_margin = min(
            target.x,
            arena_width - target.x,
            target.y,
            arena_height - target.y,
        ) / arena_scale
        return TargetPosition(
            target.seen_turn,
            target.x,
            target.y,
            target.speed,
            target.direction,
            math.degrees(absolute_bearing),
            lateral_speed,
            advancing_speed,
            wall_margin,
        )

    def history_for(self, target_id: int) -> list[TargetPosition]:
        return self._history.get(target_id, [])

    def previous_position(self, target: TargetSnapshot) -> TargetPosition | None:
        for position in reversed(self._history.get(target.bot_id, [])):
            if position.turn < target.seen_turn:
                return position
        return None

    def wave_visit_position(
        self,
        bot: Bot,
        wave: GunWave,
        target: TargetSnapshot,
        visit_margin: float,
    ) -> tuple[float, float, float, float]:
        current_traveled = (bot.turn_number - wave.fire_turn) * wave.bullet_speed
        current_distance = math.hypot(target.x - wave.source_x, target.y - wave.source_y)
        previous = self.previous_position(target)
        if previous is None or previous.turn >= target.seen_turn:
            return target.x, target.y, current_traveled, current_distance

        previous_traveled = (previous.turn - wave.fire_turn) * wave.bullet_speed
        previous_distance = math.hypot(previous.x - wave.source_x, previous.y - wave.source_y)
        if previous_traveled + visit_margin >= previous_distance:
            return previous.x, previous.y, previous_traveled, previous_distance
        if current_traveled + visit_margin < current_distance:
            return target.x, target.y, current_traveled, current_distance

        low = 0.0
        high = 1.0
        elapsed = target.seen_turn - previous.turn
        for _ in range(12):
            mid = (low + high) / 2.0
            x = previous.x + (target.x - previous.x) * mid
            y = previous.y + (target.y - previous.y) * mid
            turn = previous.turn + elapsed * mid
            traveled = (turn - wave.fire_turn) * wave.bullet_speed
            distance = math.hypot(x - wave.source_x, y - wave.source_y)
            if traveled + visit_margin >= distance:
                high = mid
            else:
                low = mid

        ratio = high
        x = previous.x + (target.x - previous.x) * ratio
        y = previous.y + (target.y - previous.y) * ratio
        turn = previous.turn + elapsed * ratio
        traveled = (turn - wave.fire_turn) * wave.bullet_speed
        distance = math.hypot(x - wave.source_x, y - wave.source_y)
        return x, y, traveled, distance

    def clear_round_state(self) -> None:
        self._history.clear()

    def remove_target(self, target_id: int) -> None:
        self._history.pop(target_id, None)


def movement_context_tags(
    bot: Bot,
    target: TargetSnapshot,
    features: tuple[float, ...],
    history: list[TargetPosition],
) -> frozenset[str]:
    _, _, lateral_speed, _, acceleration, velocity_change_age, _ = features
    tags: set[str] = set()
    if lateral_speed <= 0.18:
        tags.add("low_lateral")
    if abs(acceleration) <= 0.05 and velocity_change_age >= 0.45:
        tags.add("stable_velocity")

    recent = history[-12:]
    if len(recent) < 4:
        return frozenset(tags)

    speeds = [position.speed for position in recent]
    speed_mean = sum(speeds) / len(speeds)
    speed_variance = sum((speed - speed_mean) ** 2 for speed in speeds) / len(speeds)
    speed_stdev = math.sqrt(speed_variance)
    if speed_stdev <= 0.55:
        tags.add("stable_velocity")

    headings: list[float] = []
    path_length = 0.0
    for previous, current in zip(recent, recent[1:]):
        dx = current.x - previous.x
        dy = current.y - previous.y
        step = math.hypot(dx, dy)
        if step <= 0.25:
            continue
        path_length += step
        headings.append(math.degrees(math.atan2(dy, dx)))

    if path_length < 12.0 or len(headings) < 3:
        return frozenset(tags)

    heading_turns = [
        abs(_angle_delta_degrees(current, previous))
        for previous, current in zip(headings, headings[1:])
    ]
    mean_turn = sum(heading_turns) / len(heading_turns) if heading_turns else 0.0
    net_distance = math.hypot(recent[-1].x - recent[0].x, recent[-1].y - recent[0].y)
    path_efficiency = net_distance / max(path_length, 1.0)

    if mean_turn <= 4.0 and speed_stdev <= 0.8 and path_efficiency >= 0.9:
        tags.add("stable_pattern")
    if mean_turn >= 7.0 or path_efficiency <= 0.88:
        tags.add("nonlinear_mover")
    if mean_turn >= 10.0 or speed_stdev >= 1.4:
        tags.add("adaptive_mover")
    if lateral_speed >= 0.35 and (path_efficiency <= 0.85 or mean_turn >= 9.0):
        tags.add("surfer")

    return frozenset(tags)


def _angle_delta_degrees(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def build_gun_features(
    bot: Bot,
    target: TargetSnapshot,
    distance: float,
    firepower: float,
    motion: TargetMotion,
) -> tuple[float, ...]:
    absolute_bearing = math.radians(absolute_bearing_between(bot.x, bot.y, target.x, target.y))
    lateral_velocity, advancing_velocity = _target_velocity_components(target, absolute_bearing)
    wall_margin = min(
        target.x,
        bot.arena_width - target.x,
        target.y,
        bot.arena_height - target.y,
    )
    arena_scale = max(bot.arena_width, bot.arena_height)
    return (
        distance / arena_scale,
        firepower / 3.0,
        abs(lateral_velocity) / 8.0,
        advancing_velocity / 8.0,
        clamp(motion.acceleration / 8.0, -1.0, 1.0),
        min(60, motion.velocity_change_age) / 60.0,
        wall_margin / arena_scale,
    )


def build_fire_context(
    bot: Bot,
    target: TargetSnapshot,
    distance: float,
    firepower: float,
    features: tuple[float, ...],
    movement_tags: frozenset[str],
) -> FireContext:
    absolute_bearing_degrees = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
    absolute_bearing = math.radians(absolute_bearing_degrees)
    lateral_velocity, _ = _target_velocity_components(target, absolute_bearing)
    bullet_speed = bullet_speed_for_power(firepower)
    direction = lateral_direction(target, absolute_bearing_degrees)
    positive_escape_angle = wall_limited_escape_angle(bot, target, bullet_speed, direction)
    negative_escape_angle = wall_limited_escape_angle(bot, target, bullet_speed, -direction)
    escape_total = max(positive_escape_angle + negative_escape_angle, 1e-6)
    _, _, _, _, _, _, wall_margin = features
    return FireContext(
        movement_tags=movement_tags,
        bullet_flight_time=distance / max(bullet_speed, 1e-6),
        lateral_direction=direction,
        lateral_speed_signed=lateral_velocity,
        lateral_direction_confidence=clamp(abs(lateral_velocity) / 8.0, 0.0, 1.0),
        wall_margin=wall_margin,
        wall_escape_balance=clamp((positive_escape_angle - negative_escape_angle) / escape_total, -1.0, 1.0),
        positive_escape_angle=positive_escape_angle,
        negative_escape_angle=negative_escape_angle,
        distance_bucket=bucket(features[0], 0.30, 0.55),
        firepower_bucket=bucket(features[1], 0.42, 0.62),
    )


def _target_velocity_components(target: TargetSnapshot, absolute_bearing: float) -> tuple[float, float]:
    heading = math.radians(target.direction)
    velocity_x = math.cos(heading) * target.speed
    velocity_y = math.sin(heading) * target.speed
    lateral_velocity = velocity_x * -math.sin(absolute_bearing) + velocity_y * math.cos(absolute_bearing)
    advancing_velocity = velocity_x * math.cos(absolute_bearing) + velocity_y * math.sin(absolute_bearing)
    return lateral_velocity, advancing_velocity


def guess_factor_aim_bearing(
    bot: Bot,
    target: TargetSnapshot,
    firepower: float,
    guess_factor: float,
) -> float:
    absolute_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
    bullet_speed = bullet_speed_for_power(firepower)
    lateral = lateral_direction(target, absolute_bearing)
    escape_angle = escape_angle_for_guess_factor(bot, target, bullet_speed, lateral, guess_factor)
    return absolute_bearing + guess_factor * lateral * escape_angle

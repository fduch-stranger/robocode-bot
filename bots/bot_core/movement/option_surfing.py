"""Option surfing: wave surfing over discrete options with multi-wave lookahead.

For the nearest incoming enemy wave the bot evaluates three options, orbit
clockwise, orbit counter-clockwise and stop. Each option is simulated with
Tank Royale physics until the wave has passed the bot; the learned danger is
integrated over the exact angular span the bot's body covers while the wave
breaks on it (the ring between the bullet's positions on consecutive turns
against the bot's 18 px circle), scaled by bullet damage and time to impact.
The three options are then evaluated again against the next wave from the
state where the first one passed, and the cheapest continuation is added.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bot_core.geometry.numeric import clamp
from bot_core.geometry.waves import guess_factor_from_offset
from bot_core.movement.config import MovementFlatteningConfig
from bot_core.movement.waves import MovementWave
from bot_core.physics import MAX_ROBOT_SPEED, RobotMovementState, bullet_damage_for_power, predict_robot_movement

COUNTER_CLOCKWISE = -1
STOP = 0
CLOCKWISE = 1
OPTIONS = (COUNTER_CLOCKWISE, STOP, CLOCKWISE)
OPTION_NAMES = {COUNTER_CLOCKWISE: "ccw", STOP: "stop", CLOCKWISE: "cw"}
RING_TAIL_TICKS = 6


@dataclass(frozen=True)
class OptionSurfDecision:
    option: int
    move_bearing: float
    speed: float
    danger: float
    danger_ccw: float
    danger_stop: float
    danger_cw: float
    waves: int
    wave_kind: str
    hit_turn: int
    gf_low: float
    gf_high: float
    time_to_impact: float
    direction: int

    @property
    def option_name(self) -> str:
        return OPTION_NAMES[self.option]


@dataclass(frozen=True)
class OptionResult:
    danger: float
    passed_state: RobotMovementState
    path: tuple[RobotMovementState, ...]
    hit_turn: int
    gf_low: float
    gf_high: float


def attack_angle(distance: float, preferred_distance: float, multiplier: float, max_angle: float) -> float:
    """Degrees to lean toward (positive) or away from (negative) the enemy while orbiting."""
    distance_factor = (distance - preferred_distance) / max(1.0, preferred_distance)
    return clamp(math.degrees(distance_factor * multiplier), -max_angle, max_angle)


def orbit_bearing(x: float, y: float, source_x: float, source_y: float, direction: int, lean: float) -> float:
    """Move bearing (degrees) that orbits the source in ``direction`` leaning ``lean`` degrees inward."""
    bearing_to_source = math.degrees(math.atan2(source_y - y, source_x - x))
    return bearing_to_source + (90.0 - lean) * direction


def wall_smoothed_bearing(
    x: float,
    y: float,
    move_bearing: float,
    direction: int,
    field_margin: float,
    arena_width: float,
    arena_height: float,
    wall_stick: float,
    smoothing_degrees: float,
    attempts: int,
) -> float:
    smoothing_step = -smoothing_degrees * direction
    for _ in range(attempts):
        stick_x = x + math.cos(math.radians(move_bearing)) * wall_stick
        stick_y = y + math.sin(math.radians(move_bearing)) * wall_stick
        if field_margin <= stick_x <= arena_width - field_margin and field_margin <= stick_y <= arena_height - field_margin:
            return move_bearing
        move_bearing += smoothing_step
    return move_bearing


def ring_coverage_half_width(distance: float, radius: float, inner: float, outer: float) -> float | None:
    """Angular half-width (degrees, seen from the wave source) of the part of a circle of
    ``radius`` centred ``distance`` away that lies inside the ring ``inner <= r <= outer``.

    Returns None when the ring does not touch the circle.
    """
    if distance <= radius or outer <= inner:
        return None
    if outer < distance - radius or inner > distance + radius:
        return None
    tangent = math.sqrt(distance * distance - radius * radius)
    if inner <= tangent <= outer:
        return math.degrees(math.asin(radius / distance))
    best: float | None = None
    for ring_radius in (inner, outer):
        if ring_radius <= 0 or ring_radius < distance - radius or ring_radius > distance + radius:
            continue
        cos_angle = (distance * distance + ring_radius * ring_radius - radius * radius) / (2.0 * distance * ring_radius)
        angle = math.degrees(math.acos(clamp(cos_angle, -1.0, 1.0)))
        if best is None or angle > best:
            best = angle
    return best


def integrate_bin_danger(gf_low: float, gf_high: float, bin_dangers: list[float]) -> float:
    """Sum the bin dangers weighted by how much of each bin the guess-factor span covers."""
    bin_count = len(bin_dangers)
    if bin_count <= 1:
        return bin_dangers[0] if bin_dangers else 0.0
    half_width = 1.0 / (bin_count - 1)
    total = 0.0
    for index, danger in enumerate(bin_dangers):
        center = -1.0 + 2.0 * index / (bin_count - 1)
        low = max(gf_low, center - half_width)
        high = min(gf_high, center + half_width)
        if high <= low:
            continue
        total += danger * (high - low) / (2.0 * half_width)
    return total


def head_on_prior_danger(gf_low: float, gf_high: float, weight: float, width: float) -> float:
    """A Gaussian bump at guess factor 0 integrated over the span (most guns fire head-on)."""
    if weight <= 0 or width <= 0:
        return 0.0
    scale = 1.0 / (width * math.sqrt(2.0))
    integral = 0.5 * (math.erf(gf_high * scale) - math.erf(gf_low * scale))
    return weight * integral


def ring_inner(wave: MovementWave, turn: int) -> float:
    """Bullet distance at the start of the turn that produced the state at ``turn``."""
    return wave.bullet_speed * max(0, turn - 1 - wave.fired_turn)


def ring_outer(wave: MovementWave, turn: int) -> float:
    """Bullet distance at ``turn`` (the server fires, moves bots, then advances bullets)."""
    return wave.bullet_speed * max(0, turn - wave.fired_turn)


def is_breaking(wave: MovementWave, state: RobotMovementState, radius: float) -> bool:
    distance = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
    return ring_outer(wave, state.turn) >= distance - radius and ring_inner(wave, state.turn) <= distance + radius


def wave_passed(wave: MovementWave, state: RobotMovementState) -> bool:
    distance = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
    return ring_outer(wave, state.turn) >= distance


def wave_gone(wave: MovementWave, state: RobotMovementState, radius: float) -> bool:
    distance = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
    return ring_inner(wave, state.turn) > distance + radius


def time_to_impact(wave: MovementWave, distance_now: float, turn_number: int) -> float:
    radius_now = wave.bullet_speed * max(0, turn_number - wave.fired_turn)
    return (distance_now - radius_now) / max(0.1, wave.bullet_speed)


def guess_factor_span(wave: MovementWave, break_states: list[RobotMovementState], radius: float) -> tuple[float, float]:
    """The guess-factor interval the bot's circle covers over the breaking turns."""
    offset_low: float | None = None
    offset_high: float | None = None
    for state in break_states:
        distance = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
        half_width = ring_coverage_half_width(distance, radius, ring_inner(wave, state.turn), ring_outer(wave, state.turn))
        if half_width is None:
            continue
        bearing = math.degrees(math.atan2(state.y - wave.source_y, state.x - wave.source_x))
        offset = ((bearing - wave.direct_bearing + 180.0) % 360.0) - 180.0
        low = offset - half_width
        high = offset + half_width
        offset_low = low if offset_low is None else min(offset_low, low)
        offset_high = high if offset_high is None else max(offset_high, high)
    if offset_low is None or offset_high is None:
        return 0.0, 0.0
    gf_a = guess_factor_from_offset(offset_low, wave.lateral_direction, wave.max_escape_angle_positive, wave.max_escape_angle_negative)
    gf_b = guess_factor_from_offset(offset_high, wave.lateral_direction, wave.max_escape_angle_positive, wave.max_escape_angle_negative)
    return min(gf_a, gf_b), max(gf_a, gf_b)


class OptionSurfer:
    def __init__(self, config: MovementFlatteningConfig) -> None:
        self.config = config

    def choose(
        self,
        bot,
        target,
        waves: list[MovementWave],
        bin_dangers: dict[int, list[float]],
        max_speed: float,
        field_margin: float,
        preferred_distance: float,
        last_direction: int,
        current_option: int | None = None,
    ) -> OptionSurfDecision | None:
        if not waves:
            return None
        first_wave = waves[0]
        start = RobotMovementState(x=bot.x, y=bot.y, direction=bot.direction, speed=bot.speed, turn=bot.turn_number)
        arena = (bot.arena_width, bot.arena_height)
        previous_direction = CLOCKWISE if last_direction >= 0 else COUNTER_CLOCKWISE
        speed = min(MAX_ROBOT_SPEED, abs(max_speed))

        results: dict[int, OptionResult] = {}
        best_total = math.inf
        for option in OPTIONS:
            result = self.evaluate_option(
                bot,
                target,
                waves,
                0,
                start,
                option,
                previous_direction,
                bin_dangers,
                speed,
                field_margin,
                preferred_distance,
                arena,
                (),
                best_total,
            )
            results[option] = result
            best_total = min(best_total, result.danger)

        totals = {option: results[option].danger for option in OPTIONS}
        if current_option in totals and self.config.option_surf_hysteresis > 0:
            # Keep the current option unless another one is clearly safer, to avoid flip-flopping.
            totals[current_option] *= 1.0 - self.config.option_surf_hysteresis
        if totals[STOP] <= totals[COUNTER_CLOCKWISE] and totals[STOP] <= totals[CLOCKWISE]:
            chosen = STOP
        elif totals[CLOCKWISE] < totals[COUNTER_CLOCKWISE]:
            chosen = CLOCKWISE
        else:
            chosen = COUNTER_CLOCKWISE

        if chosen == STOP:
            move_bearing = bot.direction
            command_speed = 0.0
            direction = last_direction
        else:
            move_bearing = self.move_bearing(bot.x, bot.y, target, first_wave, chosen, field_margin, preferred_distance, arena)
            command_speed = speed
            direction = chosen

        result = results[chosen]
        distance_now = math.hypot(bot.x - first_wave.source_x, bot.y - first_wave.source_y)
        return OptionSurfDecision(
            option=chosen,
            move_bearing=move_bearing,
            speed=command_speed,
            danger=totals[chosen],
            danger_ccw=totals[COUNTER_CLOCKWISE],
            danger_stop=totals[STOP],
            danger_cw=totals[CLOCKWISE],
            waves=len(waves),
            wave_kind=first_wave.kind,
            hit_turn=result.hit_turn,
            gf_low=result.gf_low,
            gf_high=result.gf_high,
            time_to_impact=time_to_impact(first_wave, distance_now, bot.turn_number),
            direction=direction,
        )

    # Evaluation ------------------------------------------------------------------
    def evaluate_option(
        self,
        bot,
        target,
        waves: list[MovementWave],
        wave_index: int,
        start: RobotMovementState,
        option: int,
        previous_direction: int,
        bin_dangers: dict[int, list[float]],
        speed: float,
        field_margin: float,
        preferred_distance: float,
        arena: tuple[float, float],
        replay: tuple[RobotMovementState, ...],
        cutoff_danger: float,
    ) -> OptionResult:
        wave = waves[wave_index]
        config = self.config
        radius = config.option_surf_bot_radius
        smoothing_direction = option if option != STOP else previous_direction

        break_states: list[RobotMovementState] = [state for state in replay if is_breaking(wave, state, radius)]
        if is_breaking(wave, start, radius):
            break_states.append(start)
        path: list[RobotMovementState] = []
        state = start
        hit_turn = 0
        passed_state: RobotMovementState | None = None
        for _ in range(config.surf_max_ticks):
            if wave_passed(wave, state):
                passed_state = state
                break
            path.append(state)
            state = self._step(state, target, wave, option, smoothing_direction, speed, field_margin, preferred_distance, arena)
            if is_breaking(wave, state, radius):
                if hit_turn == 0:
                    hit_turn = state.turn - start.turn
                break_states.append(state)
        if passed_state is None:
            passed_state = state

        # The ring keeps overlapping the bot for a few turns after its front passes the centre.
        tail = passed_state
        for _ in range(RING_TAIL_TICKS):
            if wave_gone(wave, tail, radius):
                break
            tail = self._step(tail, target, wave, option, smoothing_direction, speed, field_margin, preferred_distance, arena)
            if is_breaking(wave, tail, radius):
                break_states.append(tail)

        gf_low, gf_high = guess_factor_span(wave, break_states, radius)
        dangers = bin_dangers.get(id(wave), [])
        danger = integrate_bin_danger(gf_low, gf_high, dangers)
        danger += head_on_prior_danger(gf_low, gf_high, config.option_surf_head_on_prior, config.option_surf_head_on_prior_width)
        danger *= bullet_damage_for_power((20.0 - wave.bullet_speed) / 3.0)
        if config.option_surf_time_to_impact_weighting:
            distance_now = math.hypot(bot.x - wave.source_x, bot.y - wave.source_y)
            danger /= max(1.0, time_to_impact(wave, distance_now, bot.turn_number))
        danger *= self._distancing_factor(start, passed_state, target)

        if wave_index + 1 < len(waves) and danger < cutoff_danger:
            best_next = math.inf
            for next_option in OPTIONS:
                next_result = self.evaluate_option(
                    bot,
                    target,
                    waves,
                    wave_index + 1,
                    passed_state,
                    next_option,
                    smoothing_direction,
                    bin_dangers,
                    speed,
                    field_margin,
                    preferred_distance,
                    arena,
                    tuple(path),
                    min(cutoff_danger - danger, best_next),
                )
                best_next = min(best_next, next_result.danger)
            danger += best_next
        return OptionResult(danger=danger, passed_state=passed_state, path=tuple(path), hit_turn=hit_turn, gf_low=gf_low, gf_high=gf_high)

    def _step(
        self,
        state: RobotMovementState,
        target,
        wave: MovementWave,
        option: int,
        smoothing_direction: int,
        speed: float,
        field_margin: float,
        preferred_distance: float,
        arena: tuple[float, float],
    ) -> RobotMovementState:
        if option == STOP:
            return predict_robot_movement(
                state,
                state.direction,
                max_speed=0.0,
                field_margin=field_margin,
                arena_width=arena[0],
                arena_height=arena[1],
            )
        move_bearing = self.move_bearing(state.x, state.y, target, wave, option, field_margin, preferred_distance, arena)
        return predict_robot_movement(
            state,
            move_bearing,
            max_speed=speed,
            field_margin=field_margin,
            arena_width=arena[0],
            arena_height=arena[1],
        )

    def move_bearing(
        self,
        x: float,
        y: float,
        target,
        wave: MovementWave,
        direction: int,
        field_margin: float,
        preferred_distance: float,
        arena: tuple[float, float],
    ) -> float:
        config = self.config
        distance_to_target = math.hypot(x - target.x, y - target.y)
        lean = attack_angle(
            distance_to_target,
            preferred_distance,
            config.option_surf_attack_multiplier,
            config.option_surf_max_attack_angle,
        )
        bearing = orbit_bearing(x, y, wave.source_x, wave.source_y, direction, lean)
        return wall_smoothed_bearing(
            x,
            y,
            bearing,
            direction,
            field_margin,
            arena[0],
            arena[1],
            config.wall_stick,
            config.wall_smoothing_degrees,
            config.wall_smoothing_attempts,
        )

    def _distancing_factor(self, start: RobotMovementState, passed: RobotMovementState, target) -> float:
        base = self.config.option_surf_distancing_base
        if base <= 1.0:
            return 1.0
        distance_now = math.hypot(target.x - start.x, target.y - start.y)
        distance_then = max(1.0, math.hypot(target.x - passed.x, target.y - passed.y))
        quotient = clamp(distance_now / distance_then, 0.0, 4.0)
        return math.pow(base, quotient) / base

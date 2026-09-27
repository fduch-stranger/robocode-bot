"""Advisor inputs and outcomes: enemy movement statistics and per-wave surf records."""
from __future__ import annotations

import math
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from bot_core.advisors.state_summary import StyleFeatures, SurfFeatures
from bot_core.geometry.angles import absolute_bearing_between, relative_bearing
from bot_core.physics.rules import max_escape_angle_for_bullet_speed

WALL_MARGIN = 50.0
REVERSAL_MIN_LATERAL_SPEED = 1.0
WAVE_PASS_WINDOW_TURNS = 2
MIN_REVERSALS_FOR_LIFT = 5
MAX_TURN_RATE = 10.0
OUTCOME_STOP_GUESS_FACTOR = 0.3


class EnemyStyleObserver:
    """Battle-level movement statistics of one enemy, reduced to ``StyleFeatures``."""

    def __init__(self) -> None:
        self.samples = 0
        self._speed_sum = 0.0
        self._lateral_sum = 0.0
        self._turn_rate_sum = 0.0
        self._turn_rate_samples = 0
        self._wall_samples = 0
        self._reversals = 0
        self._reversals_near_pass = 0
        self._samples_near_pass = 0
        self._collisions = 0
        self._rounds: set[int] = set()
        # Per-round sums for pooled within-round distance spread and trend: n, t, d, t*d, t*t, d*d.
        self._round_sums: dict[int, list[float]] = {}
        self._round: int | None = None
        self._last_turn: int | None = None
        self._last_direction: float | None = None
        self._lateral_sign = 0
        self._pass_turns: deque[int] = deque(maxlen=32)

    def observe_scan(
        self,
        round_number: int,
        turn: int,
        own_x: float,
        own_y: float,
        enemy_x: float,
        enemy_y: float,
        enemy_direction: float,
        enemy_speed: float,
        arena_width: float,
        arena_height: float,
    ) -> None:
        if round_number != self._round:
            self._round = round_number
            self._rounds.add(round_number)
            self._last_turn = None
            self._last_direction = None
            self._lateral_sign = 0
            self._pass_turns.clear()
        bearing = absolute_bearing_between(own_x, own_y, enemy_x, enemy_y)
        lateral = enemy_speed * math.sin(math.radians(enemy_direction - bearing))
        distance = math.hypot(enemy_x - own_x, enemy_y - own_y)
        near_pass = self._near_pass(turn)

        self.samples += 1
        self._speed_sum += abs(enemy_speed)
        self._lateral_sum += abs(lateral)
        if near_pass:
            self._samples_near_pass += 1
        if (
            enemy_x < WALL_MARGIN
            or enemy_y < WALL_MARGIN
            or enemy_x > arena_width - WALL_MARGIN
            or enemy_y > arena_height - WALL_MARGIN
        ):
            self._wall_samples += 1
        if self._last_turn is not None and self._last_direction is not None and 0 < turn - self._last_turn <= 2:
            change = abs(relative_bearing(enemy_direction, self._last_direction)) / (turn - self._last_turn)
            self._turn_rate_sum += min(MAX_TURN_RATE, change)
            self._turn_rate_samples += 1
        if abs(lateral) >= REVERSAL_MIN_LATERAL_SPEED:
            sign = 1 if lateral > 0 else -1
            if self._lateral_sign and sign != self._lateral_sign:
                self._reversals += 1
                if near_pass:
                    self._reversals_near_pass += 1
            self._lateral_sign = sign
        sums = self._round_sums.setdefault(round_number, [0.0] * 6)
        sums[0] += 1.0
        sums[1] += turn
        sums[2] += distance
        sums[3] += turn * distance
        sums[4] += turn * turn
        sums[5] += distance * distance
        self._last_turn = turn
        self._last_direction = enemy_direction

    def observe_our_shot(self, round_number: int, fire_turn: int, distance: float, bullet_speed: float) -> None:
        """Remember when one of our bullets' waves will pass the enemy."""
        if round_number != self._round or bullet_speed <= 0:
            return
        self._pass_turns.append(fire_turn + round(distance / bullet_speed))

    def observe_collision(self) -> None:
        self._collisions += 1

    def features(self, linear_aim_hit_rate: float | None = None) -> StyleFeatures:
        samples = max(1, self.samples)
        near_share = self._samples_near_pass / samples
        lift = None
        if self._reversals >= MIN_REVERSALS_FOR_LIFT and near_share > 0:
            lift = (self._reversals_near_pass / self._reversals) / near_share
        spread, trend = self._pooled_distance_stats()
        return StyleFeatures(
            observed_turns=self.samples,
            mean_speed=self._speed_sum / samples,
            mean_lateral_speed=self._lateral_sum / samples,
            reversals_per_100_turns=100.0 * self._reversals / samples,
            reversal_shot_lift=lift,
            mean_distance=sum(sums[2] for sums in self._round_sums.values()) / samples,
            distance_spread=spread,
            distance_trend_per_100_turns=100.0 * trend,
            mean_turn_rate=self._turn_rate_sum / self._turn_rate_samples if self._turn_rate_samples else 0.0,
            rams_per_round=self._collisions / max(1, len(self._rounds)),
            wall_time_share=self._wall_samples / samples,
            linear_aim_hit_rate=linear_aim_hit_rate,
        )

    def _near_pass(self, turn: int) -> bool:
        return any(abs(turn - pass_turn) <= WAVE_PASS_WINDOW_TURNS for pass_turn in self._pass_turns)

    def _pooled_distance_stats(self) -> tuple[float, float]:
        n_total = 0.0
        squares = 0.0
        covariance = 0.0
        variance = 0.0
        for n, t, d, td, tt, dd in self._round_sums.values():
            if n < 2:
                continue
            n_total += n
            squares += dd - d * d / n
            covariance += td - t * d / n
            variance += tt - t * t / n
        spread = math.sqrt(max(0.0, squares / n_total)) if n_total else 0.0
        trend = covariance / variance if variance > 0 else 0.0
        return spread, trend


def wave_surf_features(
    own_x: float,
    own_y: float,
    own_direction: float,
    own_speed: float,
    source_x: float,
    source_y: float,
    bullet_speed: float,
    max_escape_angle_positive: float,
    max_escape_angle_negative: float,
    recent_hit_guess_factors: tuple[float, ...],
) -> SurfFeatures:
    distance = math.hypot(own_x - source_x, own_y - source_y)
    bearing = absolute_bearing_between(source_x, source_y, own_x, own_y)
    lateral = own_speed * math.sin(math.radians(own_direction - bearing))
    open_field = max(1e-9, max_escape_angle_for_bullet_speed(bullet_speed))
    return SurfFeatures(
        distance=distance,
        bullet_power=(20.0 - bullet_speed) / 3.0,
        flight_turns=distance / max(0.1, bullet_speed),
        own_speed=abs(own_speed),
        own_lateral_share=abs(lateral) / abs(own_speed) if abs(own_speed) > 1e-9 else 0.0,
        room_forward=min(1.0, abs(max_escape_angle_positive) / open_field),
        room_reverse=min(1.0, abs(max_escape_angle_negative) / open_field),
        recent_hit_guess_factors=recent_hit_guess_factors,
    )


def outcome_option(guess_factor: float) -> str:
    """Surf option that matches where we were when the wave passed us."""
    if guess_factor >= OUTCOME_STOP_GUESS_FACTOR:
        return "forward"
    if guess_factor <= -OUTCOME_STOP_GUESS_FACTOR:
        return "reverse"
    return "stop"


@dataclass
class SurfRecord:
    key: str
    request_turn: int
    answer: str | None = None
    confidence: float | None = None
    answer_turn: int | None = None
    visit_turn: int | None = None
    guess_factor: float | None = None
    hit: bool | None = None
    context: dict[str, object] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.answer_turn is not None and self.visit_turn is not None


class SurfObserver:
    """Recent enemy hit guess factors plus the asked waves waiting for an answer and a visit."""

    def __init__(self, max_recent_hits: int = 12, max_records: int = 256) -> None:
        self._recent_hits: deque[float] = deque(maxlen=max_recent_hits)
        self._records: OrderedDict[str, SurfRecord] = OrderedDict()
        self._max_records = max_records

    @property
    def recent_hit_guess_factors(self) -> tuple[float, ...]:
        return tuple(self._recent_hits)

    def track(self, record: SurfRecord) -> None:
        self._records[record.key] = record
        while len(self._records) > self._max_records:
            self._records.popitem(last=False)

    def record_answer(self, key: str, answer: str | None, confidence: float | None, turn: int) -> SurfRecord | None:
        record = self._records.get(key)
        if record is None:
            return None
        record.answer = answer
        record.confidence = confidence
        record.answer_turn = turn
        return self._pop_if_complete(record)

    def record_visit(self, key: str, turn: int, guess_factor: float, hit: bool) -> SurfRecord | None:
        if hit:
            self._recent_hits.appendleft(guess_factor)
        record = self._records.get(key)
        if record is None or record.visit_turn is not None:
            return None
        record.visit_turn = turn
        record.guess_factor = guess_factor
        record.hit = hit
        return self._pop_if_complete(record)

    def forget(self, key: str) -> None:
        self._records.pop(key, None)

    def _pop_if_complete(self, record: SurfRecord) -> SurfRecord | None:
        if not record.complete:
            return None
        self._records.pop(record.key, None)
        return record

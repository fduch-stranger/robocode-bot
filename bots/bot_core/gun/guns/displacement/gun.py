import math
from dataclasses import dataclass

from bot_core.geometry.angles import absolute_bearing_between, relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, TargetHistoryStore
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.gun.models import TargetPosition
from bot_core.physics import bullet_speed_for_power


_DENSITY_WINDOW_DEGREES = 8.0


@dataclass(frozen=True)
class _ReplayBearing:
    bearing: float
    offset: float
    candidate_score: float
    candidate_weight: float


@dataclass(frozen=True)
class _DensitySelection:
    bearing: float
    candidate_score: float
    peak_density: float
    peak_share: float
    bearing_spread: float


class DisplacementGun:
    mode = "displacement"

    def __init__(self, config: DisplacementGunConfig, history: TargetHistoryStore) -> None:
        self.config = config
        self.history = history
        self.mode_policy = config.mode_policy()

    def aim(self, context: AimContext) -> GunBearing | None:
        result = self._aim_bearing_and_diagnostics(
            context,
            context.distance,
            context.firepower,
            context.field_margin,
        )
        if result is None:
            return None
        bearing, diagnostics = result
        context_data = {
            "context_tags": self._context_tags(context),
            "flight_time": context.fire_context.bullet_flight_time,
            **diagnostics,
        }
        return GunBearing(
            self.mode,
            bearing,
            decision_context=GunDecisionContext(
                self.mode,
                context_data,
            ),
            metadata={
                self.mode: {
                    **context_data,
                    "wall_escape_balance": context.fire_context.wall_escape_balance,
                }
            },
        )

    def aim_bearing(
        self,
        context: AimContext,
        distance: float,
        firepower: float,
        field_margin: float,
    ) -> float | None:
        result = self._aim_bearing_and_diagnostics(context, distance, firepower, field_margin)
        return result[0] if result is not None else None

    def _aim_bearing_and_diagnostics(
        self,
        context: AimContext,
        distance: float,
        firepower: float,
        field_margin: float,
    ) -> tuple[float, dict[str, object]] | None:
        history = self.history.history_for(context.target.bot_id)
        if len(history) < self.config.min_samples + 1:
            return None

        bullet_speed = bullet_speed_for_power(firepower)
        head_on_bearing = absolute_bearing_between(
            context.bot.x,
            context.bot.y,
            context.target.x,
            context.target.y,
        )
        current_lateral, current_advancing = self._velocity_components(
            TargetPosition(
                context.target.seen_turn,
                context.target.x,
                context.target.y,
                context.target.speed,
                context.target.direction,
            ),
            math.radians(head_on_bearing),
        )
        current = TargetPosition(
            context.target.seen_turn,
            context.target.x,
            context.target.y,
            context.target.speed,
            context.target.direction,
            observed_lateral_speed=current_lateral,
            observed_advancing_speed=current_advancing,
            observed_wall_margin=context.fire_context.wall_margin,
            observed_distance=distance,
        )
        candidates = self._ranked_candidates(context, current, history)
        replay_limit = max(self.config.min_samples * 4, 12)
        replay_bearings: list[_ReplayBearing] = []
        for ranked in candidates:
            _rank_score, index, candidate_score, candidate_weight = ranked
            endpoint = self._replay_from_candidate(
                context,
                history,
                index,
                bullet_speed,
                field_margin,
            )
            if endpoint is None:
                continue
            bearing = absolute_bearing_between(
                context.bot.x,
                context.bot.y,
                endpoint[0],
                endpoint[1],
            )
            replay_bearings.append(
                _ReplayBearing(
                    bearing=bearing,
                    offset=relative_bearing(bearing, head_on_bearing),
                    candidate_score=candidate_score,
                    candidate_weight=candidate_weight,
                )
            )
            if len(replay_bearings) >= replay_limit:
                break

        if len(replay_bearings) < self.config.min_samples:
            return None

        selection = self._density_best_bearing(head_on_bearing, replay_bearings)
        diagnostics = self._diagnostics(context, replay_bearings, selection)
        return selection.bearing, diagnostics

    def _ranked_candidates(
        self,
        context: AimContext,
        current: TargetPosition,
        history: list[TargetPosition],
    ) -> list[tuple[float, int, float, float]]:
        ranked: list[tuple[float, int, float, float]] = []
        for index, _past in enumerate(history[:-1]):
            if index + 1 >= len(history):
                continue
            candidate_score = self._candidate_score_for_index(context, current, history, index)
            candidate_weight = 1.0 / (1.0 + max(candidate_score, 0.0))
            ranked.append((candidate_score, index, candidate_score, candidate_weight))
        return sorted(ranked, key=lambda candidate: candidate[0])

    def _candidate_score_for_index(
        self,
        context: AimContext,
        current: TargetPosition,
        history: list[TargetPosition],
        index: int,
    ) -> float:
        past = history[index]
        score = self._candidate_score(context, current, past)
        score += self._heading_change_distance(history, index) * 0.55
        return max(0.0, score)

    def _candidate_score(self, context: AimContext, current: TargetPosition, past: TargetPosition) -> float:
        past_lateral, past_advancing = self._candidate_velocity_components(context, past)
        _, _, _, current_advancing, _, _, current_wall_margin = context.features
        past_wall_margin = self._candidate_wall_margin(context, past)
        return (
            abs(relative_bearing(past.direction, current.direction)) / 180.0 * 0.25
            + abs(past.speed - current.speed) / 16.0
            + abs(past_lateral - context.fire_context.lateral_speed_signed) / 16.0 * 1.2
            + abs((past_advancing / 8.0) - current_advancing) * 0.8
            + abs(past_wall_margin - current_wall_margin) * 0.7
        )

    def _heading_change_distance(self, history: list[TargetPosition], index: int) -> float:
        current_change = self._heading_change_at(history, len(history) - 1)
        past_change = self._heading_change_at(history, index)
        return abs(current_change - past_change) / 30.0

    @staticmethod
    def _heading_change_at(history: list[TargetPosition], index: int) -> float:
        if index <= 0 or index >= len(history):
            return 0.0
        previous = history[index - 1]
        current = history[index]
        tick_delta = max(1, current.turn - previous.turn)
        return relative_bearing(current.direction, previous.direction) / tick_delta

    def _density_best_bearing(self, head_on_bearing: float, replays: list[_ReplayBearing]) -> _DensitySelection:
        densities: list[float] = []
        for replay in replays:
            density = 0.0
            for neighbor in replays:
                distance = abs(relative_bearing(neighbor.offset, replay.offset))
                if distance > _DENSITY_WINDOW_DEGREES:
                    continue
                density += neighbor.candidate_weight * (1.0 - distance / (_DENSITY_WINDOW_DEGREES * 1.15))
            densities.append(density)

        best_index = max(range(len(replays)), key=lambda index: densities[index])
        peak = replays[best_index]
        centroid_weight = 0.0
        centroid_offset = 0.0
        for replay in replays:
            distance = abs(relative_bearing(replay.offset, peak.offset))
            if distance > _DENSITY_WINDOW_DEGREES:
                continue
            weight = replay.candidate_weight * (1.0 - distance / (_DENSITY_WINDOW_DEGREES * 1.15))
            centroid_offset += replay.offset * weight
            centroid_weight += weight
        selected_offset = centroid_offset / centroid_weight if centroid_weight > 0.0 else peak.offset
        total_weight = sum(replay.candidate_weight for replay in replays)
        return _DensitySelection(
            bearing=head_on_bearing + selected_offset,
            candidate_score=peak.candidate_score,
            peak_density=densities[best_index],
            peak_share=densities[best_index] / total_weight if total_weight > 0.0 else 0.0,
            bearing_spread=self._bearing_spread(replays),
        )

    @staticmethod
    def _bearing_spread(replays: list[_ReplayBearing]) -> float:
        offsets = sorted(replay.offset for replay in replays)
        if len(offsets) < 2:
            return 0.0
        middle = len(offsets) // 2
        median = offsets[middle] if len(offsets) % 2 else (offsets[middle - 1] + offsets[middle]) / 2.0
        return sum(abs(relative_bearing(offset, median)) for offset in offsets) / len(offsets)

    def _diagnostics(
        self,
        context: AimContext,
        replays: list[_ReplayBearing],
        selection: _DensitySelection,
    ) -> dict[str, object]:
        return {
            "displacement_replay_count": len(replays),
            "displacement_candidate_score": selection.candidate_score,
            "displacement_peak_density": selection.peak_density,
            "displacement_peak_share": selection.peak_share,
            "displacement_bearing_spread": selection.bearing_spread,
            "displacement_distance_bucket": context.fire_context.distance_bucket,
        }

    def _replay_from_candidate(
        self,
        context: AimContext,
        history: list[TargetPosition],
        start_index: int,
        bullet_speed: float,
        field_margin: float,
    ) -> tuple[float, float] | None:
        start = history[start_index]
        replay_x = context.target.x
        replay_y = context.target.y
        arena_width = float(context.bot.arena_width)
        arena_height = float(context.bot.arena_height)
        elapsed_ticks = 0.0
        for index in range(start_index, len(history) - 1):
            previous = history[index]
            next_position = history[index + 1]
            tick_delta = next_position.turn - previous.turn
            if tick_delta <= 0:
                continue
            step_x, step_y = self._rotated_step(
                start,
                previous,
                next_position,
                context.target.direction,
            )
            next_x = clamp(replay_x + step_x, field_margin, arena_width - field_margin)
            next_y = clamp(replay_y + step_y, field_margin, arena_height - field_margin)
            next_elapsed = elapsed_ticks + tick_delta
            if next_elapsed * bullet_speed >= math.hypot(
                next_x - context.bot.x,
                next_y - context.bot.y,
            ):
                return self._intersect_segment(
                    context,
                    replay_x,
                    replay_y,
                    elapsed_ticks,
                    next_x,
                    next_y,
                    next_elapsed,
                    bullet_speed,
                )
            replay_x = next_x
            replay_y = next_y
            elapsed_ticks = next_elapsed
        return None

    @staticmethod
    def _rotated_step(
        start: TargetPosition,
        previous: TargetPosition,
        next_position: TargetPosition,
        current_direction: float,
    ) -> tuple[float, float]:
        dx = next_position.x - previous.x
        dy = next_position.y - previous.y
        previous_heading = math.radians(previous.direction)
        forward = dx * math.cos(previous_heading) + dy * math.sin(previous_heading)
        left = dx * -math.sin(previous_heading) + dy * math.cos(previous_heading)
        replay_heading = math.radians(
            current_direction + relative_bearing(previous.direction, start.direction)
        )
        replay_dx = forward * math.cos(replay_heading) - left * math.sin(replay_heading)
        replay_dy = forward * math.sin(replay_heading) + left * math.cos(replay_heading)
        return replay_dx, replay_dy

    @staticmethod
    def _intersect_segment(
        context: AimContext,
        start_x: float,
        start_y: float,
        start_elapsed: float,
        end_x: float,
        end_y: float,
        end_elapsed: float,
        bullet_speed: float,
    ) -> tuple[float, float]:
        low = 0.0
        high = 1.0
        for _ in range(12):
            mid = (low + high) / 2.0
            x = start_x + (end_x - start_x) * mid
            y = start_y + (end_y - start_y) * mid
            elapsed = start_elapsed + (end_elapsed - start_elapsed) * mid
            if elapsed * bullet_speed >= math.hypot(
                x - context.bot.x,
                y - context.bot.y,
            ):
                high = mid
            else:
                low = mid
        ratio = high
        return (
            start_x + (end_x - start_x) * ratio,
            start_y + (end_y - start_y) * ratio,
        )

    @staticmethod
    def _velocity_components(position: TargetPosition, absolute_bearing: float) -> tuple[float, float]:
        heading = math.radians(position.direction)
        velocity_x = math.cos(heading) * position.speed
        velocity_y = math.sin(heading) * position.speed
        lateral_velocity = velocity_x * -math.sin(absolute_bearing) + velocity_y * math.cos(absolute_bearing)
        advancing_velocity = velocity_x * math.cos(absolute_bearing) + velocity_y * math.sin(absolute_bearing)
        return lateral_velocity, advancing_velocity

    @staticmethod
    def _candidate_velocity_components(context: AimContext, position: TargetPosition) -> tuple[float, float]:
        if position.observed_lateral_speed is not None and position.observed_advancing_speed is not None:
            return position.observed_lateral_speed, position.observed_advancing_speed
        approximate_bearing = math.radians(absolute_bearing_between(context.bot.x, context.bot.y, position.x, position.y))
        return DisplacementGun._velocity_components(position, approximate_bearing)

    @staticmethod
    def _candidate_wall_margin(context: AimContext, position: TargetPosition) -> float:
        if position.observed_wall_margin is not None:
            return position.observed_wall_margin
        arena_width = float(context.bot.arena_width)
        arena_height = float(context.bot.arena_height)
        arena_scale = max(arena_width, arena_height)
        return (
            min(
                position.x,
                arena_width - position.x,
                position.y,
                arena_height - position.y,
            )
            / arena_scale
        )

    def observe_visit(self, visit: GunVisit) -> None:
        return None

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        metadata = visit.wave.gun_metadata.get(self.mode)
        if isinstance(metadata, dict):
            return dict(metadata)
        context = visit.wave.fire_context
        return {
            "context_tags": self._context_tags_from_tags(context.movement_tags),
            "flight_time": context.bullet_flight_time,
            "wall_escape_balance": context.wall_escape_balance,
        }

    @staticmethod
    def _context_tags(context: AimContext) -> frozenset[str]:
        return DisplacementGun._context_tags_from_tags(context.movement_tags)

    @staticmethod
    def _context_tags_from_tags(tags: frozenset[str]) -> frozenset[str]:
        return tags.intersection({"stable_pattern", "nonlinear_mover", "adaptive_mover", "surfer"})

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        return {}

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None

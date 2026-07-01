import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_core.tank_math import TargetSnapshot


@dataclass(frozen=True)
class MinimumRiskConfig:
    candidate_distances: tuple[float, ...] = (95.0, 145.0, 205.0)
    candidate_angle_step: int = 22
    field_margin: float = 58.0
    preferred_target_distance: float = 290.0
    max_target_distance: float = 520.0
    close_enemy_distance: float = 145.0
    travel_weight: float = 0.0018
    wall_weight: float = 95.0
    enemy_weight: float = 16500.0
    close_enemy_weight: float = 14.0
    target_distance_weight: float = 0.0009
    radial_weight: float = 0.35
    threat_lateral_weight: float = 0.0
    threat_distance_weight: float = 0.0
    recent_destination_weight: float = 2.4
    recent_destination_radius: float = 130.0
    recent_destination_count: int = 12
    destination_commit_ticks: int = 16
    destination_reached_radius: float = 42.0
    destination_switch_risk_ratio: float = 0.82


@dataclass(frozen=True)
class MinimumRiskDecision:
    x: float
    y: float
    risk: float
    candidates: int
    nearest_enemy_id: int | None
    nearest_enemy_distance: float
    reused: bool = False
    age: int = 0


class MinimumRiskMovement:
    def __init__(self, config: MinimumRiskConfig | None = None) -> None:
        self.config = config or MinimumRiskConfig()
        self._recent_destinations: list[tuple[float, float]] = []
        self._active_destination: tuple[float, float] | None = None
        self._active_selected_turn = 0

    def choose(
        self,
        bot: Bot,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        threat_target: TargetSnapshot | None = None,
        dodge_direction: int = 0,
    ) -> MinimumRiskDecision | None:
        if len(targets) < 2:
            self._active_destination = None
            return None

        candidates = self._candidate_points(bot)
        best: MinimumRiskDecision | None = None
        for x, y in candidates:
            risk, nearest_id, nearest_distance = self._risk(
                bot,
                x,
                y,
                targets,
                focus_target,
                threat_target,
                dodge_direction,
            )
            decision = MinimumRiskDecision(
                x=x,
                y=y,
                risk=risk,
                candidates=0,
                nearest_enemy_id=nearest_id,
                nearest_enemy_distance=nearest_distance,
            )
            if best is None or decision.risk < best.risk:
                best = decision

        if best is None:
            return None

        active = self._active_decision(
            bot,
            targets,
            focus_target,
            len(candidates),
            threat_target,
            dodge_direction,
        )
        if active is not None and best.risk >= active.risk * self.config.destination_switch_risk_ratio:
            return active

        selected = MinimumRiskDecision(
            x=best.x,
            y=best.y,
            risk=best.risk,
            candidates=len(candidates),
            nearest_enemy_id=best.nearest_enemy_id,
            nearest_enemy_distance=best.nearest_enemy_distance,
        )
        self._active_destination = (selected.x, selected.y)
        self._active_selected_turn = getattr(bot, "turn_number", 0)
        self._remember_destination(selected.x, selected.y)
        return selected

    def _active_decision(
        self,
        bot: Bot,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        candidate_count: int,
        threat_target: TargetSnapshot | None,
        dodge_direction: int,
    ) -> MinimumRiskDecision | None:
        if self._active_destination is None:
            return None

        x, y = self._active_destination
        if not self._in_field(bot, x, y):
            return None

        turn_number = getattr(bot, "turn_number", 0)
        age = turn_number - self._active_selected_turn
        if age > self.config.destination_commit_ticks:
            return None

        if math.hypot(x - bot.x, y - bot.y) <= self.config.destination_reached_radius:
            return None

        risk, nearest_id, nearest_distance = self._risk(
            bot,
            x,
            y,
            targets,
            focus_target,
            threat_target,
            dodge_direction,
        )
        return MinimumRiskDecision(
            x=x,
            y=y,
            risk=risk,
            candidates=candidate_count,
            nearest_enemy_id=nearest_id,
            nearest_enemy_distance=nearest_distance,
            reused=True,
            age=max(0, age),
        )

    def _remember_destination(self, x: float, y: float) -> None:
        self._recent_destinations.append((x, y))
        if len(self._recent_destinations) > self.config.recent_destination_count:
            del self._recent_destinations[: len(self._recent_destinations) - self.config.recent_destination_count]

    def clear_round_state(self) -> None:
        self._recent_destinations.clear()
        self._active_destination = None
        self._active_selected_turn = 0

    def _candidate_points(self, bot: Bot) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for distance in self.config.candidate_distances:
            for angle in range(0, 360, self.config.candidate_angle_step):
                x = bot.x + math.cos(math.radians(angle)) * distance
                y = bot.y + math.sin(math.radians(angle)) * distance
                if self._in_field(bot, x, y):
                    points.append((x, y))
        return points

    def _risk(
        self,
        bot: Bot,
        x: float,
        y: float,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        threat_target: TargetSnapshot | None,
        dodge_direction: int,
    ) -> tuple[float, int | None, float]:
        nearest_id: int | None = None
        nearest_distance = float("inf")
        risk = math.hypot(x - bot.x, y - bot.y) * self.config.travel_weight
        risk += self._wall_risk(bot, x, y)
        risk += self._target_distance_risk(x, y, focus_target)
        risk += self._recent_destination_risk(x, y)

        for target in targets:
            distance = max(1.0, math.hypot(x - target.x, y - target.y))
            if distance < nearest_distance:
                nearest_id = target.bot_id
                nearest_distance = distance

            energy_weight = 1.0 + target.energy / 100.0
            risk += self.config.enemy_weight * energy_weight / (distance * distance)
            if distance < self.config.close_enemy_distance:
                closeness = (self.config.close_enemy_distance - distance) / self.config.close_enemy_distance
                risk += closeness * closeness * self.config.close_enemy_weight * energy_weight

            current_bearing = math.atan2(bot.y - target.y, bot.x - target.x)
            candidate_bearing = math.atan2(y - target.y, x - target.x)
            lateral = abs(math.sin(candidate_bearing - current_bearing))
            risk += (1.0 - lateral) * self.config.radial_weight * energy_weight

            if threat_target is not None and target.bot_id == threat_target.bot_id:
                lateral_delta = math.sin(candidate_bearing - current_bearing)
                threat_lateral = abs(lateral_delta)
                risk += (1.0 - threat_lateral) * self.config.threat_lateral_weight * energy_weight
                risk += self.config.threat_distance_weight * energy_weight / (distance * distance)
                if dodge_direction and lateral_delta * dodge_direction < 0:
                    risk += self.config.threat_lateral_weight * 0.35 * energy_weight

        return risk, nearest_id, nearest_distance

    def _target_distance_risk(self, x: float, y: float, focus_target: TargetSnapshot) -> float:
        distance = math.hypot(x - focus_target.x, y - focus_target.y)
        if distance < self.config.preferred_target_distance:
            error = self.config.preferred_target_distance - distance
        elif distance > self.config.max_target_distance:
            error = distance - self.config.max_target_distance
        else:
            return 0.0
        return error * error * self.config.target_distance_weight

    def _wall_risk(self, bot: Bot, x: float, y: float) -> float:
        margin = min(x, bot.arena_width - x, y, bot.arena_height - y)
        if margin <= self.config.field_margin:
            return self.config.wall_weight
        return self.config.wall_weight / max(1.0, margin)

    def _recent_destination_risk(self, x: float, y: float) -> float:
        risk = 0.0
        for recent_x, recent_y in self._recent_destinations:
            distance = math.hypot(x - recent_x, y - recent_y)
            if distance < self.config.recent_destination_radius:
                closeness = (self.config.recent_destination_radius - distance) / self.config.recent_destination_radius
                risk += closeness * self.config.recent_destination_weight
        return risk

    def _in_field(self, bot: Bot, x: float, y: float) -> bool:
        margin = self.config.field_margin
        return margin <= x <= bot.arena_width - margin and margin <= y <= bot.arena_height - margin

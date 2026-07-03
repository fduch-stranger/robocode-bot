from bot_core.geometry.angles import absolute_bearing_between
from bot_core.geometry.numeric import clamp
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, TargetHistoryStore
from bot_core.gun.guns.displacement.config import DisplacementGunConfig
from bot_core.physics import bullet_speed_for_power


class DisplacementGun:
    mode = "displacement"

    def __init__(self, config: DisplacementGunConfig, history: TargetHistoryStore) -> None:
        self.config = config
        self.history = history
        self.mode_policy = config.mode_policy()

    def aim(self, context: AimContext) -> GunBearing | None:
        bearing = self.aim_bearing(
            context,
            context.distance,
            context.firepower,
            context.field_margin,
        )
        if bearing is None:
            return None
        return GunBearing(
            self.mode,
            bearing,
            decision_context=GunDecisionContext(
                self.mode,
                {
                    "context_tags": self._context_tags(context),
                    "flight_time": context.fire_context.bullet_flight_time,
                },
            ),
            metadata={
                self.mode: {
                    "context_tags": self._context_tags(context),
                    "flight_time": context.fire_context.bullet_flight_time,
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
        history = self.history.history_for(context.target.bot_id)
        if len(history) < self.config.min_samples + 1:
            return None

        travel_ticks = max(1, round(context.fire_context.bullet_flight_time or distance / bullet_speed_for_power(firepower)))
        current = history[-1]
        samples: list[tuple[float, float]] = []
        for past in history[:-1]:
            elapsed = current.turn - past.turn
            if abs(elapsed - travel_ticks) > self.config.time_tolerance:
                continue
            samples.append((current.x - past.x, current.y - past.y))

        if len(samples) < self.config.min_samples:
            return None

        average_dx = sum(dx for dx, _ in samples) / len(samples)
        average_dy = sum(dy for _, dy in samples) / len(samples)
        predicted_x = clamp(context.target.x + average_dx, field_margin, context.bot.arena_width - field_margin)
        predicted_y = clamp(context.target.y + average_dy, field_margin, context.bot.arena_height - field_margin)
        return absolute_bearing_between(context.bot.x, context.bot.y, predicted_x, predicted_y)

    def observe_visit(self, visit: GunVisit) -> None:
        return None

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
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

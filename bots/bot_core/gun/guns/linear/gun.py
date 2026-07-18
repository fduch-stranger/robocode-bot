from bot_core.geometry.angles import absolute_bearing_between
from bot_core.gun.config import GunDecisionContext, GunModePolicy, GunModeTraits
from bot_core.gun.context import AimContext, GunBearing, GunVisit
from bot_core.gun.prediction import predict_linear_details


LINEAR_MODE = "linear"


class LinearGun:
    def __init__(
        self,
        min_switch_visits: int = 90,
        min_switch_score: float = 0.30,
    ) -> None:
        self.mode = LINEAR_MODE
        self.mode_policy = GunModePolicy(
            self.mode,
            min_switch_visits,
            min_switch_score,
            GunModeTraits(
                role="fallback",
                family="linear_predictor",
                phases=frozenset({"early"}),
                strengths=frozenset({"low_lateral", "stable_velocity"}),
            ),
        )

    def aim(self, context: AimContext) -> GunBearing:
        prediction = predict_linear_details(
            context.bot,
            context.target,
            context.firepower,
            context.field_margin,
        )
        context_tags = self._context_tags(context)
        return GunBearing(
            self.mode,
            absolute_bearing_between(context.bot.x, context.bot.y, prediction.x, prediction.y),
            decision_context=GunDecisionContext(
                self.mode,
                {"context_tags": context_tags},
            ),
            metadata={
                self.mode: {
                    "context_tags": context_tags,
                    "short_flight_time": context.fire_context.bullet_flight_time <= 22.0,
                    "flight_time": context.fire_context.bullet_flight_time,
                    "lateral_confidence": context.fire_context.lateral_direction_confidence,
                }
            },
        )



    @staticmethod
    def _context_tags(context: AimContext) -> frozenset[str]:
        _, _, lateral_speed, _, acceleration, velocity_change_age, _ = context.features
        tags: set[str] = set(context.movement_tags.intersection({"low_lateral", "stable_velocity", "stable_pattern"}))
        if lateral_speed <= 0.18:
            tags.add("low_lateral")
        if abs(acceleration) <= 0.05 and velocity_change_age >= 0.45:
            tags.add("stable_velocity")
        if context.fire_context.bullet_flight_time <= 22.0:
            tags.add("short_flight_time")
        return frozenset(tags)

    def observe_visit(self, visit: GunVisit) -> None:
        return None

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        metadata = visit.wave.gun_metadata.get(self.mode)
        return dict(metadata) if isinstance(metadata, dict) else {}

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        return {}

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None

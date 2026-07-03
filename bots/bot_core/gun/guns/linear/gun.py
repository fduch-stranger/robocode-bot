from bot_core.geometry.angles import absolute_bearing_between
from bot_core.gun.config import GunModePolicy
from bot_core.gun.context import AimContext, GunBearing, GunVisit
from bot_core.gun.prediction import (
    LinearPrediction,
    predict_linear_details,
    predict_wall_aware_linear_details,
)


LINEAR_MODE = "linear"
LINEAR_WALL_AWARE_MODE = "linear_wall_aware"
LINEAR_VARIANT_MODES = frozenset({
    LINEAR_MODE,
    LINEAR_WALL_AWARE_MODE,
})


class LinearGun:
    def __init__(
        self,
        min_switch_visits: int = 90,
        min_switch_score: float = 0.30,
        *,
        mode: str = LINEAR_MODE,
    ) -> None:
        if mode not in LINEAR_VARIANT_MODES:
            raise ValueError(f"unknown linear gun mode: {mode}")
        self.mode = mode
        self.mode_policy = GunModePolicy(self.mode, min_switch_visits, min_switch_score)

    def aim(self, context: AimContext) -> GunBearing:
        prediction, metadata = self._predict_position(context)
        return GunBearing(
            self.mode,
            absolute_bearing_between(context.bot.x, context.bot.y, prediction.x, prediction.y),
            metadata=metadata,
        )

    def _predict_position(self, context: AimContext) -> tuple[LinearPrediction, dict[str, object]]:
        if self.mode == LINEAR_WALL_AWARE_MODE:
            prediction = predict_wall_aware_linear_details(
                context.bot,
                context.target,
                context.firepower,
                context.field_margin,
            )
            return prediction, {
                self.mode: {
                    "ticks": prediction.ticks,
                    "wall_hit": prediction.wall_hit,
                    "final_speed": prediction.final_speed,
                }
            }
        prediction = predict_linear_details(
            context.bot,
            context.target,
            context.firepower,
            context.field_margin,
        )
        return prediction, {}

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

from bot_core.geometry.angles import absolute_bearing_between
from bot_core.gun.config import GunModePolicy
from bot_core.gun.context import AimContext, GunBearing, GunVisit
from bot_core.gun.prediction import predicted_position


class LinearGun:
    mode = "linear"

    def __init__(self, min_switch_visits: int = 90, min_switch_score: float = 0.30) -> None:
        self.mode_policy = GunModePolicy(self.mode, min_switch_visits, min_switch_score)

    def aim(self, context: AimContext) -> GunBearing:
        predicted_x, predicted_y = predicted_position(
            context.bot,
            context.target,
            context.firepower,
            context.field_margin,
        )
        return GunBearing(
            self.mode,
            absolute_bearing_between(context.bot.x, context.bot.y, predicted_x, predicted_y),
        )

    def observe_visit(self, visit: GunVisit) -> None:
        return None

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        return {}

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        return {}

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None

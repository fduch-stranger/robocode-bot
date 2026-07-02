from typing import Protocol

from bot_core.gun.config import GunModePolicy
from bot_core.gun.context import AimContext, GunBearing, GunVisit


class GunComponent(Protocol):
    mode: str
    mode_policy: GunModePolicy

    def aim(self, context: AimContext) -> GunBearing | None:
        ...

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        ...

    def observe_visit(self, visit: GunVisit) -> None:
        ...

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        ...

    def clear_round_state(self) -> None:
        ...

    def remove_target(self, target_id: int) -> None:
        ...

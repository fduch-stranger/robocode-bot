from bot_core.gun.context import AimContext, GunBearing, GunVisit
from bot_core.gun.guns.base import GunComponent


class GunRegistry:
    def __init__(self, components: list[GunComponent]) -> None:
        self._components = {component.mode: component for component in components}

    @property
    def components(self) -> dict[str, GunComponent]:
        return self._components

    @property
    def mode_policies(self):
        return {mode: component.mode_policy for mode, component in self._components.items()}

    def bearings(self, context: AimContext) -> dict[str, GunBearing]:
        bearings: dict[str, GunBearing] = {}
        for component in self._components.values():
            bearing = component.aim(context)
            if bearing is not None:
                bearings[bearing.mode] = bearing
        return bearings

    def observe_visit(self, visit: GunVisit) -> None:
        if visit.is_evaluation:
            return
        for component in self._components.values():
            component.observe_visit(visit)

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, dict[str, object]]:
        diagnostics: dict[str, dict[str, object]] = {}
        for component in self._components.values():
            component_diagnostics = component.visit_diagnostics(visit)
            if component_diagnostics:
                diagnostics[component.mode] = component_diagnostics
        return diagnostics

    def metric(self, name: str, target_id: int | None = None, default: int | float = 0) -> int | float:
        for component in self._components.values():
            metrics = component.metrics(target_id)
            if name in metrics:
                return metrics[name]
        return default

    def clear_round_state(self) -> None:
        for component in self._components.values():
            component.clear_round_state()

    def remove_target(self, target_id: int) -> None:
        for component in self._components.values():
            component.remove_target(target_id)

"""Adaptive Jev: Adaptive Prime plus an optional asynchronous Jev advisor (experimental).

With ROBOCODE_JEV_ENABLED=0 (the default) this runs Adaptive Prime's own class under the Adaptive
Jev name, so every decision is Adaptive Prime's. See docs/plans/jev-advisor-bot.md.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from collections.abc import Callable
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
PRIME_DIR = BOT_DIR.parent / "adaptive-prime"
PRIME_MODULE_NAME = "adaptive_prime_for_jev"
if str(PRIME_DIR) not in sys.path:
    # adaptive-prime.py imports adaptive_config from its own directory.
    sys.path.append(str(PRIME_DIR))


def _load_adaptive_prime_module():
    module = sys.modules.get(PRIME_MODULE_NAME)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(PRIME_MODULE_NAME, PRIME_DIR / "adaptive-prime.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Adaptive Prime from {PRIME_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PRIME_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


AdaptivePrime = _load_adaptive_prime_module().AdaptivePrime

from robocode_tank_royale.bot_api import BotInfo  # noqa: E402
from robocode_tank_royale.bot_api.events import (  # noqa: E402
    BulletFiredEvent,
    GameEndedEvent,
    HitBotEvent,
    ScannedBotEvent,
)

from adaptive_config import MOVEMENT_FLATTENING_CONFIG  # noqa: E402
from bot_core.advisors.client import AdvisorClient  # noqa: E402
from bot_core.advisors.movement_hooks import ObservedMovementFlattener  # noqa: E402
from bot_core.telemetry.advisor import AdvisorTelemetry  # noqa: E402
from jev_advisor import LINEAR_AIM_MIN_VISITS, JevAdvisorLayer, build_transport  # noqa: E402
from jev_config import JevConfig, load_jev_config  # noqa: E402

TELEMETRY_NAME = "adaptive-jev"


def jev_bot_info() -> BotInfo:
    return BotInfo(
        name="Adaptive Jev",
        version="1.0",
        authors=["robocode-bot"],
        description="Adaptive Prime with an optional asynchronous Jev advisor (experimental).",
        game_types={"classic", "1v1", "melee"},
        programming_lang="Python 3",
    )


class AdaptiveJevPassthrough(AdaptivePrime):
    """Adaptive Prime itself under the Adaptive Jev name; used whenever the advisor is off."""

    def __init__(self, config: JevConfig | None = None, reason: str = "disabled") -> None:
        super().__init__(bot_info=jev_bot_info(), telemetry_name=TELEMETRY_NAME)
        AdvisorTelemetry(self._debug).record_config(
            advisor=False,
            reason=reason,
            **(config or JevConfig()).status_fields(),
        )


class AdaptiveJev(AdaptivePrime):
    """Adaptive Prime that also feeds the advisor layer; shadow mode leaves every decision unchanged."""

    def __init__(self, config: JevConfig, client: AdvisorClient) -> None:
        super().__init__(bot_info=jev_bot_info(), telemetry_name=TELEMETRY_NAME)
        telemetry = AdvisorTelemetry(self._debug)
        self._advisor = JevAdvisorLayer(self, config, client, telemetry, self._linear_aim_hit_rate)
        # Same configuration as Adaptive Prime's own flattener; the subclass only reports waves.
        self._movement = ObservedMovementFlattener(MOVEMENT_FLATTENING_CONFIG, self._advisor)
        telemetry.record_config(advisor=True, reason="enabled", transport=client.transport.name, **config.status_fields())

    def on_scanned_bot(self, event: ScannedBotEvent) -> None:
        super().on_scanned_bot(event)
        self._advisor.on_scan(event.scanned_bot_id, event.x, event.y, event.direction, event.speed)

    def on_bullet_fired(self, event: BulletFiredEvent) -> None:
        super().on_bullet_fired(event)
        target = self._targets.get(self._target_id) if self._target_id is not None else None
        if target is not None:
            distance = math.hypot(target.x - event.bullet.x, target.y - event.bullet.y)
            self._advisor.on_bullet_fired(target.bot_id, distance, event.bullet.speed)

    def on_hit_bot(self, event: HitBotEvent) -> None:
        super().on_hit_bot(event)
        self._advisor.on_collision(event.victim_id)

    def on_game_ended(self, event: GameEndedEvent) -> None:
        try:
            super().on_game_ended(event)
        finally:
            self._advisor.close()

    def go(self) -> None:
        self._advisor.on_turn_end()
        super().go()

    def _linear_aim_hit_rate(self, target_id: int) -> float | None:
        score, visits = self._gun.mode_confidence(target_id, "linear")
        return score if visits >= LINEAR_AIM_MIN_VISITS else None


def build_bot(
    config: JevConfig | None = None,
    transport_factory: Callable[[JevConfig], object | None] = build_transport,
) -> AdaptivePrime:
    """Adaptive Prime's own behavior unless the advisor is enabled and has a transport."""
    config = config or load_jev_config()
    if not config.enabled:
        return AdaptiveJevPassthrough(config)
    transport = transport_factory(config)
    if transport is None:
        return AdaptiveJevPassthrough(config, reason="missing_api_key")
    client = AdvisorClient(transport, max_queue=config.max_queue, workers=config.workers, max_rps=config.max_rps)
    return AdaptiveJev(config, client)


if __name__ == "__main__":
    build_bot().start()

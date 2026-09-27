"""MovementFlattener that reports enemy waves and wave visits to a listener without changing results."""
from __future__ import annotations

from typing import Protocol

from robocode_tank_royale.bot_api import Bot

from bot_core.movement import MovementFlattener, MovementWave


class MovementWaveListener(Protocol):
    def on_enemy_wave(self, bot: Bot, wave: MovementWave) -> None: ...

    def on_wave_visit(self, bot: Bot, wave: MovementWave, guess_factor: float, hit: bool) -> None: ...

    def on_round_cleared(self) -> None: ...

    def on_listener_error(self, error: Exception) -> None: ...


class ObservedMovementFlattener(MovementFlattener):
    """Same decisions as ``MovementFlattener``; listener failures are reported and never propagate."""

    def __init__(self, config, listener: MovementWaveListener) -> None:
        super().__init__(config)
        self._listener = listener
        self._visit_bot: Bot | None = None
        self._visit_hit = False

    def record_enemy_fire(self, bot: Bot, target, fire_power: float, *args, **kwargs) -> MovementWave | None:
        wave = super().record_enemy_fire(bot, target, fire_power, *args, **kwargs)
        if wave is not None:
            self._notify(self._listener.on_enemy_wave, bot, wave)
        return wave

    def update(self, bot: Bot):
        self._visit_bot, self._visit_hit = bot, False
        try:
            return super().update(bot)
        finally:
            self._visit_bot = None

    def record_bullet_hit(self, bot: Bot, target_id: int, bullet_power: float):
        self._visit_bot, self._visit_hit = bot, True
        try:
            return super().record_bullet_hit(bot, target_id, bullet_power)
        finally:
            self._visit_bot, self._visit_hit = None, False

    def clear_round_state(self) -> None:
        super().clear_round_state()
        self._notify(self._listener.on_round_cleared)

    def _record_visit(self, wave: MovementWave, bin_index: int, weight: float) -> float:
        visits = super()._record_visit(wave, bin_index, weight)
        bot = self._visit_bot
        if bot is not None:
            self._notify(self._listener.on_wave_visit, bot, wave, self._guess_factor(wave, bot.x, bot.y), self._visit_hit)
        return visits

    def _notify(self, callback, *args) -> None:
        try:
            callback(*args)
        except Exception as error:  # noqa: BLE001 - advisor bookkeeping must never break movement.
            try:
                self._listener.on_listener_error(error)
            except Exception:  # noqa: BLE001
                pass

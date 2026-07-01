import math

from robocode_tank_royale.bot_api import Bot

from bot_core.movement.config import MovementFlatteningConfig
from bot_core.movement.waves import MovementWave, MovementWaveStore


class SurfingPlanner:
    def __init__(self, config: MovementFlatteningConfig, wave_store: MovementWaveStore) -> None:
        self.config = config
        self.wave_store = wave_store

    def surf_wave(self, bot: Bot, target_id: int) -> MovementWave | None:
        candidates = self.wave_store.for_target(target_id)
        if not candidates:
            return None

        def remaining_distance(wave: MovementWave) -> float:
            radius = wave.bullet_speed * max(0, bot.turn_number - wave.fired_turn)
            distance = math.hypot(bot.x - wave.source_x, bot.y - wave.source_y)
            return distance - radius

        incoming = [wave for wave in candidates if remaining_distance(wave) > -self.config.surf_intercept_margin]
        if incoming:
            return min(incoming, key=remaining_distance)
        return max(candidates, key=lambda wave: wave.fired_turn)

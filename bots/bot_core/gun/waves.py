from bot_core.gun.models import GunConfig, GunWave


class GunWaveTracker:
    def __init__(self, config: GunConfig, waves: list[GunWave]) -> None:
        self.config = config
        self.waves = waves
        self.pending_wave: GunWave | None = None

    def set_pending_wave(self, wave: GunWave) -> None:
        self.pending_wave = wave

    def record_pending_fire(self) -> GunWave | None:
        wave = self.pending_wave
        if wave is None:
            return None
        self.waves.append(wave)
        if len(self.waves) > self.config.max_waves:
            del self.waves[: len(self.waves) - self.config.max_waves]
        self.pending_wave = None
        return wave

    def replace(self, waves: list[GunWave]) -> None:
        self.waves[:] = waves[-self.config.max_waves :]

    def clear_round_state(self) -> None:
        self.waves.clear()
        self.pending_wave = None

    def remove_target(self, target_id: int) -> None:
        self.waves[:] = [wave for wave in self.waves if wave.target_id != target_id]
        if self.pending_wave is not None and self.pending_wave.target_id == target_id:
            self.pending_wave = None

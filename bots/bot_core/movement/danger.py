from bot_core.movement.config import MovementFlatteningConfig
from bot_core.movement.decisions import MovementDangerBreakdown
from bot_core.movement.profile import MovementProfile
from bot_core.movement.waves import MovementWave
from bot_core.tank_math import clamp


class MovementDangerModel:
    def __init__(self, config: MovementFlatteningConfig, profile: MovementProfile) -> None:
        self.config = config
        self.profile = profile

    def breakdown(self, wave: MovementWave, bin_index: int) -> MovementDangerBreakdown:
        profile_danger = self.profile.smoothed_count(wave.target_id, wave.distance_bucket, bin_index)
        ensemble = self.profile.stats_buffers.danger(wave, bin_index)
        ensemble_confidence = clamp(
            ensemble.samples / max(1.0, self.config.stats_buffer_max_effective_samples),
            0.0,
            1.0,
        )
        ensemble_weight = self.config.stats_buffer_weight * ensemble_confidence
        ensemble_delta = max(0.0, ensemble.danger - profile_danger)
        learned_danger = profile_danger + ensemble_delta * ensemble_weight
        return MovementDangerBreakdown(
            profile_danger=profile_danger,
            ensemble_danger=ensemble.danger,
            ensemble_samples=ensemble.samples,
            ensemble_weight=ensemble_weight,
            total_danger=learned_danger + self.config.unvisited_bin_danger,
        )

from dataclasses import dataclass
from typing import Callable

from bot_core.geometry.angles import relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.geometry.waves import guess_factor_from_offset
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, guess_factor_aim_bearing
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.gun.guns.traditional_gf.diagnostics import TraditionalGfDiagnostics
from bot_core.gun.guns.traditional_gf.profile import GuessFactorProfile
from bot_core.gun.models import GunWave
from bot_core.gun.utils import bin_to_guess_factor


@dataclass
class SourceBiasCorrection:
    samples: int = 0
    correction: float = 0.0


class TraditionalGfGun:
    mode = "traditional_gf"

    def __init__(self, config: TraditionalGfGunConfig) -> None:
        self.config = config
        self.profiles: dict[int, GuessFactorProfile] = {}
        self.segment_profiles: dict[tuple[int, tuple[int, ...]], GuessFactorProfile] = {}
        self.coarse_segment_profiles: dict[tuple[int, tuple[int, ...]], GuessFactorProfile] = {}
        self.source_biases: dict[tuple[int, str], SourceBiasCorrection] = {}
        self.mode_policy = config.mode_policy()

    def aim(self, context: AimContext) -> GunBearing | None:
        if self.mode in context.disabled_modes:
            return None
        diagnostics = self.diagnostics(context.target.bot_id, context.segment_key)
        guess_factor = diagnostics.selected_guess_factor if diagnostics is not None else None
        if guess_factor is None:
            return None
        return GunBearing(
            self.mode,
            guess_factor_aim_bearing(context.bot, context.target, context.firepower, guess_factor),
            guess_factor=guess_factor,
            decision_context=GunDecisionContext(
                self.mode,
                {
                    "source": diagnostics.source,
                    "blend": diagnostics.blend,
                    "context_tags": self._context_tags(diagnostics.source, context),
                },
            ),
            metadata={self.mode: diagnostics},
        )

    def observe_visit(self, visit: GunVisit) -> None:
        self.record(visit.wave.target_id, visit.guess_factor, visit.segment_key)
        self.record_source_bias(visit)

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        error = self.error(visit.wave, visit.guess_factor)
        if error is None:
            return {}
        aim_guess_factor, signed_error, abs_error = error
        source = None
        raw_guess_factor = None
        source_bias_correction = None
        source_bias_samples = None
        metadata = visit.wave.gun_metadata.get(self.mode)
        metadata_source = getattr(metadata, "source", None)
        if isinstance(metadata_source, str):
            source = metadata_source
        metadata_raw_guess_factor = getattr(metadata, "raw_guess_factor", None)
        if isinstance(metadata_raw_guess_factor, int | float):
            raw_guess_factor = float(metadata_raw_guess_factor)
        metadata_source_bias_correction = getattr(metadata, "source_bias_correction", None)
        if isinstance(metadata_source_bias_correction, int | float):
            source_bias_correction = float(metadata_source_bias_correction)
        metadata_source_bias_samples = getattr(metadata, "source_bias_samples", None)
        if isinstance(metadata_source_bias_samples, int):
            source_bias_samples = metadata_source_bias_samples
        diagnostics: dict[str, object] = {
            "aim_guess_factor": aim_guess_factor,
            "error": signed_error,
            "abs_error": abs_error,
            "source": source,
        }
        if raw_guess_factor is not None:
            diagnostics["raw_guess_factor"] = raw_guess_factor
        if source_bias_correction is not None:
            diagnostics["source_bias_correction"] = source_bias_correction
        if source_bias_samples is not None:
            diagnostics["source_bias_samples"] = source_bias_samples
        return diagnostics

    @staticmethod
    def _context_tags(source: str, context: AimContext) -> frozenset[str]:
        tags = set(context.movement_tags.intersection({"stable_pattern"}))
        if source in {"segment", "coarse"}:
            tags.update({"trusted_segment", "stable_pattern"})
            return frozenset(tags)
        if source in {"blend", "coarse_blend"}:
            tags.add("stable_pattern")
        return frozenset(tags)

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        return {}

    def record(
        self,
        target_id: int,
        guess_factor: float,
        segment_key: tuple[int, ...] | None = None,
    ) -> None:
        profile = self.profiles.setdefault(
            target_id,
            GuessFactorProfile.with_bins(self.config.guess_factor_bins),
        )
        self.record_profile(profile, guess_factor, self.config.smoothing_bins, self.config.decay)
        if self.config.segment_min_samples > 0 and segment_key is not None:
            segment_profile = self.segment_profiles.setdefault(
                (target_id, segment_key),
                GuessFactorProfile.with_bins(self.config.guess_factor_bins),
            )
            self.record_profile(segment_profile, guess_factor, self.config.smoothing_bins, self.config.decay)
        if (
            self.config.segment_min_samples > 0
            and self.config.coarse_segment_min_samples > 0
            and segment_key is not None
        ):
            coarse_key = self.coarse_segment_key(segment_key)
            coarse_profile = self.coarse_segment_profiles.setdefault(
                (target_id, coarse_key),
                GuessFactorProfile.with_bins(self.config.guess_factor_bins),
            )
            self.record_profile(coarse_profile, guess_factor, self.config.smoothing_bins, self.config.decay)

    def record_source_bias(self, visit: GunVisit) -> None:
        metadata = visit.wave.gun_metadata.get(self.mode)
        source = getattr(metadata, "source", None)
        raw_guess_factor = getattr(metadata, "raw_guess_factor", None)
        if not isinstance(source, str) or not isinstance(raw_guess_factor, int | float):
            return

        key = (visit.wave.target_id, source)
        state = self.source_biases.setdefault(key, SourceBiasCorrection())
        raw_error = clamp(float(visit.guess_factor) - float(raw_guess_factor), -1.0, 1.0)
        learning_rate = clamp(self.config.source_bias_learning_rate, 0.0, 1.0)
        max_correction = max(0.0, self.config.source_bias_max_correction)
        state.samples += 1
        state.correction = clamp(
            (1.0 - learning_rate) * state.correction + learning_rate * raw_error,
            -max_correction,
            max_correction,
        )

    def record_profile(
        self,
        profile: GuessFactorProfile,
        guess_factor: float,
        smoothing_bins: float,
        decay: float,
    ) -> None:
        profile.record(guess_factor, self.config.guess_factor_bins, smoothing_bins, decay)

    def guess_factor(
        self,
        target_id: int,
        segment_key: tuple[int, ...] | None = None,
    ) -> float | None:
        diagnostics = self.diagnostics(target_id, segment_key)
        return diagnostics.selected_guess_factor if diagnostics is not None else None

    def diagnostics(
        self,
        target_id: int,
        segment_key: tuple[int, ...] | None = None,
    ) -> TraditionalGfDiagnostics | None:
        profile = self.profiles.get(target_id)
        if profile is None or profile.effective_weight < self.config.min_samples:
            return None
        global_guess_factor = self.profile_guess_factor(profile)
        if self.config.segment_min_samples <= 0 or segment_key is None:
            raw_guess_factor = self.center_guess_factor(global_guess_factor, "global")
            selected_guess_factor, source_bias_correction, source_bias_samples = self.apply_source_bias(
                target_id,
                "global",
                raw_guess_factor,
            )
            return TraditionalGfDiagnostics(
                global_guess_factor=global_guess_factor,
                global_weight=profile.effective_weight,
                raw_guess_factor=raw_guess_factor,
                selected_guess_factor=selected_guess_factor,
                source="global",
                source_bias_correction=source_bias_correction,
                source_bias_samples=source_bias_samples,
            )

        segment_profile = self.segment_profiles.get((target_id, segment_key))
        if (
            segment_profile is None
            or segment_profile.effective_weight < self.config.segment_min_samples
        ):
            coarse_diagnostics = self.coarse_diagnostics(
                target_id,
                segment_key,
                profile,
                global_guess_factor,
            )
            if coarse_diagnostics is not None:
                return coarse_diagnostics
            raw_guess_factor = self.center_guess_factor(global_guess_factor, "global")
            selected_guess_factor, source_bias_correction, source_bias_samples = self.apply_source_bias(
                target_id,
                "global",
                raw_guess_factor,
            )
            return TraditionalGfDiagnostics(
                global_guess_factor=global_guess_factor,
                global_weight=profile.effective_weight,
                segment_weight=segment_profile.effective_weight if segment_profile is not None else 0.0,
                raw_guess_factor=raw_guess_factor,
                selected_guess_factor=selected_guess_factor,
                source="global",
                source_bias_correction=source_bias_correction,
                source_bias_samples=source_bias_samples,
            )

        blend = clamp(
            (segment_profile.effective_weight - self.config.segment_min_samples)
            / max(1.0, self.config.segment_full_weight_samples - self.config.segment_min_samples),
            0.0,
            1.0,
        )
        segment_guess_factor = self.profile_guess_factor(segment_profile)
        blended_guess_factor = self.blended_profile_guess_factor(profile, segment_profile, blend)
        source = "segment" if blend >= 1.0 else "blend"
        raw_guess_factor = self.center_guess_factor(blended_guess_factor, source)
        selected_guess_factor, source_bias_correction, source_bias_samples = self.apply_source_bias(
            target_id,
            source,
            raw_guess_factor,
        )
        return TraditionalGfDiagnostics(
            global_guess_factor=global_guess_factor,
            global_weight=profile.effective_weight,
            segment_guess_factor=segment_guess_factor,
            segment_weight=segment_profile.effective_weight,
            blend=blend,
            raw_guess_factor=raw_guess_factor,
            selected_guess_factor=selected_guess_factor,
            source=source,
            source_bias_correction=source_bias_correction,
            source_bias_samples=source_bias_samples,
        )

    def coarse_diagnostics(
        self,
        target_id: int,
        segment_key: tuple[int, ...],
        global_profile: GuessFactorProfile,
        global_guess_factor: float,
    ) -> TraditionalGfDiagnostics | None:
        if self.config.coarse_segment_min_samples <= 0:
            return None
        coarse_key = self.coarse_segment_key(segment_key)
        coarse_profile = self.coarse_segment_profiles.get((target_id, coarse_key))
        if (
            coarse_profile is None
            or coarse_profile.effective_weight < self.config.coarse_segment_min_samples
        ):
            return None
        blend = clamp(
            (coarse_profile.effective_weight - self.config.coarse_segment_min_samples)
            / max(1.0, self.config.coarse_segment_full_weight_samples - self.config.coarse_segment_min_samples),
            0.0,
            1.0,
        )
        coarse_guess_factor = self.profile_guess_factor(coarse_profile)
        blended_guess_factor = self.blended_profile_guess_factor(global_profile, coarse_profile, blend)
        source = "coarse" if blend >= 1.0 else "coarse_blend"
        raw_guess_factor = self.center_guess_factor(blended_guess_factor, source)
        selected_guess_factor, source_bias_correction, source_bias_samples = self.apply_source_bias(
            target_id,
            source,
            raw_guess_factor,
        )
        return TraditionalGfDiagnostics(
            global_guess_factor=global_guess_factor,
            global_weight=global_profile.effective_weight,
            segment_guess_factor=coarse_guess_factor,
            segment_weight=coarse_profile.effective_weight,
            blend=blend,
            raw_guess_factor=raw_guess_factor,
            selected_guess_factor=selected_guess_factor,
            source=source,
            source_bias_correction=source_bias_correction,
            source_bias_samples=source_bias_samples,
        )

    @staticmethod
    def coarse_segment_key(segment_key: tuple[int, ...]) -> tuple[int, ...]:
        return (segment_key[0], segment_key[2], segment_key[5])

    def profile_guess_factor(self, profile: GuessFactorProfile) -> float:
        if self.config.peak_selection == "density":
            return self.density_peak_guess_factor(lambda index: profile.bins[index])
        best_index = max(range(len(profile.bins)), key=lambda index: profile.bins[index])
        return bin_to_guess_factor(best_index, self.config.guess_factor_bins)

    def blended_profile_guess_factor(
        self,
        global_profile: GuessFactorProfile,
        segment_profile: GuessFactorProfile,
        segment_weight: float,
    ) -> float:
        def blended_value(index: int) -> float:
            return (
                (1.0 - segment_weight) * self.normalized_bin(global_profile, index)
                + segment_weight * self.normalized_bin(segment_profile, index)
            )

        if self.config.peak_selection == "density":
            return self.density_peak_guess_factor(blended_value)
        best_index = max(range(self.config.guess_factor_bins), key=blended_value)
        return bin_to_guess_factor(best_index, self.config.guess_factor_bins)

    def density_peak_guess_factor(self, value_at: Callable[[int], float]) -> float:
        bins = self.config.guess_factor_bins
        radius = max(0, self.config.peak_support_radius)
        if radius <= 0:
            best_index = max(range(bins), key=value_at)
            return bin_to_guess_factor(best_index, bins)

        def support_weight(center: int, index: int) -> float:
            return (radius + 1 - abs(index - center)) / (radius + 1)

        def supported_density(center: int) -> float:
            start = max(0, center - radius)
            end = min(bins, center + radius + 1)
            return sum(value_at(index) * support_weight(center, index) for index in range(start, end))

        best_index = max(range(bins), key=supported_density)
        start = max(0, best_index - radius)
        end = min(bins, best_index + radius + 1)
        total_weight = 0.0
        weighted_guess_factor = 0.0
        for index in range(start, end):
            weight = max(0.0, value_at(index)) * support_weight(best_index, index)
            total_weight += weight
            weighted_guess_factor += bin_to_guess_factor(index, bins) * weight
        if total_weight <= 0.0:
            return bin_to_guess_factor(best_index, bins)
        return clamp(weighted_guess_factor / total_weight, -1.0, 1.0)

    @staticmethod
    def normalized_bin(profile: GuessFactorProfile, index: int) -> float:
        return profile.normalized_bin(index)

    def center_guess_factor(self, guess_factor: float, source: str | None = None) -> float:
        return clamp(guess_factor * self.source_centering_factor(source), -1.0, 1.0)

    def source_centering_factor(self, source: str | None) -> float:
        factor = self.config.centering_factor
        if source == "global":
            factor *= self.config.global_source_centering_factor
        elif source == "blend":
            factor *= self.config.blend_source_centering_factor
        elif source == "segment":
            factor *= self.config.segment_source_centering_factor
        elif source == "coarse":
            factor *= self.config.coarse_source_centering_factor
        elif source == "coarse_blend":
            factor *= self.config.coarse_blend_source_centering_factor
        return clamp(factor, 0.0, 1.0)

    def apply_source_bias(self, target_id: int, source: str, raw_guess_factor: float) -> tuple[float, float, int]:
        correction, samples = self.source_bias_correction(target_id, source)
        return clamp(raw_guess_factor + correction, -1.0, 1.0), correction, samples

    def source_bias_correction(self, target_id: int, source: str) -> tuple[float, int]:
        state = self.source_biases.get((target_id, source))
        if state is None:
            return 0.0, 0
        if state.samples < self.config.source_bias_min_samples:
            return 0.0, state.samples
        max_correction = max(0.0, self.config.source_bias_max_correction)
        return clamp(state.correction, -max_correction, max_correction), state.samples

    @staticmethod
    def error(wave: GunWave, actual_guess_factor: float) -> tuple[float, float, float] | None:
        aim_bearing = wave.virtual_bearings.get("traditional_gf")
        if aim_bearing is None:
            return None
        aim_offset = relative_bearing(aim_bearing, wave.fire_bearing)
        aim_guess_factor = guess_factor_from_offset(
            aim_offset,
            wave.lateral_direction,
            wave.max_escape_angle_positive,
            wave.max_escape_angle_negative,
        )
        error = actual_guess_factor - aim_guess_factor
        return aim_guess_factor, error, abs(error)

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None

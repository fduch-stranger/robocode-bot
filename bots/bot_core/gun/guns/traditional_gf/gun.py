from bot_core.geometry.angles import relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.geometry.waves import guess_factor_from_offset
from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, guess_factor_aim_bearing
from bot_core.gun.guess_factors import bin_to_guess_factor
from bot_core.gun.guns.traditional_gf.config import TraditionalGfGunConfig
from bot_core.gun.guns.traditional_gf.diagnostics import TraditionalGfDiagnostics
from bot_core.gun.guns.traditional_gf.profile import GuessFactorProfile
from bot_core.gun.models import FireContext, GunWave


class TraditionalGfGun:
    mode = "traditional_gf"

    def __init__(self, config: TraditionalGfGunConfig) -> None:
        self.config = config
        self.profiles: dict[int, GuessFactorProfile] = {}
        self.segment_profiles: dict[tuple[int, tuple[int, ...]], GuessFactorProfile] = {}
        self.mode_policy = config.mode_policy()

    def aim(self, context: AimContext) -> GunBearing | None:
        if self.mode in context.disabled_modes:
            return None
        profile_key = self.profile_segment_key(context.fire_context)
        diagnostics = self.diagnostics(context.target.bot_id, profile_key)
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
        profile_key = self.profile_segment_key(visit.wave.fire_context)
        self.record(visit.wave.target_id, visit.guess_factor, profile_key)

    def profile_segment_key(
        self,
        fire_context: FireContext,
    ) -> tuple[int, ...]:
        flight_time = fire_context.bullet_flight_time
        flight_bucket = 0 if flight_time < 20.0 else 1 if flight_time < 35.0 else 2
        lateral_speed = abs(fire_context.lateral_speed_signed)
        lateral_bucket = 0 if lateral_speed < 2.0 else 1 if lateral_speed < 5.6 else 2
        wall_margin = fire_context.wall_margin
        wall_bucket = 0 if wall_margin < 0.12 else 1 if wall_margin < 0.25 else 2
        return (flight_bucket, lateral_bucket, wall_bucket)

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        profile_key = self.profile_segment_key(visit.wave.fire_context)
        segment_profile = self.segment_profiles.get((visit.wave.target_id, profile_key))
        error = self.error(visit.wave, visit.guess_factor)
        source = None
        metadata = visit.wave.gun_metadata.get(self.mode)
        metadata_source = getattr(metadata, "source", None)
        if isinstance(metadata_source, str):
            source = metadata_source
        diagnostics: dict[str, object] = {
            "source": source,
            "profile_key": profile_key,
            "segment_weight": segment_profile.effective_weight if segment_profile is not None else 0.0,
        }
        if error is not None:
            aim_guess_factor, signed_error, abs_error = error
            diagnostics.update(
                aim_guess_factor=aim_guess_factor,
                error=signed_error,
                abs_error=abs_error,
            )
        diagnostics.update(self._fire_context_diagnostics(visit))
        return diagnostics

    @staticmethod
    def _context_tags(source: str, context: AimContext) -> frozenset[str]:
        tags = set(context.movement_tags.intersection({"stable_pattern"}))
        if source == "segment":
            tags.update({"trusted_segment", "stable_pattern"})
            return frozenset(tags)
        if source == "blend":
            tags.add("stable_pattern")
        return frozenset(tags)

    @staticmethod
    def _fire_context_diagnostics(visit: GunVisit) -> dict[str, object]:
        context = visit.wave.fire_context
        return {
            "context_flight_time": context.bullet_flight_time,
            "context_wall_escape_balance": context.wall_escape_balance,
            "context_lateral_confidence": context.lateral_direction_confidence,
            "context_tags": context.movement_tags,
        }

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
            return TraditionalGfDiagnostics(
                global_guess_factor=global_guess_factor,
                global_weight=profile.effective_weight,
                selected_guess_factor=self._bounded_aim_guess_factor(global_guess_factor),
                source="global",
                profile_key=segment_key or (),
            )

        segment_profile = self.segment_profiles.get((target_id, segment_key))
        if (
            segment_profile is None
            or segment_profile.effective_weight < self.config.segment_min_samples
        ):
            return TraditionalGfDiagnostics(
                global_guess_factor=global_guess_factor,
                global_weight=profile.effective_weight,
                segment_weight=segment_profile.effective_weight if segment_profile is not None else 0.0,
                selected_guess_factor=self._bounded_aim_guess_factor(global_guess_factor),
                source="global",
                profile_key=segment_key,
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
        return TraditionalGfDiagnostics(
            global_guess_factor=global_guess_factor,
            global_weight=profile.effective_weight,
            segment_guess_factor=segment_guess_factor,
            segment_weight=segment_profile.effective_weight,
            blend=blend,
            selected_guess_factor=self._bounded_aim_guess_factor(blended_guess_factor),
            source=source,
            profile_key=segment_key,
        )

    def profile_guess_factor(self, profile: GuessFactorProfile) -> float:
        best_index = max(range(len(profile.bins)), key=lambda index: profile.bins[index])
        return bin_to_guess_factor(best_index, self.config.guess_factor_bins)

    def _bounded_aim_guess_factor(self, guess_factor: float) -> float:
        limit = clamp(self.config.max_aim_guess_factor, 0.0, 1.0)
        return clamp(guess_factor, -limit, limit)

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

        best_index = max(range(self.config.guess_factor_bins), key=blended_value)
        return bin_to_guess_factor(best_index, self.config.guess_factor_bins)

    @staticmethod
    def normalized_bin(profile: GuessFactorProfile, index: int) -> float:
        return profile.normalized_bin(index)


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

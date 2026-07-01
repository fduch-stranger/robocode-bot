import math
from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_core.gun.aim import AimModeSelector
from bot_core.gun.knn import RollingKnnBuffer
from bot_core.gun.models import (
    AimSolution,
    GunConfig,
    GunSample,
    GunStats,
    GunWave,
    GuessFactorProfile,
    TargetMotion,
    TargetPosition,
    WaveVisit,
)
from bot_core.gun.scoring import VirtualGunScorer
from bot_core.gun.utils import (
    bin_to_guess_factor,
    feature_distance,
    guess_factor_to_bin,
    lateral_direction,
    point_on_bearing,
    segment_features,
)
from bot_core.gun.waves import GunWaveTracker
from bot_core.geometry.angles import absolute_bearing_between, relative_bearing
from bot_core.geometry.numeric import clamp
from bot_core.geometry.position import predicted_position
from bot_core.geometry.waves import (
    escape_angle_for_guess_factor,
    guess_factor_from_offset,
    wall_limited_escape_angle,
)
from bot_core.physics import bullet_speed_for_power
from bot_core.target_snapshot import TargetSnapshot


@dataclass
class VirtualGunSystem:
    config: GunConfig = field(default_factory=GunConfig)
    _knn_memory: RollingKnnBuffer = field(init=False)
    _waves: list[GunWave] = field(default_factory=list)
    _stats: dict[tuple[int, str], GunStats] = field(default_factory=dict)
    _segment_stats: dict[tuple[int, str, tuple[int, ...]], GunStats] = field(default_factory=dict)
    _active_modes: dict[int, str] = field(default_factory=dict)
    _target_history: dict[int, list[TargetPosition]] = field(default_factory=dict)
    _traditional_profiles: dict[int, GuessFactorProfile] = field(default_factory=dict)
    _anti_surfer_profiles: dict[int, GuessFactorProfile] = field(default_factory=dict)
    _wave_tracker: GunWaveTracker = field(init=False)
    _scorer: VirtualGunScorer = field(init=False)
    _aim_selector: AimModeSelector = field(init=False)
    _knn_sequence: int = 0

    def __post_init__(self) -> None:
        self._knn_memory = RollingKnnBuffer(self.config.max_samples, self.config.max_samples_per_target)
        self._wave_tracker = GunWaveTracker(self.config, self._waves)
        self._scorer = VirtualGunScorer(self.config, self._stats, self._segment_stats)
        self._aim_selector = AimModeSelector(self.config, self._scorer, self._active_modes, self._stats)

    @property
    def sample_count(self) -> int:
        return self._knn_memory.sample_count

    @property
    def wave_count(self) -> int:
        return len(self._waves)

    def observe_target(self, target: TargetSnapshot) -> None:
        history = self._target_history.setdefault(target.bot_id, [])
        if history and history[-1].turn == target.seen_turn:
            history[-1] = TargetPosition(target.seen_turn, target.x, target.y, target.speed)
        else:
            history.append(TargetPosition(target.seen_turn, target.x, target.y, target.speed))
        if len(history) > self.config.max_target_history:
            del history[: len(history) - self.config.max_target_history]

    def aim(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        motion: TargetMotion,
        field_margin: float,
        allow_traditional_gf: bool = True,
        allow_segmented_stats: bool = True,
    ) -> AimSolution:
        features = self._gun_features(bot, target, distance, firepower, motion)
        segment_key = segment_features(features)
        scoring_segment = segment_key if allow_segmented_stats else None
        absolute_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
        virtual_bearings = {
            "head_on": absolute_bearing,
            "linear": self._linear_aim_bearing(bot, target, firepower, field_margin),
        }
        displacement_bearing = self._displacement_aim_bearing(bot, target, distance, firepower, field_margin)
        if displacement_bearing is not None:
            virtual_bearings["displacement"] = displacement_bearing

        traditional_guess_factor = self._traditional_guess_factor(target.bot_id) if allow_traditional_gf else None
        if traditional_guess_factor is not None:
            virtual_bearings["traditional_gf"] = self._guess_factor_aim_bearing(
                bot,
                target,
                firepower,
                traditional_guess_factor,
            )

        anti_surfer_guess_factor = self._anti_surfer_guess_factor(target.bot_id)
        if anti_surfer_guess_factor is not None:
            virtual_bearings["anti_surfer"] = self._guess_factor_aim_bearing(
                bot,
                target,
                firepower,
                anti_surfer_guess_factor,
            )

        cluster_guess_factor = self._knn_guess_factor(target.bot_id, features)
        if cluster_guess_factor is not None:
            virtual_bearings["dynamic_cluster"] = self._guess_factor_aim_bearing(
                bot,
                target,
                firepower,
                cluster_guess_factor,
            )

        mode, previous_mode, mode_changed = self._select_aim_mode(target.bot_id, virtual_bearings, scoring_segment)
        aim_bearing = virtual_bearings[mode]
        predicted_x, predicted_y = point_on_bearing(bot, aim_bearing, distance, field_margin)
        selected_guess_factor = None
        if mode == "traditional_gf":
            selected_guess_factor = traditional_guess_factor
        elif mode == "anti_surfer":
            selected_guess_factor = anti_surfer_guess_factor
        elif mode == "dynamic_cluster":
            selected_guess_factor = cluster_guess_factor
        return AimSolution(
            predicted_x=predicted_x,
            predicted_y=predicted_y,
            gun_bearing=relative_bearing(aim_bearing, bot.gun_direction),
            mode=mode,
            guess_factor=selected_guess_factor,
            features=features,
            segment_key=segment_key,
            virtual_bearings=virtual_bearings,
            previous_mode=previous_mode,
            mode_changed=mode_changed,
        )

    @staticmethod
    def make_wave(
        bot: Bot,
        target: TargetSnapshot,
        firepower: float,
        aim: AimSolution,
    ) -> GunWave:
        bullet_speed = bullet_speed_for_power(firepower)
        fire_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
        wave_lateral_direction = lateral_direction(target, fire_bearing)
        return GunWave(
            source_x=bot.x,
            source_y=bot.y,
            fire_turn=bot.turn_number,
            fire_bearing=fire_bearing,
            target_id=target.bot_id,
            bullet_power=firepower,
            bullet_speed=bullet_speed,
            max_escape_angle_positive=wall_limited_escape_angle(
                bot,
                target,
                bullet_speed,
                wave_lateral_direction,
            ),
            max_escape_angle_negative=wall_limited_escape_angle(
                bot,
                target,
                bullet_speed,
                -wave_lateral_direction,
            ),
            lateral_direction=wave_lateral_direction,
            features=aim.features,
            segment_key=aim.segment_key,
            aim_mode=aim.mode,
            aim_guess_factor=aim.guess_factor,
            virtual_bearings=aim.virtual_bearings,
        )

    def set_pending_wave(self, wave: GunWave) -> None:
        self._wave_tracker.set_pending_wave(wave)

    def record_pending_fire(self) -> GunWave | None:
        return self._wave_tracker.record_pending_fire()

    def update_waves(self, bot: Bot, target: TargetSnapshot) -> list[WaveVisit]:
        visits: list[WaveVisit] = []
        remaining_waves: list[GunWave] = []
        for wave in self._wave_tracker.waves:
            if wave.target_id != target.bot_id:
                remaining_waves.append(wave)
                continue

            traveled = (bot.turn_number - wave.fire_turn) * wave.bullet_speed
            target_distance = math.hypot(target.x - wave.source_x, target.y - wave.source_y)
            if traveled + self.config.wave_visit_margin < target_distance:
                remaining_waves.append(wave)
                continue

            actual_bearing = absolute_bearing_between(wave.source_x, wave.source_y, target.x, target.y)
            bearing_offset = relative_bearing(actual_bearing, wave.fire_bearing)
            guess_factor = guess_factor_from_offset(
                bearing_offset,
                wave.lateral_direction,
                wave.max_escape_angle_positive,
                wave.max_escape_angle_negative,
            )
            virtual_scores = self._score_virtual_guns(wave, actual_bearing, target_distance)
            self._knn_sequence += 1
            self._knn_memory.add(GunSample(wave.target_id, self._knn_sequence, wave.features, guess_factor))
            self._record_traditional_guess_factor(wave.target_id, guess_factor)
            self._record_anti_surfer_guess_factor(wave.target_id, guess_factor)
            visits.append(
                WaveVisit(
                    target_id=target.bot_id,
                    guess_factor=guess_factor,
                    samples=self._knn_memory.target_sample_count(target.bot_id),
                    traveled=traveled,
                    distance=target_distance,
                    selected_gun=wave.aim_mode,
                    virtual_scores=virtual_scores,
                    gun_scores=self.score_summary(target.bot_id, wave.segment_key),
                )
            )

        self._wave_tracker.replace(remaining_waves)
        return visits

    def score_summary(self, target_id: int, segment_key: tuple[int, ...] | None = None) -> dict[str, str]:
        return self._scorer.score_summary(target_id, segment_key)

    def target_confidence(self, target_id: int) -> tuple[float, int]:
        return self._scorer.target_confidence(target_id)

    def clear_round_state(self) -> None:
        self._wave_tracker.clear_round_state()
        self._target_history.clear()

    def remove_target(self, target_id: int) -> None:
        self._wave_tracker.remove_target(target_id)
        self._active_modes.pop(target_id, None)
        self._target_history.pop(target_id, None)

    @staticmethod
    def _linear_aim_bearing(
        bot: Bot,
        target: TargetSnapshot,
        firepower: float,
        field_margin: float,
    ) -> float:
        predicted_x, predicted_y = predicted_position(bot, target, firepower, field_margin)
        return absolute_bearing_between(bot.x, bot.y, predicted_x, predicted_y)

    @staticmethod
    def _guess_factor_aim_bearing(
        bot: Bot,
        target: TargetSnapshot,
        firepower: float,
        guess_factor: float,
    ) -> float:
        absolute_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
        bullet_speed = bullet_speed_for_power(firepower)
        lateral = lateral_direction(target, absolute_bearing)
        escape_angle = escape_angle_for_guess_factor(bot, target, bullet_speed, lateral, guess_factor)
        return absolute_bearing + guess_factor * lateral * escape_angle

    def _displacement_aim_bearing(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        field_margin: float,
    ) -> float | None:
        history = self._target_history.get(target.bot_id, [])
        if len(history) < self.config.displacement_min_samples + 1:
            return None

        travel_ticks = max(1, round(distance / bullet_speed_for_power(firepower)))
        current = history[-1]
        samples: list[tuple[float, float]] = []
        for past in history[:-1]:
            elapsed = current.turn - past.turn
            if abs(elapsed - travel_ticks) > self.config.displacement_time_tolerance:
                continue
            samples.append((current.x - past.x, current.y - past.y))

        if len(samples) < self.config.displacement_min_samples:
            return None

        average_dx = sum(dx for dx, _ in samples) / len(samples)
        average_dy = sum(dy for _, dy in samples) / len(samples)
        predicted_x = clamp(target.x + average_dx, field_margin, bot.arena_width - field_margin)
        predicted_y = clamp(target.y + average_dy, field_margin, bot.arena_height - field_margin)
        return absolute_bearing_between(bot.x, bot.y, predicted_x, predicted_y)

    def _select_aim_mode(
        self,
        target_id: int,
        virtual_bearings: dict[str, float],
        segment_key: tuple[int, ...] | None,
    ) -> tuple[str, str | None, bool]:
        return self._aim_selector.select(target_id, virtual_bearings, segment_key)

    @staticmethod
    def _gun_features(
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        firepower: float,
        motion: TargetMotion,
    ) -> tuple[float, ...]:
        absolute_bearing = math.radians(absolute_bearing_between(bot.x, bot.y, target.x, target.y))
        heading = math.radians(target.direction)
        velocity_x = math.cos(heading) * target.speed
        velocity_y = math.sin(heading) * target.speed
        lateral_velocity = velocity_x * -math.sin(absolute_bearing) + velocity_y * math.cos(absolute_bearing)
        advancing_velocity = velocity_x * math.cos(absolute_bearing) + velocity_y * math.sin(absolute_bearing)
        wall_margin = min(
            target.x,
            bot.arena_width - target.x,
            target.y,
            bot.arena_height - target.y,
        )
        arena_scale = max(bot.arena_width, bot.arena_height)
        return (
            distance / arena_scale,
            firepower / 3.0,
            abs(lateral_velocity) / 8.0,
            advancing_velocity / 8.0,
            clamp(motion.acceleration / 8.0, -1.0, 1.0),
            min(60, motion.velocity_change_age) / 60.0,
            wall_margin / arena_scale,
        )

    def _knn_guess_factor(self, target_id: int, features: tuple[float, ...]) -> float | None:
        samples = self._knn_memory.samples_for(target_id)
        sample_count = len(samples)
        if sample_count < self.config.knn_min_samples:
            return None
        current_turn = self._knn_sequence
        effective_count = self._knn_memory.effective_count(
            target_id,
            current_turn=current_turn,
            half_life=self.config.knn_decay_half_life,
        )
        if effective_count < self.config.knn_min_effective_samples:
            return None

        neighbors = sorted(
            samples,
            key=lambda neighbor_sample: feature_distance(features, neighbor_sample.features)
            / max(
                0.25,
                self._knn_memory.decayed_weight(
                    neighbor_sample,
                    current_turn=current_turn,
                    half_life=self.config.knn_decay_half_life,
                ),
            ),
        )[: min(self.config.knn_neighbors, sample_count)]
        weighted_neighbors: list[tuple[GunSample, float]] = []
        for sample in neighbors:
            distance = feature_distance(features, sample.features)
            recency = self._knn_memory.decayed_weight(sample, current_turn, self.config.knn_decay_half_life)
            weight = recency / (0.05 + distance)
            weighted_neighbors.append((sample, weight))
        if not weighted_neighbors:
            return None

        guess_factor = 0.0
        best_score = -1.0
        for index in range(self.config.guess_factor_bins):
            candidate = -1.0 + 2.0 * index / (self.config.guess_factor_bins - 1)
            score = 0.0
            for sample, weight in weighted_neighbors:
                offset = (sample.guess_factor - candidate) / self.config.guess_factor_bandwidth
                score += weight * math.exp(-(offset * offset))
            if score > best_score:
                best_score = score
                guess_factor = candidate

        if sample_count < self.config.knn_blend_samples:
            blend = (sample_count - self.config.knn_min_samples) / (
                self.config.knn_blend_samples - self.config.knn_min_samples
            )
            guess_factor *= clamp(blend, 0.0, 1.0)
        return clamp(guess_factor, -1.0, 1.0)

    def _record_traditional_guess_factor(self, target_id: int, guess_factor: float) -> None:
        profile = self._traditional_profiles.setdefault(
            target_id,
            GuessFactorProfile(bins=[0.0] * self.config.guess_factor_bins),
        )
        profile.visits += 1
        profile.effective_weight = profile.effective_weight * self.config.traditional_gf_decay + 1.0
        bin_index = guess_factor_to_bin(guess_factor, self.config.guess_factor_bins)
        for index in range(self.config.guess_factor_bins):
            profile.bins[index] *= self.config.traditional_gf_decay
            offset = (index - bin_index) / self.config.traditional_gf_smoothing_bins
            profile.bins[index] += math.exp(-(offset * offset))

    def _traditional_guess_factor(self, target_id: int) -> float | None:
        profile = self._traditional_profiles.get(target_id)
        if profile is None or profile.effective_weight < self.config.traditional_gf_min_samples:
            return None
        best_index = max(range(len(profile.bins)), key=lambda index: profile.bins[index])
        return bin_to_guess_factor(best_index, self.config.guess_factor_bins)

    def _record_anti_surfer_guess_factor(self, target_id: int, guess_factor: float) -> None:
        profile = self._anti_surfer_profiles.setdefault(
            target_id,
            GuessFactorProfile(bins=[0.0] * self.config.guess_factor_bins),
        )
        profile.visits += 1
        profile.effective_weight = profile.effective_weight * self.config.anti_surfer_decay + 1.0
        bin_index = guess_factor_to_bin(guess_factor, self.config.guess_factor_bins)
        for index in range(self.config.guess_factor_bins):
            profile.bins[index] *= self.config.anti_surfer_decay
            offset = (index - bin_index) / self.config.anti_surfer_smoothing_bins
            profile.bins[index] += math.exp(-(offset * offset))

    def _anti_surfer_guess_factor(self, target_id: int) -> float | None:
        profile = self._anti_surfer_profiles.get(target_id)
        if profile is None or profile.effective_weight < self.config.anti_surfer_min_samples:
            return None

        center = (self.config.guess_factor_bins - 1) / 2.0
        candidates = range(1, self.config.guess_factor_bins - 1)
        safest_index = min(
            candidates,
            key=lambda index: (
                profile.bins[index],
                abs(index - center),
            ),
        )
        return bin_to_guess_factor(safest_index, self.config.guess_factor_bins)

    def _score_virtual_guns(
        self,
        wave: GunWave,
        actual_bearing: float,
        target_distance: float,
    ) -> dict[str, float]:
        return self._scorer.score_virtual_guns(wave, actual_bearing, target_distance)

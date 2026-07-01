import math
from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_utils.tank_math import TargetSnapshot, clamp, predicted_position
from bot_utils.wave_math import (
    absolute_bearing_between,
    bullet_speed_for_power,
    escape_angle_for_guess_factor,
    guess_factor_from_offset,
    max_escape_angle_for_speed,
    relative_bearing,
    wall_limited_escape_angle,
)


@dataclass(frozen=True)
class GunConfig:
    max_samples: int = 1200
    max_samples_per_target: int = 900
    max_waves: int = 80
    knn_min_samples: int = 60
    knn_blend_samples: int = 150
    knn_neighbors: int = 17
    knn_decay_half_life: float = 0.0
    knn_min_effective_samples: float = 0.0
    wave_visit_margin: float = 18
    guess_factor_bins: int = 31
    guess_factor_bandwidth: float = 0.18
    default_mode: str = "linear"
    selectable_modes: frozenset[str] = frozenset({"linear", "traditional_gf", "dynamic_cluster"})
    min_visits: int = 90
    switch_margin: float = 0.08
    min_switch_score: float = 0.30
    head_on_min_switch_score: float = 0.45
    score_alpha: float = 0.12
    virtual_hit_radius: float = 18
    max_target_history: int = 80
    displacement_min_samples: int = 4
    displacement_time_tolerance: int = 2
    traditional_gf_min_samples: int = 28
    traditional_gf_smoothing_bins: float = 1.25
    traditional_gf_decay: float = 0.985
    traditional_gf_min_switch_visits: int = 260
    traditional_gf_min_switch_score: float = 0.42
    anti_surfer_min_samples: int = 7
    anti_surfer_smoothing_bins: float = 0.9
    anti_surfer_decay: float = 0.92
    anti_surfer_min_switch_visits: int = 80
    anti_surfer_min_switch_score: float = 0.32
    segment_min_visits: int = 18
    segment_full_weight_visits: int = 80


@dataclass(frozen=True)
class TargetMotion:
    acceleration: float = 0.0
    velocity_change_age: int = 0


@dataclass
class GunSample:
    target_id: int
    turn: int
    features: tuple[float, ...]
    guess_factor: float


@dataclass
class GunWave:
    source_x: float
    source_y: float
    fire_turn: int
    fire_bearing: float
    target_id: int
    bullet_power: float
    bullet_speed: float
    max_escape_angle: float
    max_escape_angle_positive: float
    max_escape_angle_negative: float
    lateral_direction: int
    features: tuple[float, ...]
    segment_key: tuple[int, ...]
    aim_mode: str
    aim_guess_factor: float | None
    virtual_bearings: dict[str, float]


@dataclass
class GunStats:
    visits: int = 0
    hits: int = 0
    rolling_score: float = 0.0


@dataclass
class GuessFactorProfile:
    visits: int = 0
    effective_weight: float = 0.0
    bins: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class TargetPosition:
    turn: int
    x: float
    y: float
    speed: float


@dataclass
class AimSolution:
    predicted_x: float
    predicted_y: float
    gun_bearing: float
    mode: str
    guess_factor: float | None
    features: tuple[float, ...]
    segment_key: tuple[int, ...]
    virtual_bearings: dict[str, float]
    previous_mode: str | None = None
    mode_changed: bool = False


@dataclass
class WaveVisit:
    target_id: int
    guess_factor: float
    samples: int
    traveled: float
    distance: float
    selected_gun: str
    virtual_scores: dict[str, float]
    gun_scores: dict[str, str]


@dataclass
class RollingKnnBuffer:
    max_samples: int
    max_samples_per_target: int
    _samples_by_target: dict[int, list[GunSample]] = field(default_factory=dict)
    _sample_count: int = 0

    @property
    def sample_count(self) -> int:
        return self._sample_count

    def add(self, sample: GunSample) -> None:
        samples = self._samples_by_target.setdefault(sample.target_id, [])
        samples.append(sample)
        self._sample_count += 1
        self._trim_target(sample.target_id)
        self._trim_global()

    def samples_for(self, target_id: int) -> list[GunSample]:
        return self._samples_by_target.get(target_id, [])

    def target_sample_count(self, target_id: int) -> int:
        return len(self._samples_by_target.get(target_id, []))

    def decayed_weight(self, sample: GunSample, current_turn: int, half_life: float) -> float:
        if half_life <= 0:
            return 1.0
        age = max(0, current_turn - sample.turn)
        return 0.5 ** (age / half_life)

    def effective_count(self, target_id: int, current_turn: int, half_life: float) -> float:
        return sum(self.decayed_weight(sample, current_turn, half_life) for sample in self.samples_for(target_id))

    def clear(self) -> None:
        self._samples_by_target.clear()
        self._sample_count = 0

    def _trim_target(self, target_id: int) -> None:
        samples = self._samples_by_target.get(target_id)
        if samples is None or len(samples) <= self.max_samples_per_target:
            return
        removed = len(samples) - self.max_samples_per_target
        del samples[:removed]
        self._sample_count -= removed

    def _trim_global(self) -> None:
        while self._sample_count > self.max_samples:
            oldest_target = None
            oldest_turn = None
            for target_id, samples in self._samples_by_target.items():
                if not samples:
                    continue
                if oldest_turn is None or samples[0].turn < oldest_turn:
                    oldest_target = target_id
                    oldest_turn = samples[0].turn
            if oldest_target is None:
                self._sample_count = 0
                return
            samples = self._samples_by_target[oldest_target]
            del samples[0]
            self._sample_count -= 1
            if not samples:
                del self._samples_by_target[oldest_target]


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
    _pending_wave: GunWave | None = None
    _knn_sequence: int = 0

    def __post_init__(self) -> None:
        self._knn_memory = RollingKnnBuffer(self.config.max_samples, self.config.max_samples_per_target)

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

    def make_wave(
        self,
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
            max_escape_angle=max_escape_angle_for_speed(bullet_speed),
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
        self._pending_wave = wave

    def record_pending_fire(self) -> GunWave | None:
        wave = self._pending_wave
        if wave is None:
            return None
        self._waves.append(wave)
        self._waves = self._waves[-self.config.max_waves :]
        self._pending_wave = None
        return wave

    def update_waves(self, bot: Bot, target: TargetSnapshot) -> list[WaveVisit]:
        visits: list[WaveVisit] = []
        remaining_waves: list[GunWave] = []
        for wave in self._waves:
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

        self._waves = remaining_waves[-self.config.max_waves :]
        return visits

    def score_summary(self, target_id: int, segment_key: tuple[int, ...] | None = None) -> dict[str, str]:
        summary: dict[str, str] = {}
        for (stats_target_id, mode), stats in self._stats.items():
            if stats_target_id != target_id:
                continue
            if segment_key is None:
                summary[mode] = f"{self._gun_score(target_id, mode):.3f}/{stats.visits}"
                continue

            segment_stats = self._segment_stats.get((target_id, mode, segment_key))
            segment_visits = segment_stats.visits if segment_stats is not None else 0
            summary[mode] = (
                f"{self._gun_score(target_id, mode, segment_key):.3f}/{stats.visits}"
                f"/s{segment_visits}"
            )
        return summary

    def target_confidence(self, target_id: int) -> tuple[float, int]:
        best_score = 0.0
        best_visits = 0
        for (stats_target_id, mode), stats in self._stats.items():
            if stats_target_id != target_id or mode not in self.config.selectable_modes:
                continue
            score = self._gun_score(target_id, mode)
            if score > best_score:
                best_score = score
                best_visits = stats.visits
        return best_score, best_visits

    def clear_round_state(self) -> None:
        self._waves.clear()
        self._pending_wave = None
        self._target_history.clear()

    def remove_target(self, target_id: int) -> None:
        self._waves = [wave for wave in self._waves if wave.target_id != target_id]
        self._active_modes.pop(target_id, None)
        self._target_history.pop(target_id, None)

    def _linear_aim_bearing(
        self,
        bot: Bot,
        target: TargetSnapshot,
        firepower: float,
        field_margin: float,
    ) -> float:
        predicted_x, predicted_y = predicted_position(bot, target, firepower, field_margin)
        return absolute_bearing_between(bot.x, bot.y, predicted_x, predicted_y)

    def _guess_factor_aim_bearing(
        self,
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
        current = self._active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        best_score = self._gun_score(target_id, current, segment_key)
        for mode in virtual_bearings:
            if mode not in self.config.selectable_modes:
                continue
            stats = self._stats.get((target_id, mode))
            if stats is None or stats.visits < self._min_switch_visits(mode):
                continue
            score = self._gun_score(target_id, mode, segment_key)
            if score < self._min_switch_score(mode):
                continue
            if score > best_score + self.config.switch_margin:
                best_mode = mode
                best_score = score

        previous = self._active_modes.get(target_id)
        self._active_modes[target_id] = best_mode
        return best_mode, previous, previous != best_mode

    def _min_switch_score(self, mode: str) -> float:
        if mode == "head_on":
            return self.config.head_on_min_switch_score
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_score
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_score
        return self.config.min_switch_score

    def _min_switch_visits(self, mode: str) -> int:
        if mode == "traditional_gf":
            return self.config.traditional_gf_min_switch_visits
        if mode == "anti_surfer":
            return self.config.anti_surfer_min_switch_visits
        return self.config.min_visits

    def _gun_features(
        self,
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
            key=lambda sample: feature_distance(features, sample.features)
            / max(
                0.25,
                self._knn_memory.decayed_weight(
                    sample,
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
        hit_angle = math.degrees(math.atan2(self.config.virtual_hit_radius, max(1.0, target_distance)))
        scores: dict[str, float] = {}
        for mode, aim_bearing in wave.virtual_bearings.items():
            error = abs(relative_bearing(actual_bearing, aim_bearing))
            score = max(0.0, 1.0 - error / max(hit_angle, 0.1))
            self._update_stats(self._stats.setdefault((wave.target_id, mode), GunStats()), score)
            self._update_stats(
                self._segment_stats.setdefault((wave.target_id, mode, wave.segment_key), GunStats()),
                score,
            )
            scores[mode] = round(score, 3)
        return scores

    def _gun_score(self, target_id: int, mode: str, segment_key: tuple[int, ...] | None = None) -> float:
        stats = self._stats.get((target_id, mode))
        if stats is None:
            return 0.0
        global_score = self._raw_gun_score(stats)
        if segment_key is None:
            return global_score

        segment_stats = self._segment_stats.get((target_id, mode, segment_key))
        if segment_stats is None or segment_stats.visits < self.config.segment_min_visits:
            return global_score

        segment_score = self._raw_gun_score(segment_stats)
        blend = clamp(
            (segment_stats.visits - self.config.segment_min_visits)
            / max(1, self.config.segment_full_weight_visits - self.config.segment_min_visits),
            0.0,
            1.0,
        )
        return global_score * (1.0 - blend) + segment_score * blend

    def _raw_gun_score(self, stats: GunStats) -> float:
        accuracy = stats.hits / max(1, stats.visits)
        return 0.7 * stats.rolling_score + 0.3 * accuracy

    def _update_stats(self, stats: GunStats, score: float) -> None:
        stats.visits += 1
        if score > 0:
            stats.hits += 1
        stats.rolling_score = (1.0 - self.config.score_alpha) * stats.rolling_score + self.config.score_alpha * score


def feature_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    weights = (2.0, 1.2, 1.8, 1.3, 0.8, 0.7, 0.9)
    return math.sqrt(sum(weight * (a - b) ** 2 for weight, a, b in zip(weights, left, right)))


def segment_features(features: tuple[float, ...]) -> tuple[int, ...]:
    distance, firepower, lateral_speed, advancing_speed, acceleration, velocity_change_age, wall_margin = features
    return (
        bucket(distance, 0.30, 0.55),
        bucket(firepower, 0.42, 0.62),
        bucket(lateral_speed, 0.25, 0.70),
        signed_bucket(advancing_speed, -0.25, 0.25),
        0 if abs(acceleration) >= 0.18 or velocity_change_age <= 0.15 else 1,
        bucket(wall_margin, 0.12, 0.25),
    )


def bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value < high:
        return 1
    return 2


def signed_bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value > high:
        return 2
    return 1


def guess_factor_to_bin(guess_factor: float, bins: int) -> int:
    return round((clamp(guess_factor, -1.0, 1.0) + 1.0) * (bins - 1) / 2.0)


def bin_to_guess_factor(index: int, bins: int) -> float:
    return -1.0 + 2.0 * index / (bins - 1)


def lateral_direction(target: TargetSnapshot, absolute_bearing: float) -> int:
    heading = math.radians(target.direction)
    bearing = math.radians(absolute_bearing)
    velocity_x = math.cos(heading) * target.speed
    velocity_y = math.sin(heading) * target.speed
    lateral_velocity = velocity_x * -math.sin(bearing) + velocity_y * math.cos(bearing)
    return 1 if lateral_velocity >= 0 else -1


def point_on_bearing(bot: Bot, aim_bearing: float, distance: float, field_margin: float) -> tuple[float, float]:
    aim_radians = math.radians(aim_bearing)
    predicted_x = bot.x + math.cos(aim_radians) * distance
    predicted_y = bot.y + math.sin(aim_radians) * distance
    return (
        clamp(predicted_x, field_margin, bot.arena_width - field_margin),
        clamp(predicted_y, field_margin, bot.arena_height - field_margin),
    )

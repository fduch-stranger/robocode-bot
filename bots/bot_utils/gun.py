import math
from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_utils.tank_math import TargetSnapshot, clamp, predicted_position


@dataclass(frozen=True)
class GunConfig:
    max_samples: int = 900
    max_waves: int = 80
    knn_min_samples: int = 90
    knn_blend_samples: int = 220
    knn_neighbors: int = 17
    wave_visit_margin: float = 18
    guess_factor_bins: int = 31
    guess_factor_bandwidth: float = 0.18
    default_mode: str = "linear"
    selectable_modes: frozenset[str] = frozenset({"linear", "dynamic_cluster"})
    min_visits: int = 160
    switch_margin: float = 0.14
    min_switch_score: float = 0.34
    head_on_min_switch_score: float = 0.45
    score_alpha: float = 0.12
    virtual_hit_radius: float = 18
    max_target_history: int = 80
    displacement_min_samples: int = 4
    displacement_time_tolerance: int = 2


@dataclass(frozen=True)
class TargetMotion:
    acceleration: float = 0.0
    velocity_change_age: int = 0


@dataclass
class GunSample:
    target_id: int
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
    lateral_direction: int
    features: tuple[float, ...]
    aim_mode: str
    aim_guess_factor: float | None
    virtual_bearings: dict[str, float]


@dataclass
class GunStats:
    visits: int = 0
    hits: int = 0
    rolling_score: float = 0.0


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
class VirtualGunSystem:
    config: GunConfig = field(default_factory=GunConfig)
    _samples: list[GunSample] = field(default_factory=list)
    _waves: list[GunWave] = field(default_factory=list)
    _stats: dict[tuple[int, str], GunStats] = field(default_factory=dict)
    _active_modes: dict[int, str] = field(default_factory=dict)
    _target_history: dict[int, list[TargetPosition]] = field(default_factory=dict)
    _pending_wave: GunWave | None = None

    @property
    def sample_count(self) -> int:
        return len(self._samples)

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
    ) -> AimSolution:
        features = self._gun_features(bot, target, distance, firepower, motion)
        absolute_bearing = absolute_bearing_between(bot.x, bot.y, target.x, target.y)
        virtual_bearings = {
            "head_on": absolute_bearing,
            "linear": self._linear_aim_bearing(bot, target, firepower, field_margin),
        }
        displacement_bearing = self._displacement_aim_bearing(bot, target, distance, firepower, field_margin)
        if displacement_bearing is not None:
            virtual_bearings["displacement"] = displacement_bearing

        cluster_guess_factor = self._knn_guess_factor(target.bot_id, features)
        if cluster_guess_factor is not None:
            virtual_bearings["dynamic_cluster"] = self._guess_factor_aim_bearing(
                bot,
                target,
                firepower,
                cluster_guess_factor,
            )

        mode, previous_mode, mode_changed = self._select_aim_mode(target.bot_id, virtual_bearings)
        aim_bearing = virtual_bearings[mode]
        predicted_x, predicted_y = point_on_bearing(bot, aim_bearing, distance, field_margin)
        return AimSolution(
            predicted_x=predicted_x,
            predicted_y=predicted_y,
            gun_bearing=relative_bearing(aim_bearing, bot.gun_direction),
            mode=mode,
            guess_factor=cluster_guess_factor if mode == "dynamic_cluster" else None,
            features=features,
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
        return GunWave(
            source_x=bot.x,
            source_y=bot.y,
            fire_turn=bot.turn_number,
            fire_bearing=fire_bearing,
            target_id=target.bot_id,
            bullet_power=firepower,
            bullet_speed=bullet_speed,
            max_escape_angle=max_escape_angle_for_speed(bullet_speed),
            lateral_direction=lateral_direction(target, fire_bearing),
            features=aim.features,
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
            guess_factor = clamp((bearing_offset / wave.max_escape_angle) * wave.lateral_direction, -1.0, 1.0)
            virtual_scores = self._score_virtual_guns(wave, actual_bearing, target_distance)
            self._samples.append(GunSample(wave.target_id, wave.features, guess_factor))
            if len(self._samples) > self.config.max_samples:
                del self._samples[: len(self._samples) - self.config.max_samples]
            visits.append(
                WaveVisit(
                    target_id=target.bot_id,
                    guess_factor=guess_factor,
                    samples=len(self._samples),
                    traveled=traveled,
                    distance=target_distance,
                    selected_gun=wave.aim_mode,
                    virtual_scores=virtual_scores,
                    gun_scores=self.score_summary(target.bot_id),
                )
            )

        self._waves = remaining_waves[-self.config.max_waves :]
        return visits

    def score_summary(self, target_id: int) -> dict[str, str]:
        summary: dict[str, str] = {}
        for (stats_target_id, mode), stats in self._stats.items():
            if stats_target_id != target_id:
                continue
            summary[mode] = f"{self._gun_score(target_id, mode):.3f}/{stats.visits}"
        return summary

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
        max_escape_angle = max_escape_angle_for_speed(bullet_speed)
        return absolute_bearing + guess_factor * lateral_direction(target, absolute_bearing) * max_escape_angle

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

    def _select_aim_mode(self, target_id: int, virtual_bearings: dict[str, float]) -> tuple[str, str | None, bool]:
        current = self._active_modes.get(target_id, self.config.default_mode)
        if current not in self.config.selectable_modes or current not in virtual_bearings:
            current = self.config.default_mode if self.config.default_mode in virtual_bearings else next(iter(virtual_bearings))

        best_mode = current
        best_score = self._gun_score(target_id, current)
        for mode in virtual_bearings:
            if mode not in self.config.selectable_modes:
                continue
            stats = self._stats.get((target_id, mode))
            if stats is None or stats.visits < self.config.min_visits:
                continue
            score = self._gun_score(target_id, mode)
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
        return self.config.min_switch_score

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
        samples = [sample for sample in self._samples if sample.target_id == target_id]
        sample_count = len(samples)
        if sample_count < self.config.knn_min_samples:
            return None

        neighbors = sorted(
            samples,
            key=lambda sample: feature_distance(features, sample.features),
        )[: min(self.config.knn_neighbors, sample_count)]
        weighted_neighbors: list[tuple[GunSample, float]] = []
        for sample in neighbors:
            distance = feature_distance(features, sample.features)
            weight = 1.0 / (0.05 + distance)
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
            stats = self._stats.setdefault((wave.target_id, mode), GunStats())
            stats.visits += 1
            if score > 0:
                stats.hits += 1
            stats.rolling_score = (1.0 - self.config.score_alpha) * stats.rolling_score + self.config.score_alpha * score
            scores[mode] = round(score, 3)
        return scores

    def _gun_score(self, target_id: int, mode: str) -> float:
        stats = self._stats.get((target_id, mode))
        if stats is None:
            return 0.0
        accuracy = stats.hits / max(1, stats.visits)
        return 0.7 * stats.rolling_score + 0.3 * accuracy


def bullet_speed_for_power(firepower: float) -> float:
    return 20 - 3 * firepower


def max_escape_angle_for_speed(bullet_speed: float) -> float:
    return math.degrees(math.asin(min(1, 8 / bullet_speed)))


def feature_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    weights = (2.0, 1.2, 1.8, 1.3, 0.8, 0.7, 0.9)
    return math.sqrt(sum(weight * (a - b) ** 2 for weight, a, b in zip(weights, left, right)))


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


def absolute_bearing_between(source_x: float, source_y: float, target_x: float, target_y: float) -> float:
    return math.degrees(math.atan2(target_y - source_y, target_x - source_x))


def relative_bearing(angle: float, reference: float) -> float:
    return ((angle - reference + 180) % 360) - 180

import math
from dataclasses import dataclass, field

from robocode_tank_royale.bot_api import Bot

from bot_core.physics import MAX_ROBOT_SPEED, RobotMovementState, bullet_speed_for_power, predict_robot_movement
from bot_core.tank_math import TargetSnapshot, clamp, drive_command_to_destination
from bot_core.wave_math import guess_factor_from_offset, wall_limited_escape_angle_from_state


@dataclass(frozen=True)
class MovementFlatteningConfig:
    min_distance: float = 150.0
    max_distance: float = 700.0
    near_distance: float = 280.0
    mid_distance: float = 480.0
    bin_count: int = 31
    switch_margin: float = 1.5
    switch_cooldown: int = 12
    lookahead_ticks: int = 14
    surf_max_ticks: int = 80
    surf_intercept_margin: float = 18.0
    wall_stick: float = 140.0
    wall_smoothing_degrees: float = 12.0
    wall_smoothing_attempts: int = 18
    unvisited_bin_danger: float = 0.08
    profile_decay_after: float = 220.0
    bullet_hit_visit_weight: float = 3.0
    bullet_hit_wave_tolerance: float = 55.0
    bullet_shadow_enabled: bool = False
    bullet_shadow_danger_multiplier: float = 0.45
    bullet_shadow_radius_margin: float = 14.0
    bullet_shadow_bin_radius: int = 0
    bullet_shadow_max_ticks: int = 80
    goto_candidate_distances: tuple[float, ...] = (120.0, 180.0, 260.0)
    goto_candidate_angle_offsets: tuple[float, ...] = (-110.0, -80.0, -50.0, -20.0, 20.0, 50.0, 80.0, 110.0)
    goto_min_target_distance: float = 340.0
    goto_max_target_distance: float = 720.0
    goto_preferred_target_distance: float = 560.0
    goto_wall_weight: float = 2.2
    goto_target_distance_weight: float = 0.000035
    goto_close_enemy_weight: float = 1.4
    goto_travel_weight: float = 0.0008
    goto_wave_kind_expected_multiplier: float = 0.85
    goto_use_expected_waves: bool = False
    goto_expected_wave_min_confidence: float = 0.58
    stats_buffer_enabled: bool = True
    stats_buffer_weight: float = 0.28
    stats_buffer_decay: float = 0.99
    stats_buffer_min_samples: float = 6.0
    stats_buffer_max_effective_samples: float = 48.0


@dataclass(frozen=True)
class FlatteningDecision:
    direction: int
    changed: bool
    reason: str
    bucket: int
    current_count: float
    alternative_count: float


@dataclass(frozen=True)
class MovementCommand:
    mode: str
    turn: float
    speed: float
    strafe_offset: float = 0.0
    telemetry_fields: dict[str, object] = field(default_factory=dict)
    direction_update: int | None = None

    @classmethod
    def strafe(
        cls,
        mode: str,
        body_bearing: float,
        strafe_offset: float,
        direction: int,
        speed: float,
        **telemetry_fields: object,
    ) -> "MovementCommand":
        return cls(
            mode=mode,
            turn=body_bearing + strafe_offset * direction,
            speed=speed,
            strafe_offset=strafe_offset,
            telemetry_fields=telemetry_fields,
        )

    @classmethod
    def drive_to_destination(
        cls,
        bot: Bot,
        x: float,
        y: float,
        speed: float,
        mode: str,
        strafe_offset: float = 0.0,
        direction_update: int | None = None,
        **telemetry_fields: object,
    ) -> "MovementCommand":
        turn, target_speed = drive_command_to_destination(bot, x, y, speed)
        return cls(
            mode=mode,
            turn=turn,
            speed=target_speed,
            strafe_offset=strafe_offset,
            telemetry_fields=telemetry_fields,
            direction_update=direction_update,
        )

    def apply(self, bot: Bot) -> None:
        bot.target_speed = self.speed
        bot.set_turn_left(self.turn)


@dataclass(frozen=True)
class MovementProfileVisit:
    target_id: int
    guess_factor: float
    bin_index: int
    bucket: int
    visits: float
    wave_age: int
    ensemble_danger: float = 0.0
    ensemble_samples: float = 0.0


@dataclass(frozen=True)
class GoToSurfDecision:
    x: float
    y: float
    danger: float
    candidates: int
    wave_kind: str
    hit_guess_factor: float
    hit_bin: int
    hit_turn: int
    direction: int
    profile_danger: float
    ensemble_danger: float
    ensemble_samples: float
    ensemble_weight: float
    wall_risk: float
    distance_risk: float
    travel_risk: float


@dataclass(frozen=True)
class MovementWaveFeatures:
    lateral_velocity: float = 0.0
    advancing_velocity: float = 0.0
    bullet_flight_time: float = 0.0
    acceleration: float = 0.0
    direction_change_age: int = 0
    decel_age: int = 0
    wall_distance: float = 0.0


@dataclass(frozen=True)
class MovementDangerBreakdown:
    profile_danger: float
    ensemble_danger: float
    ensemble_samples: float
    ensemble_weight: float
    total_danger: float


@dataclass
class MovementWave:
    target_id: int
    source_x: float
    source_y: float
    direct_bearing: float
    lateral_direction: int
    bullet_speed: float
    max_escape_angle_positive: float
    max_escape_angle_negative: float
    fired_turn: int
    distance_bucket: int
    kind: str = "confirmed"
    expected_confidence: float = 1.0
    features: MovementWaveFeatures = MovementWaveFeatures()


@dataclass(frozen=True)
class ShadowBullet:
    bullet_id: str
    source_x: float
    source_y: float
    direction: float
    bullet_speed: float
    fired_turn: int


@dataclass(frozen=True)
class MovementStatsBufferSpec:
    name: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class MovementStatsBufferDanger:
    name: str
    danger: float
    samples: float


class MovementStatsBuffer:
    def __init__(self, spec: MovementStatsBufferSpec, config: MovementFlatteningConfig) -> None:
        self.spec = spec
        self.config = config
        self._visits: dict[tuple[int, tuple[int, ...], int], float] = {}
        self._samples: dict[tuple[int, tuple[int, ...]], float] = {}

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> None:
        segment = self._segment(wave)
        self._decay_segment(wave.target_id, segment)
        key = (wave.target_id, segment, bin_index)
        self._visits[key] = self._visits.get(key, 0.0) + weight
        sample_key = (wave.target_id, segment)
        self._samples[sample_key] = self._samples.get(sample_key, 0.0) + weight

    def danger(self, wave: MovementWave, bin_index: int) -> MovementStatsBufferDanger:
        segment = self._segment(wave)
        score = 0.0
        for offset, smooth_weight in ((0, 1.0), (-1, 0.55), (1, 0.55), (-2, 0.25), (2, 0.25)):
            neighbor = bin_index + offset
            if 0 <= neighbor < self.config.bin_count:
                score += self._visits.get((wave.target_id, segment, neighbor), 0.0) * smooth_weight
        samples = self._samples.get((wave.target_id, segment), 0.0)
        return MovementStatsBufferDanger(self.spec.name, score, samples)

    def remove_target(self, target_id: int) -> None:
        self._visits = {key: value for key, value in self._visits.items() if key[0] != target_id}
        self._samples = {key: value for key, value in self._samples.items() if key[0] != target_id}

    def _decay_segment(self, target_id: int, segment: tuple[int, ...]) -> None:
        decay = self.config.stats_buffer_decay
        sample_key = (target_id, segment)
        total = 0.0
        for key in list(self._visits):
            if key[0] == target_id and key[1] == segment:
                decayed = self._visits[key] * decay
                if decayed < 0.001:
                    del self._visits[key]
                else:
                    self._visits[key] = decayed
                    total += decayed
        if total > 0.0:
            self._samples[sample_key] = total
        else:
            self._samples.pop(sample_key, None)

    def _segment(self, wave: MovementWave) -> tuple[int, ...]:
        return tuple(self._bucket(wave, dimension) for dimension in self.spec.dimensions)

    def _bucket(self, wave: MovementWave, dimension: str) -> int:
        features = wave.features
        if dimension == "distance":
            return wave.distance_bucket
        if dimension == "lateral":
            return round(clamp((features.lateral_velocity + 8.0) / 4.0, 0.0, 4.0))
        if dimension == "advancing":
            return round(clamp((features.advancing_velocity + 8.0) / 4.0, 0.0, 4.0))
        if dimension == "flight":
            if features.bullet_flight_time < 18:
                return 0
            if features.bullet_flight_time < 32:
                return 1
            return 2
        if dimension == "accel":
            if features.acceleration < -0.4:
                return 0
            if features.acceleration > 0.4:
                return 2
            return 1
        if dimension == "dir_age":
            if features.direction_change_age < 8:
                return 0
            if features.direction_change_age < 28:
                return 1
            return 2
        if dimension == "decel_age":
            if features.decel_age < 8:
                return 0
            if features.decel_age < 28:
                return 1
            return 2
        if dimension == "wall":
            if features.wall_distance < 90:
                return 0
            if features.wall_distance < 180:
                return 1
            return 2
        return 0


class MovementStatsBufferSet:
    SPECS: tuple[MovementStatsBufferSpec, ...] = (
        MovementStatsBufferSpec("distance", ("distance",)),
        MovementStatsBufferSpec("lateral", ("lateral",)),
        MovementStatsBufferSpec("advancing", ("advancing",)),
        MovementStatsBufferSpec("accel", ("accel",)),
        MovementStatsBufferSpec("wall", ("wall",)),
        MovementStatsBufferSpec("flight", ("flight",)),
        MovementStatsBufferSpec("distance_lateral", ("distance", "lateral")),
        MovementStatsBufferSpec("distance_wall", ("distance", "wall")),
        MovementStatsBufferSpec("distance_flight", ("distance", "flight")),
        MovementStatsBufferSpec("lateral_accel", ("lateral", "accel")),
        MovementStatsBufferSpec("lateral_wall", ("lateral", "wall")),
        MovementStatsBufferSpec("distance_decel", ("distance", "decel_age")),
    )

    def __init__(self, config: MovementFlatteningConfig) -> None:
        self.config = config
        self._buffers = [MovementStatsBuffer(spec, config) for spec in self.SPECS]

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> None:
        if not self.config.stats_buffer_enabled:
            return
        for buffer in self._buffers:
            buffer.record(wave, bin_index, weight)

    def danger(self, wave: MovementWave, bin_index: int) -> MovementStatsBufferDanger:
        if not self.config.stats_buffer_enabled:
            return MovementStatsBufferDanger("disabled", 0.0, 0.0)
        dangers = [buffer.danger(wave, bin_index) for buffer in self._buffers]
        if not dangers:
            return MovementStatsBufferDanger("empty", 0.0, 0.0)
        weighted_danger = 0.0
        total_weight = 0.0
        total_samples = 0.0
        top = max(dangers, key=lambda item: item.danger)
        for danger in dangers:
            confidence = clamp(
                danger.samples / max(1.0, self.config.stats_buffer_min_samples),
                0.0,
                1.0,
            )
            if confidence <= 0.0:
                continue
            weighted_danger += danger.danger * confidence
            total_weight += confidence
            total_samples += danger.samples
        if total_weight <= 0.0:
            return MovementStatsBufferDanger(top.name, 0.0, 0.0)
        return MovementStatsBufferDanger(top.name, weighted_danger / total_weight, total_samples / len(dangers))

    def remove_target(self, target_id: int) -> None:
        for buffer in self._buffers:
            buffer.remove_target(target_id)


class MovementWaveStore:
    def __init__(self) -> None:
        self.waves: list[MovementWave] = []

    def add(self, wave: MovementWave) -> None:
        self.waves.append(wave)

    def replace(self, waves: list[MovementWave]) -> None:
        self.waves[:] = waves

    def remove(self, wave: MovementWave) -> None:
        self.replace([candidate for candidate in self.waves if candidate is not wave])

    def remove_target(self, target_id: int) -> None:
        self.replace([wave for wave in self.waves if wave.target_id != target_id])

    def remove_recent_expected(self, target_id: int, turn_number: int, max_age: int) -> None:
        self.replace(
            [
                wave
                for wave in self.waves
                if not (
                    wave.target_id == target_id
                    and wave.kind == "expected"
                    and 0 <= turn_number - wave.fired_turn <= max_age
                )
            ]
        )

    def for_target(self, target_id: int) -> list[MovementWave]:
        return [wave for wave in self.waves if wave.target_id == target_id]

    def matching_target_speed(self, target_id: int, bullet_speed: float, tolerance: float) -> list[MovementWave]:
        return [
            wave
            for wave in self.waves
            if wave.target_id == target_id and abs(wave.bullet_speed - bullet_speed) <= tolerance
        ]

    def clear_round_state(self) -> None:
        self.waves.clear()


class MovementProfile:
    def __init__(self, config: MovementFlatteningConfig) -> None:
        self.config = config
        self.profile: dict[tuple[int, int, int], float] = {}
        self.stats_buffers = MovementStatsBufferSet(config)

    def record(self, wave: MovementWave, bin_index: int, weight: float) -> float:
        key = (wave.target_id, wave.distance_bucket, bin_index)
        self.profile[key] = self.profile.get(key, 0.0) + weight
        self.stats_buffers.record(wave, bin_index, weight)
        self._decay_if_needed(wave.target_id)
        return self.profile[key]

    def smoothed_count(self, target_id: int, bucket: int, bin_index: int) -> float:
        score = 0.0
        for offset, weight in ((0, 1.0), (-1, 0.55), (1, 0.55), (-2, 0.25), (2, 0.25)):
            neighbor = bin_index + offset
            if 0 <= neighbor < self.config.bin_count:
                score += self.profile.get((target_id, bucket, neighbor), 0.0) * weight
        return score

    def remove_target(self, target_id: int) -> None:
        for key in list(self.profile):
            if key[0] == target_id:
                del self.profile[key]
        self.stats_buffers.remove_target(target_id)

    def _decay_if_needed(self, target_id: int) -> None:
        total = sum(value for key, value in self.profile.items() if key[0] == target_id)
        if total <= self.config.profile_decay_after:
            return
        for key in list(self.profile):
            if key[0] == target_id:
                self.profile[key] *= 0.5


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


@dataclass(frozen=True)
class MinimumRiskConfig:
    candidate_distances: tuple[float, ...] = (95.0, 145.0, 205.0)
    candidate_angle_step: int = 22
    field_margin: float = 58.0
    preferred_target_distance: float = 290.0
    max_target_distance: float = 520.0
    close_enemy_distance: float = 145.0
    travel_weight: float = 0.0018
    wall_weight: float = 95.0
    enemy_weight: float = 16500.0
    close_enemy_weight: float = 14.0
    target_distance_weight: float = 0.0009
    radial_weight: float = 0.35
    threat_lateral_weight: float = 0.0
    threat_distance_weight: float = 0.0
    recent_destination_weight: float = 2.4
    recent_destination_radius: float = 130.0
    recent_destination_count: int = 12
    destination_commit_ticks: int = 16
    destination_reached_radius: float = 42.0
    destination_switch_risk_ratio: float = 0.82


@dataclass(frozen=True)
class MinimumRiskDecision:
    x: float
    y: float
    risk: float
    candidates: int
    nearest_enemy_id: int | None
    nearest_enemy_distance: float
    reused: bool = False
    age: int = 0


class MinimumRiskMovement:
    def __init__(self, config: MinimumRiskConfig | None = None) -> None:
        self.config = config or MinimumRiskConfig()
        self._recent_destinations: list[tuple[float, float]] = []
        self._active_destination: tuple[float, float] | None = None
        self._active_selected_turn = 0

    def choose(
        self,
        bot: Bot,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        threat_target: TargetSnapshot | None = None,
        dodge_direction: int = 0,
    ) -> MinimumRiskDecision | None:
        if len(targets) < 2:
            self._active_destination = None
            return None

        candidates = self._candidate_points(bot)
        best: MinimumRiskDecision | None = None
        for x, y in candidates:
            risk, nearest_id, nearest_distance = self._risk(
                bot,
                x,
                y,
                targets,
                focus_target,
                threat_target,
                dodge_direction,
            )
            decision = MinimumRiskDecision(
                x=x,
                y=y,
                risk=risk,
                candidates=0,
                nearest_enemy_id=nearest_id,
                nearest_enemy_distance=nearest_distance,
            )
            if best is None or decision.risk < best.risk:
                best = decision

        if best is None:
            return None

        active = self._active_decision(
            bot,
            targets,
            focus_target,
            len(candidates),
            threat_target,
            dodge_direction,
        )
        if active is not None and best.risk >= active.risk * self.config.destination_switch_risk_ratio:
            return active

        selected = MinimumRiskDecision(
            x=best.x,
            y=best.y,
            risk=best.risk,
            candidates=len(candidates),
            nearest_enemy_id=best.nearest_enemy_id,
            nearest_enemy_distance=best.nearest_enemy_distance,
        )
        self._active_destination = (selected.x, selected.y)
        self._active_selected_turn = getattr(bot, "turn_number", 0)
        self._remember_destination(selected.x, selected.y)
        return selected

    def _active_decision(
        self,
        bot: Bot,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        candidate_count: int,
        threat_target: TargetSnapshot | None,
        dodge_direction: int,
    ) -> MinimumRiskDecision | None:
        if self._active_destination is None:
            return None

        x, y = self._active_destination
        if not self._in_field(bot, x, y):
            return None

        turn_number = getattr(bot, "turn_number", 0)
        age = turn_number - self._active_selected_turn
        if age > self.config.destination_commit_ticks:
            return None

        if math.hypot(x - bot.x, y - bot.y) <= self.config.destination_reached_radius:
            return None

        risk, nearest_id, nearest_distance = self._risk(
            bot,
            x,
            y,
            targets,
            focus_target,
            threat_target,
            dodge_direction,
        )
        return MinimumRiskDecision(
            x=x,
            y=y,
            risk=risk,
            candidates=candidate_count,
            nearest_enemy_id=nearest_id,
            nearest_enemy_distance=nearest_distance,
            reused=True,
            age=max(0, age),
        )

    def _remember_destination(self, x: float, y: float) -> None:
        self._recent_destinations.append((x, y))
        if len(self._recent_destinations) > self.config.recent_destination_count:
            del self._recent_destinations[: len(self._recent_destinations) - self.config.recent_destination_count]

    def clear_round_state(self) -> None:
        self._recent_destinations.clear()
        self._active_destination = None
        self._active_selected_turn = 0

    def _candidate_points(self, bot: Bot) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for distance in self.config.candidate_distances:
            for angle in range(0, 360, self.config.candidate_angle_step):
                x = bot.x + math.cos(math.radians(angle)) * distance
                y = bot.y + math.sin(math.radians(angle)) * distance
                if self._in_field(bot, x, y):
                    points.append((x, y))
        return points

    def _risk(
        self,
        bot: Bot,
        x: float,
        y: float,
        targets: list[TargetSnapshot],
        focus_target: TargetSnapshot,
        threat_target: TargetSnapshot | None,
        dodge_direction: int,
    ) -> tuple[float, int | None, float]:
        nearest_id: int | None = None
        nearest_distance = float("inf")
        risk = math.hypot(x - bot.x, y - bot.y) * self.config.travel_weight
        risk += self._wall_risk(bot, x, y)
        risk += self._target_distance_risk(x, y, focus_target)
        risk += self._recent_destination_risk(x, y)

        for target in targets:
            distance = max(1.0, math.hypot(x - target.x, y - target.y))
            if distance < nearest_distance:
                nearest_id = target.bot_id
                nearest_distance = distance

            energy_weight = 1.0 + target.energy / 100.0
            risk += self.config.enemy_weight * energy_weight / (distance * distance)
            if distance < self.config.close_enemy_distance:
                closeness = (self.config.close_enemy_distance - distance) / self.config.close_enemy_distance
                risk += closeness * closeness * self.config.close_enemy_weight * energy_weight

            current_bearing = math.atan2(bot.y - target.y, bot.x - target.x)
            candidate_bearing = math.atan2(y - target.y, x - target.x)
            lateral = abs(math.sin(candidate_bearing - current_bearing))
            risk += (1.0 - lateral) * self.config.radial_weight * energy_weight

            if threat_target is not None and target.bot_id == threat_target.bot_id:
                lateral_delta = math.sin(candidate_bearing - current_bearing)
                threat_lateral = abs(lateral_delta)
                risk += (1.0 - threat_lateral) * self.config.threat_lateral_weight * energy_weight
                risk += self.config.threat_distance_weight * energy_weight / (distance * distance)
                if dodge_direction and lateral_delta * dodge_direction < 0:
                    risk += self.config.threat_lateral_weight * 0.35 * energy_weight

        return risk, nearest_id, nearest_distance

    def _target_distance_risk(self, x: float, y: float, focus_target: TargetSnapshot) -> float:
        distance = math.hypot(x - focus_target.x, y - focus_target.y)
        if distance < self.config.preferred_target_distance:
            error = self.config.preferred_target_distance - distance
        elif distance > self.config.max_target_distance:
            error = distance - self.config.max_target_distance
        else:
            return 0.0
        return error * error * self.config.target_distance_weight

    def _wall_risk(self, bot: Bot, x: float, y: float) -> float:
        margin = min(x, bot.arena_width - x, y, bot.arena_height - y)
        if margin <= self.config.field_margin:
            return self.config.wall_weight
        return self.config.wall_weight / max(1.0, margin)

    def _recent_destination_risk(self, x: float, y: float) -> float:
        risk = 0.0
        for recent_x, recent_y in self._recent_destinations:
            distance = math.hypot(x - recent_x, y - recent_y)
            if distance < self.config.recent_destination_radius:
                closeness = (self.config.recent_destination_radius - distance) / self.config.recent_destination_radius
                risk += closeness * self.config.recent_destination_weight
        return risk

    def _in_field(self, bot: Bot, x: float, y: float) -> bool:
        margin = self.config.field_margin
        return margin <= x <= bot.arena_width - margin and margin <= y <= bot.arena_height - margin


class MovementFlattener:
    def __init__(self, config: MovementFlatteningConfig | None = None) -> None:
        self.config = config or MovementFlatteningConfig()
        self._wave_store = MovementWaveStore()
        self._profile_store = MovementProfile(self.config)
        self._danger_model = MovementDangerModel(self.config, self._profile_store)
        self._surfing = SurfingPlanner(self.config, self._wave_store)
        self._profile = self._profile_store.profile
        self._stats_buffers = self._profile_store.stats_buffers
        self._waves = self._wave_store.waves
        self._shadow_bullets: list[ShadowBullet] = []
        self._last_switch_turn: dict[int, int] = {}

    @property
    def shadow_bullet_count(self) -> int:
        return len(self._shadow_bullets)

    def record_shadow_bullet(
        self,
        bot: Bot,
        bullet_id: object,
        fire_power: float,
        direction: float,
    ) -> None:
        if not self.config.bullet_shadow_enabled:
            return
        self._shadow_bullets.append(
            ShadowBullet(
                bullet_id=str(bullet_id),
                source_x=bot.x,
                source_y=bot.y,
                direction=direction,
                bullet_speed=bullet_speed_for_power(fire_power),
                fired_turn=bot.turn_number,
            )
        )

    def remove_shadow_bullet(self, bullet_id: object) -> None:
        key = str(bullet_id)
        self._shadow_bullets = [bullet for bullet in self._shadow_bullets if bullet.bullet_id != key]

    def record_enemy_fire(
        self,
        bot: Bot,
        target: TargetSnapshot,
        fire_power: float,
        wave_kind: str = "confirmed",
        expected_confidence: float = 1.0,
        acceleration: float = 0.0,
        direction_change_age: int = 0,
        decel_age: int = 0,
    ) -> MovementWave | None:
        distance = math.hypot(bot.x - target.x, bot.y - target.y)
        if not (self.config.min_distance <= distance <= self.config.max_distance):
            return None

        if wave_kind == "confirmed":
            self._wave_store.remove_recent_expected(target.bot_id, bot.turn_number, 4)

        bullet_speed = bullet_speed_for_power(fire_power)
        wave_lateral_direction = self._lateral_direction(bot, target) or 1
        features = self._wave_features(
            bot,
            target,
            distance,
            bullet_speed,
            acceleration=acceleration,
            direction_change_age=direction_change_age,
            decel_age=decel_age,
        )
        wave = MovementWave(
            target_id=target.bot_id,
            source_x=target.x,
            source_y=target.y,
            direct_bearing=self._absolute_bearing(target.x, target.y, bot.x, bot.y),
            lateral_direction=wave_lateral_direction,
            bullet_speed=bullet_speed,
            max_escape_angle_positive=wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                wave_lateral_direction,
            ),
            max_escape_angle_negative=wall_limited_escape_angle_from_state(
                bot.arena_width,
                bot.arena_height,
                target.x,
                target.y,
                bot.x,
                bot.y,
                bullet_speed,
                -wave_lateral_direction,
            ),
            fired_turn=bot.turn_number,
            distance_bucket=self._distance_bucket(distance),
            kind=wave_kind,
            expected_confidence=clamp(expected_confidence, 0.0, 1.0),
            features=features,
        )
        self._wave_store.add(wave)
        return wave

    def update(self, bot: Bot) -> list[MovementProfileVisit]:
        self._expire_shadow_bullets(bot)
        visits: list[MovementProfileVisit] = []
        remaining_waves: list[MovementWave] = []
        for wave in self._wave_store.waves:
            wave_age = bot.turn_number - wave.fired_turn
            if wave_age < 1:
                remaining_waves.append(wave)
                continue

            wave_radius = wave.bullet_speed * wave_age
            distance = math.hypot(bot.x - wave.source_x, bot.y - wave.source_y)
            if wave_radius < distance - 18:
                remaining_waves.append(wave)
                continue

            guess_factor = self._guess_factor(wave, bot.x, bot.y)
            bin_index = self._bin_index(guess_factor)
            profile_visits = self._record_visit(wave, bin_index, 1.0)
            danger = self._danger_breakdown(wave, bin_index)
            visits.append(
                MovementProfileVisit(
                    target_id=wave.target_id,
                    guess_factor=guess_factor,
                    bin_index=bin_index,
                    bucket=wave.distance_bucket,
                    visits=profile_visits,
                    wave_age=wave_age,
                    ensemble_danger=danger.ensemble_danger,
                    ensemble_samples=danger.ensemble_samples,
                )
            )
        self._wave_store.replace(remaining_waves)
        return visits

    def record_bullet_hit(self, bot: Bot, target_id: int, bullet_power: float) -> MovementProfileVisit | None:
        if not self._wave_store.waves:
            return None

        bullet_speed = bullet_speed_for_power(bullet_power)
        candidates = self._wave_store.matching_target_speed(target_id, bullet_speed, 1.2)
        if not candidates:
            return None

        def hit_error(wave: MovementWave) -> float:
            wave_age = max(1, bot.turn_number - wave.fired_turn)
            wave_radius = wave.bullet_speed * wave_age
            distance = math.hypot(bot.x - wave.source_x, bot.y - wave.source_y)
            return abs(distance - wave_radius)

        wave = min(candidates, key=hit_error)
        if hit_error(wave) > self.config.bullet_hit_wave_tolerance:
            return None

        guess_factor = self._guess_factor(wave, bot.x, bot.y)
        bin_index = self._bin_index(guess_factor)
        visits = self._record_visit(wave, bin_index, self.config.bullet_hit_visit_weight)
        danger = self._danger_breakdown(wave, bin_index)
        self._wave_store.remove(wave)
        return MovementProfileVisit(
            target_id=wave.target_id,
            guess_factor=guess_factor,
            bin_index=bin_index,
            bucket=wave.distance_bucket,
            visits=visits,
            wave_age=max(1, bot.turn_number - wave.fired_turn),
            ensemble_danger=danger.ensemble_danger,
            ensemble_samples=danger.ensemble_samples,
        )

    def choose_direction(
        self,
        bot: Bot,
        target: TargetSnapshot,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        target_id: int,
        distance: float,
        current_direction: int,
        turn_number: int,
        allow_switch: bool,
        use_surfing: bool = True,
    ) -> FlatteningDecision:
        bucket = self._distance_bucket(distance)
        if not allow_switch:
            return self._decision(current_direction, False, "locked", target_id, bucket, current_direction)

        if not (self.config.min_distance <= distance <= self.config.max_distance):
            return self._decision(current_direction, False, "distance", target_id, bucket, current_direction)

        if turn_number - self._last_switch_turn.get(target_id, -1000) < self.config.switch_cooldown:
            return self._decision(current_direction, False, "cooldown", target_id, bucket, current_direction)

        wave = self._surf_wave(bot, target_id) if use_surfing else self._best_wave(target_id)
        if wave is None:
            return self._decision(current_direction, False, "no_wave", target_id, bucket, current_direction)

        alternative = -1 if current_direction >= 0 else 1
        current_count = self._candidate_score(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            current_direction,
            use_surfing,
        )
        alternative_count = self._candidate_score(
            bot,
            wave,
            body_bearing,
            strafe_offset,
            move_speed,
            field_margin,
            alternative,
            use_surfing,
        )
        margin = self.config.switch_margin
        if use_surfing and min(current_count, alternative_count) < 1.0:
            margin *= 0.35
        if alternative_count + margin >= current_count:
            return FlatteningDecision(
                direction=current_direction,
                changed=False,
                reason="balanced",
                bucket=bucket,
                current_count=current_count,
                alternative_count=alternative_count,
            )

        self._last_switch_turn[target_id] = turn_number
        return FlatteningDecision(
            direction=alternative,
            changed=True,
            reason="flatten",
            bucket=bucket,
            current_count=current_count,
            alternative_count=alternative_count,
        )

    def choose_go_to_surf_destination(
        self,
        bot: Bot,
        target: TargetSnapshot,
        max_speed: float,
        field_margin: float,
    ) -> GoToSurfDecision | None:
        wave = self._surf_wave(bot, target.bot_id)
        if wave is None:
            return None
        if wave.kind == "expected":
            if not self.config.goto_use_expected_waves:
                return None
            if wave.expected_confidence < self.config.goto_expected_wave_min_confidence:
                return None

        candidates = self._go_to_candidate_points(bot, target, field_margin)
        best: GoToSurfDecision | None = None
        for destination_x, destination_y in candidates:
            decision = self._score_go_to_candidate(
                bot,
                target,
                wave,
                destination_x,
                destination_y,
                max_speed,
                field_margin,
            )
            if decision is None:
                continue
            if best is None or decision.danger < best.danger:
                best = decision

        if best is None:
            return None

        return GoToSurfDecision(
            x=best.x,
            y=best.y,
            danger=best.danger,
            candidates=len(candidates),
            wave_kind=best.wave_kind,
            hit_guess_factor=best.hit_guess_factor,
            hit_bin=best.hit_bin,
            hit_turn=best.hit_turn,
            direction=best.direction,
            profile_danger=best.profile_danger,
            ensemble_danger=best.ensemble_danger,
            ensemble_samples=best.ensemble_samples,
            ensemble_weight=best.ensemble_weight,
            wall_risk=best.wall_risk,
            distance_risk=best.distance_risk,
            travel_risk=best.travel_risk,
        )

    def clear_round_state(self) -> None:
        self._wave_store.clear_round_state()
        self._shadow_bullets.clear()
        self._last_switch_turn.clear()

    def remove_target(self, target_id: int, clear_profile: bool = True) -> None:
        self._wave_store.remove_target(target_id)
        if clear_profile:
            self._profile_store.remove_target(target_id)
        self._last_switch_turn.pop(target_id, None)

    def _decision(
        self,
        direction: int,
        changed: bool,
        reason: str,
        target_id: int,
        bucket: int,
        current_direction: int,
    ) -> FlatteningDecision:
        alternative = -1 if current_direction >= 0 else 1
        return FlatteningDecision(
            direction=direction,
            changed=changed,
            reason=reason,
            bucket=bucket,
            current_count=self._count(target_id, bucket, current_direction),
            alternative_count=self._count(target_id, bucket, alternative),
        )

    def _count(self, target_id: int, bucket: int, direction: int) -> float:
        wave = self._best_wave(target_id)
        if wave is None:
            return 0.0
        offset_bin = self.config.bin_count // 2 + (1 if direction >= 0 else -1)
        return self._smoothed_count(target_id, bucket, offset_bin)

    def _decay_if_needed(self, target_id: int) -> None:
        self._profile_store._decay_if_needed(target_id)

    def _record_visit(self, wave: MovementWave, bin_index: int, weight: float) -> float:
        return self._profile_store.record(wave, bin_index, weight)

    def _wave_features(
        self,
        bot: Bot,
        target: TargetSnapshot,
        distance: float,
        bullet_speed: float,
        acceleration: float,
        direction_change_age: int,
        decel_age: int,
    ) -> MovementWaveFeatures:
        target_to_bot = math.atan2(bot.y - target.y, bot.x - target.x)
        bot_heading = math.radians(bot.direction)
        velocity_x = math.cos(bot_heading) * bot.speed
        velocity_y = math.sin(bot_heading) * bot.speed
        radial_x = math.cos(target_to_bot)
        radial_y = math.sin(target_to_bot)
        lateral_x = -radial_y
        lateral_y = radial_x
        return MovementWaveFeatures(
            lateral_velocity=velocity_x * lateral_x + velocity_y * lateral_y,
            advancing_velocity=velocity_x * radial_x + velocity_y * radial_y,
            bullet_flight_time=distance / max(0.1, bullet_speed),
            acceleration=acceleration,
            direction_change_age=max(0, direction_change_age),
            decel_age=max(0, decel_age),
            wall_distance=min(bot.x, bot.arena_width - bot.x, bot.y, bot.arena_height - bot.y),
        )

    def _distance_bucket(self, distance: float) -> int:
        if distance < self.config.near_distance:
            return 0
        if distance < self.config.mid_distance:
            return 1
        return 2

    def _best_wave(self, target_id: int) -> MovementWave | None:
        candidates = self._wave_store.for_target(target_id)
        if not candidates:
            return None
        return max(candidates, key=lambda wave: wave.fired_turn)

    def _surf_wave(self, bot: Bot, target_id: int) -> MovementWave | None:
        return self._surfing.surf_wave(bot, target_id)

    def _candidate_score(
        self,
        bot: Bot,
        wave: MovementWave,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
        use_surfing: bool,
    ) -> float:
        if use_surfing:
            projected_x, projected_y = self._project_surf_position(
                bot,
                wave,
                strafe_offset,
                move_speed,
                field_margin,
                direction,
            )
        else:
            projected_x, projected_y = self._project_position(
                bot,
                body_bearing,
                strafe_offset,
                move_speed,
                field_margin,
                direction,
            )
        guess_factor = self._guess_factor(wave, projected_x, projected_y)
        bin_index = self._bin_index(guess_factor)
        if use_surfing:
            return self._danger(wave, bin_index, bot)
        return self._smoothed_count(wave.target_id, wave.distance_bucket, bin_index)

    def _project_position(
        self,
        bot: Bot,
        body_bearing: float,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
    ) -> tuple[float, float]:
        movement_bearing = math.radians(bot.direction + body_bearing + strafe_offset * direction)
        distance = move_speed * self.config.lookahead_ticks
        return (
            clamp(bot.x + math.cos(movement_bearing) * distance, field_margin, bot.arena_width - field_margin),
            clamp(bot.y + math.sin(movement_bearing) * distance, field_margin, bot.arena_height - field_margin),
        )

    def _project_surf_position(
        self,
        bot: Bot,
        wave: MovementWave,
        strafe_offset: float,
        move_speed: float,
        field_margin: float,
        direction: int,
    ) -> tuple[float, float]:
        projected_x = bot.x
        projected_y = bot.y
        speed = max(0.1, abs(move_speed))
        for tick in range(1, self.config.surf_max_ticks + 1):
            move_bearing = self._surf_move_bearing(
                projected_x,
                projected_y,
                wave,
                strafe_offset,
                direction,
                field_margin,
                bot.arena_width,
                bot.arena_height,
            )
            projected_x = clamp(
                projected_x + math.cos(math.radians(move_bearing)) * speed,
                field_margin,
                bot.arena_width - field_margin,
            )
            projected_y = clamp(
                projected_y + math.sin(math.radians(move_bearing)) * speed,
                field_margin,
                bot.arena_height - field_margin,
            )
            wave_radius = wave.bullet_speed * max(0, bot.turn_number + tick - wave.fired_turn)
            distance = math.hypot(projected_x - wave.source_x, projected_y - wave.source_y)
            if wave_radius + self.config.surf_intercept_margin >= distance:
                break
        return projected_x, projected_y

    def _surf_move_bearing(
        self,
        x: float,
        y: float,
        wave: MovementWave,
        strafe_offset: float,
        direction: int,
        field_margin: float,
        arena_width: float,
        arena_height: float,
    ) -> float:
        bearing_to_source = self._absolute_bearing(x, y, wave.source_x, wave.source_y)
        move_bearing = bearing_to_source + strafe_offset * direction
        smoothing_step = -self.config.wall_smoothing_degrees * direction
        for _ in range(self.config.wall_smoothing_attempts):
            stick_x = x + math.cos(math.radians(move_bearing)) * self.config.wall_stick
            stick_y = y + math.sin(math.radians(move_bearing)) * self.config.wall_stick
            if field_margin <= stick_x <= arena_width - field_margin and field_margin <= stick_y <= arena_height - field_margin:
                return move_bearing
            move_bearing += smoothing_step
        return move_bearing

    def _go_to_candidate_points(self, bot: Bot, target: TargetSnapshot, field_margin: float) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        source_to_self = self._absolute_bearing(target.x, target.y, bot.x, bot.y)
        seen: set[tuple[int, int]] = set()
        for distance in self.config.goto_candidate_distances:
            for offset in self.config.goto_candidate_angle_offsets:
                bearing = math.radians(source_to_self + offset)
                x = bot.x + math.cos(bearing) * distance
                y = bot.y + math.sin(bearing) * distance
                if not (field_margin <= x <= bot.arena_width - field_margin):
                    continue
                if not (field_margin <= y <= bot.arena_height - field_margin):
                    continue
                key = (round(x / 8), round(y / 8))
                if key in seen:
                    continue
                seen.add(key)
                points.append((x, y))
        return points

    def _score_go_to_candidate(
        self,
        bot: Bot,
        target: TargetSnapshot,
        wave: MovementWave,
        destination_x: float,
        destination_y: float,
        max_speed: float,
        field_margin: float,
    ) -> GoToSurfDecision | None:
        hit_x, hit_y, hit_turn = self._simulate_go_to_wave_hit(
            bot,
            wave,
            destination_x,
            destination_y,
            max_speed,
            field_margin,
        )
        if hit_turn <= 0:
            return None

        guess_factor = self._guess_factor(wave, hit_x, hit_y)
        bin_index = self._bin_index(guess_factor)
        danger_breakdown = self._danger_breakdown(wave, bin_index)
        learned_danger = danger_breakdown.total_danger
        if wave.kind == "expected":
            learned_danger *= self.config.goto_wave_kind_expected_multiplier
        wall_risk = self._go_to_wall_risk(bot, hit_x, hit_y, field_margin)
        distance_risk = self._go_to_target_distance_risk(hit_x, hit_y, target)
        travel_risk = math.hypot(destination_x - bot.x, destination_y - bot.y) * self.config.goto_travel_weight
        danger = learned_danger + wall_risk + distance_risk + travel_risk
        direction = self._go_to_lateral_direction(bot, target, destination_x, destination_y)
        return GoToSurfDecision(
            x=destination_x,
            y=destination_y,
            danger=danger,
            candidates=0,
            wave_kind=wave.kind,
            hit_guess_factor=guess_factor,
            hit_bin=bin_index,
            hit_turn=hit_turn,
            direction=direction,
            profile_danger=danger_breakdown.profile_danger,
            ensemble_danger=danger_breakdown.ensemble_danger,
            ensemble_samples=danger_breakdown.ensemble_samples,
            ensemble_weight=danger_breakdown.ensemble_weight,
            wall_risk=wall_risk,
            distance_risk=distance_risk,
            travel_risk=travel_risk,
        )

    def _simulate_go_to_wave_hit(
        self,
        bot: Bot,
        wave: MovementWave,
        destination_x: float,
        destination_y: float,
        max_speed: float,
        field_margin: float,
    ) -> tuple[float, float, int]:
        state = RobotMovementState(x=bot.x, y=bot.y, direction=bot.direction, speed=bot.speed)
        speed = min(MAX_ROBOT_SPEED, abs(max_speed))
        for tick in range(1, self.config.surf_max_ticks + 1):
            move_bearing = self._absolute_bearing(state.x, state.y, destination_x, destination_y)
            distance_remaining = math.hypot(destination_x - state.x, destination_y - state.y)
            state = predict_robot_movement(
                state,
                move_bearing,
                max_speed=speed,
                distance_remaining=distance_remaining,
                field_margin=field_margin,
                arena_width=bot.arena_width,
                arena_height=bot.arena_height,
            )
            wave_radius = wave.bullet_speed * max(0, bot.turn_number + tick - wave.fired_turn)
            distance_to_wave_source = math.hypot(state.x - wave.source_x, state.y - wave.source_y)
            if wave_radius + self.config.surf_intercept_margin >= distance_to_wave_source:
                return state.x, state.y, tick
            if distance_remaining <= 1.0 and abs(state.speed) <= 0.2:
                return state.x, state.y, tick
        return state.x, state.y, self.config.surf_max_ticks

    def _go_to_wall_risk(self, bot: Bot, x: float, y: float, field_margin: float) -> float:
        margin = min(x, bot.arena_width - x, y, bot.arena_height - y)
        if margin <= field_margin:
            return self.config.goto_wall_weight
        return self.config.goto_wall_weight / max(1.0, margin - field_margin + 1.0)

    def _go_to_target_distance_risk(self, x: float, y: float, target: TargetSnapshot) -> float:
        distance = math.hypot(x - target.x, y - target.y)
        risk = 0.0
        if distance < self.config.goto_min_target_distance:
            close_error = self.config.goto_min_target_distance - distance
            risk += close_error * close_error * self.config.goto_target_distance_weight
            closeness = close_error / max(1.0, self.config.goto_min_target_distance)
            risk += closeness * closeness * self.config.goto_close_enemy_weight
        elif distance > self.config.goto_max_target_distance:
            far_error = distance - self.config.goto_max_target_distance
            risk += far_error * far_error * self.config.goto_target_distance_weight
        else:
            preferred_error = abs(distance - self.config.goto_preferred_target_distance)
            risk += preferred_error * preferred_error * self.config.goto_target_distance_weight * 0.12
        return risk

    def _go_to_lateral_direction(
        self,
        bot: Bot,
        target: TargetSnapshot,
        destination_x: float,
        destination_y: float,
    ) -> int:
        current_x = bot.x - target.x
        current_y = bot.y - target.y
        destination_vector_x = destination_x - target.x
        destination_vector_y = destination_y - target.y
        cross = current_x * destination_vector_y - current_y * destination_vector_x
        if cross > 0.001:
            return 1
        if cross < -0.001:
            return -1
        return 0

    def _danger(self, wave: MovementWave, bin_index: int, bot: Bot | None = None) -> float:
        danger = self._danger_breakdown(wave, bin_index).total_danger
        if bot is not None and self._has_bullet_shadow(bot, wave, bin_index):
            return danger * self.config.bullet_shadow_danger_multiplier
        return danger

    def _danger_breakdown(self, wave: MovementWave, bin_index: int) -> MovementDangerBreakdown:
        return self._danger_model.breakdown(wave, bin_index)

    def _has_bullet_shadow(self, bot: Bot, wave: MovementWave, bin_index: int) -> bool:
        if not self.config.bullet_shadow_enabled or not self._shadow_bullets:
            return False
        if wave.kind != "confirmed":
            return False
        start_turn = max(bot.turn_number, wave.fired_turn + 1)
        end_turn = min(
            bot.turn_number + self.config.bullet_shadow_max_ticks,
            wave.fired_turn + self.config.bullet_shadow_max_ticks,
        )
        for bullet in self._shadow_bullets:
            first_turn = max(start_turn, bullet.fired_turn + 1)
            for turn in range(first_turn, end_turn + 1):
                previous_x, previous_y = self._shadow_bullet_position(bullet, turn - 1)
                bullet_x, bullet_y = self._shadow_bullet_position(bullet, turn)
                if not self._point_inside_field(bot, previous_x, previous_y) and not self._point_inside_field(
                    bot, bullet_x, bullet_y
                ):
                    break
                wave_radius = wave.bullet_speed * max(0, turn - wave.fired_turn)
                shadow_x, shadow_y = self._closest_point_on_segment(
                    wave.source_x,
                    wave.source_y,
                    previous_x,
                    previous_y,
                    bullet_x,
                    bullet_y,
                )
                distance_to_wave_source = math.hypot(shadow_x - wave.source_x, shadow_y - wave.source_y)
                if abs(distance_to_wave_source - wave_radius) > self.config.bullet_shadow_radius_margin:
                    continue
                shadow_bin = self._bin_index(self._guess_factor(wave, shadow_x, shadow_y))
                if abs(shadow_bin - bin_index) <= self.config.bullet_shadow_bin_radius:
                    return True
        return False

    def _expire_shadow_bullets(self, bot: Bot) -> None:
        if not self._shadow_bullets:
            return
        remaining: list[ShadowBullet] = []
        for bullet in self._shadow_bullets:
            age = bot.turn_number - bullet.fired_turn
            if age < 0 or age > self.config.bullet_shadow_max_ticks:
                continue
            bullet_x, bullet_y = self._shadow_bullet_position(bullet, bot.turn_number)
            if self._point_inside_field(bot, bullet_x, bullet_y):
                remaining.append(bullet)
        self._shadow_bullets = remaining

    @staticmethod
    def _shadow_bullet_position(bullet: ShadowBullet, turn: int) -> tuple[float, float]:
        age = max(0, turn - bullet.fired_turn)
        bearing = math.radians(bullet.direction)
        return (
            bullet.source_x + math.cos(bearing) * bullet.bullet_speed * age,
            bullet.source_y + math.sin(bearing) * bullet.bullet_speed * age,
        )

    @staticmethod
    def _point_inside_field(bot: Bot, x: float, y: float) -> bool:
        return 0.0 <= x <= bot.arena_width and 0.0 <= y <= bot.arena_height

    @staticmethod
    def _closest_point_on_segment(
        point_x: float,
        point_y: float,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
    ) -> tuple[float, float]:
        segment_x = end_x - start_x
        segment_y = end_y - start_y
        length_squared = segment_x * segment_x + segment_y * segment_y
        if length_squared <= 0.0:
            return start_x, start_y
        projection = ((point_x - start_x) * segment_x + (point_y - start_y) * segment_y) / length_squared
        clamped_projection = clamp(projection, 0.0, 1.0)
        return (
            start_x + segment_x * clamped_projection,
            start_y + segment_y * clamped_projection,
        )

    def _smoothed_count(self, target_id: int, bucket: int, bin_index: int) -> float:
        return self._profile_store.smoothed_count(target_id, bucket, bin_index)

    def _bin_index(self, guess_factor: float) -> int:
        normalized = clamp((guess_factor + 1.0) / 2.0, 0.0, 1.0)
        return round(normalized * (self.config.bin_count - 1))

    def _guess_factor(self, wave: MovementWave, x: float, y: float) -> float:
        bearing = self._absolute_bearing(wave.source_x, wave.source_y, x, y)
        bearing_offset = self._relative_bearing(bearing, wave.direct_bearing)
        return guess_factor_from_offset(
            bearing_offset,
            wave.lateral_direction,
            wave.max_escape_angle_positive,
            wave.max_escape_angle_negative,
        )

    @staticmethod
    def _lateral_direction(bot: Bot, target: TargetSnapshot) -> int:
        target_to_bot = math.atan2(bot.y - target.y, bot.x - target.x)
        bot_heading = math.radians(bot.direction)
        lateral_velocity = bot.speed * math.sin(bot_heading - target_to_bot)
        if lateral_velocity > 0.3:
            return 1
        if lateral_velocity < -0.3:
            return -1
        return 0

    @staticmethod
    def _absolute_bearing(source_x: float, source_y: float, target_x: float, target_y: float) -> float:
        return math.degrees(math.atan2(target_y - source_y, target_x - source_x))

    @staticmethod
    def _relative_bearing(angle: float, reference: float) -> float:
        return ((angle - reference + 180) % 360) - 180

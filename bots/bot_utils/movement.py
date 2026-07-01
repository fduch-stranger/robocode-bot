import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_utils.physics import bullet_speed_for_power
from bot_utils.tank_math import TargetSnapshot, clamp
from bot_utils.wave_math import guess_factor_from_offset, wall_limited_escape_angle_from_state


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


@dataclass(frozen=True)
class FlatteningDecision:
    direction: int
    changed: bool
    reason: str
    bucket: int
    current_count: float
    alternative_count: float


@dataclass(frozen=True)
class MovementProfileVisit:
    target_id: int
    guess_factor: float
    bin_index: int
    bucket: int
    visits: float
    wave_age: int


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
        self._profile: dict[tuple[int, int, int], float] = {}
        self._waves: list[MovementWave] = []
        self._last_switch_turn: dict[int, int] = {}

    def record_enemy_fire(
        self,
        bot: Bot,
        target: TargetSnapshot,
        fire_power: float,
        wave_kind: str = "confirmed",
    ) -> MovementWave | None:
        distance = math.hypot(bot.x - target.x, bot.y - target.y)
        if not (self.config.min_distance <= distance <= self.config.max_distance):
            return None

        if wave_kind == "confirmed":
            self._waves = [
                wave
                for wave in self._waves
                if not (
                    wave.target_id == target.bot_id
                    and wave.kind == "expected"
                    and 0 <= bot.turn_number - wave.fired_turn <= 4
                )
            ]

        bullet_speed = bullet_speed_for_power(fire_power)
        wave_lateral_direction = self._lateral_direction(bot, target) or 1
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
        )
        self._waves.append(wave)
        return wave

    def update(self, bot: Bot) -> list[MovementProfileVisit]:
        visits: list[MovementProfileVisit] = []
        remaining_waves: list[MovementWave] = []
        for wave in self._waves:
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
            key = (wave.target_id, wave.distance_bucket, bin_index)
            self._profile[key] = self._profile.get(key, 0.0) + 1.0
            self._decay_if_needed(wave.target_id)
            visits.append(
                MovementProfileVisit(
                    target_id=wave.target_id,
                    guess_factor=guess_factor,
                    bin_index=bin_index,
                    bucket=wave.distance_bucket,
                    visits=self._profile[key],
                    wave_age=wave_age,
                )
            )
        self._waves = remaining_waves
        return visits

    def record_bullet_hit(self, bot: Bot, target_id: int, bullet_power: float) -> MovementProfileVisit | None:
        if not self._waves:
            return None

        bullet_speed = bullet_speed_for_power(bullet_power)
        candidates = [
            wave
            for wave in self._waves
            if wave.target_id == target_id and abs(wave.bullet_speed - bullet_speed) <= 1.2
        ]
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
        key = (wave.target_id, wave.distance_bucket, bin_index)
        self._profile[key] = self._profile.get(key, 0.0) + self.config.bullet_hit_visit_weight
        self._decay_if_needed(wave.target_id)
        self._waves = [candidate for candidate in self._waves if candidate is not wave]
        return MovementProfileVisit(
            target_id=wave.target_id,
            guess_factor=guess_factor,
            bin_index=bin_index,
            bucket=wave.distance_bucket,
            visits=self._profile[key],
            wave_age=max(1, bot.turn_number - wave.fired_turn),
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

    def clear_round_state(self) -> None:
        self._waves.clear()
        self._last_switch_turn.clear()

    def remove_target(self, target_id: int, clear_profile: bool = True) -> None:
        self._waves = [wave for wave in self._waves if wave.target_id != target_id]
        if clear_profile:
            self._profile = {key: value for key, value in self._profile.items() if key[0] != target_id}
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
        total = sum(value for key, value in self._profile.items() if key[0] == target_id)
        if total <= self.config.profile_decay_after:
            return
        for key in list(self._profile):
            if key[0] == target_id:
                self._profile[key] *= 0.5

    def _distance_bucket(self, distance: float) -> int:
        if distance < self.config.near_distance:
            return 0
        if distance < self.config.mid_distance:
            return 1
        return 2

    def _best_wave(self, target_id: int) -> MovementWave | None:
        candidates = [wave for wave in self._waves if wave.target_id == target_id]
        if not candidates:
            return None
        return max(candidates, key=lambda wave: wave.fired_turn)

    def _surf_wave(self, bot: Bot, target_id: int) -> MovementWave | None:
        candidates = [wave for wave in self._waves if wave.target_id == target_id]
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
            return self._danger(wave.target_id, wave.distance_bucket, bin_index)
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

    def _danger(self, target_id: int, bucket: int, bin_index: int) -> float:
        return self._smoothed_count(target_id, bucket, bin_index) + self.config.unvisited_bin_danger

    def _smoothed_count(self, target_id: int, bucket: int, bin_index: int) -> float:
        score = 0.0
        for offset, weight in ((0, 1.0), (-1, 0.55), (1, 0.55), (-2, 0.25), (2, 0.25)):
            neighbor = bin_index + offset
            if 0 <= neighbor < self.config.bin_count:
                score += self._profile.get((target_id, bucket, neighbor), 0.0) * weight
        return score

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

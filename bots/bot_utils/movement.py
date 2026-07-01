import math
from dataclasses import dataclass

from robocode_tank_royale.bot_api import Bot

from bot_utils.tank_math import TargetSnapshot, clamp


@dataclass(frozen=True)
class MovementFlatteningConfig:
    min_distance: float = 150.0
    max_distance: float = 700.0
    near_distance: float = 280.0
    mid_distance: float = 480.0
    bin_count: int = 31
    switch_margin: float = 1.5
    switch_cooldown: int = 28
    lookahead_ticks: int = 14
    surf_max_ticks: int = 80
    surf_intercept_margin: float = 18.0
    wall_smoothing_degrees: float = 12.0
    wall_smoothing_attempts: int = 8
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
    fired_turn: int
    distance_bucket: int
    kind: str = "confirmed"


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

        wave = MovementWave(
            target_id=target.bot_id,
            source_x=target.x,
            source_y=target.y,
            direct_bearing=self._absolute_bearing(target.x, target.y, bot.x, bot.y),
            lateral_direction=self._lateral_direction(bot, target) or 1,
            bullet_speed=max(0.1, 20 - 3 * fire_power),
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

        bullet_speed = max(0.1, 20 - 3 * bullet_power)
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
        self._profile.clear()
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
        smoothing_step = self.config.wall_smoothing_degrees * direction
        for _ in range(self.config.wall_smoothing_attempts):
            next_x = x + math.cos(math.radians(move_bearing)) * 8
            next_y = y + math.sin(math.radians(move_bearing)) * 8
            if field_margin <= next_x <= arena_width - field_margin and field_margin <= next_y <= arena_height - field_margin:
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
        max_escape_angle = math.degrees(math.asin(min(1.0, 8 / wave.bullet_speed)))
        return clamp((bearing_offset / max_escape_angle) * wave.lateral_direction, -1.0, 1.0)

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
